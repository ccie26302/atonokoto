#!/usr/bin/env python3
"""送信。確認者へのリンク、本人への最後の通知、解約依頼、お渡しの手紙を実際に送る。

  送信元は atonokoto 自身のメールボックス（本人のアカウントは使わない）。SMTP の資格情報は Secret Manager から
  環境変数 ATONOKOTO_SMTP_JSON で受ける: {"host","port","user","password","from"}。無ければ送らず outbox に残す（sent: false）。

  送る前に必ず通す:
    - 宛先は本人が登録した確認者、または遺志で指定された相手、または本人だけ（それ以外へは送らない）
    - 本文に資格情報・口座番号が無い（FORBIDDEN）
    - 1 日の上限（既定 20 通）。超えたら止めて記録する
    - 送った事実を監査ログに残す（宛先は伏せる）
"""
from __future__ import annotations
import json, os, re, smtplib, ssl, datetime as dt, hashlib
from email.message import EmailMessage
from email.utils import formataddr

FORBIDDEN = ("パスワード:", "password:", "口座番号", "暗証", "1234-567890")
DAILY_LIMIT = int(os.environ.get("ATONOKOTO_MAIL_DAILY_LIMIT", "20"))
LEDGER = os.environ.get("ATONOKOTO_MAIL_LEDGER", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "mail_ledger.jsonl"))

SDP_TYPES = ("CREDIT_CARD_NUMBER", "JAPAN_BANK_ACCOUNT", "PASSWORD", "AUTH_TOKEN", "GCP_CREDENTIALS", "JSON_WEB_TOKEN", "ENCRYPTION_KEY")
def _sdp_findings(text: str) -> list[str]:
    """Sensitive Data Protection で資格情報・口座・カードを検査する。API が使えなければ空（リテラル検査だけが残る）。"""
    if os.environ.get("ATONOKOTO_SDP", "1") == "0": return []
    try:
        import urllib.request
        from google.auth import default as _default
        from google.auth.transport.requests import Request as _Req
        c, project = _default(scopes=["https://www.googleapis.com/auth/cloud-platform"]); c.refresh(_Req())
        proj = os.environ.get("GOOGLE_CLOUD_PROJECT", project)
        body = {"item": {"value": text}, "inspectConfig": {"infoTypes": [{"name": n} for n in SDP_TYPES], "minLikelihood": "POSSIBLE"}}
        req = urllib.request.Request(f"https://dlp.googleapis.com/v2/projects/{proj}/locations/global/content:inspect", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {c.token}", "Content-Type": "application/json", "x-goog-user-project": proj})
        r = json.load(urllib.request.urlopen(req, timeout=20))
        return sorted({f["infoType"]["name"] for f in r.get("result", {}).get("findings", [])})
    except Exception:
        return []

def config() -> dict | None:
    raw = os.environ.get("ATONOKOTO_SMTP_JSON")
    if not raw or raw.strip() in ("", "{}"): return None
    try: return json.loads(raw)
    except Exception: return None

def _sent_today() -> int:
    if not os.path.exists(LEDGER): return 0
    today = dt.date.today().isoformat()
    return sum(1 for line in open(LEDGER) if json.loads(line).get("date") == today and json.loads(line).get("sent"))

def _ledger(rec: dict):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"):
        print(json.dumps({"severity": "NOTICE", "message": "atonokoto.mail", **rec}, ensure_ascii=False), flush=True)

def send(to: str, subject: str, body: str, allowed_recipients: set[str], kind: str) -> dict:
    """送れたら sent=True。送らない理由は reason に残す。宛先は監査にはハッシュで残す。"""
    to_hash = hashlib.sha256(to.lower().encode()).hexdigest()[:12]
    rec = {"date": dt.date.today().isoformat(), "at": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind, "to_hash": to_hash, "sent": False}
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to or ""):
        rec["reason"] = "宛先の形式が不正"; _ledger(rec); return rec
    if to.lower() not in {a.lower() for a in allowed_recipients}:
        rec["reason"] = "宛先が登録された相手ではない"; _ledger(rec); return rec
    if any(f in body for f in FORBIDDEN) or any(f in subject for f in FORBIDDEN):
        rec["reason"] = "本文に秘密が混ざっている"; _ledger(rec); return rec
    hit = _sdp_findings(subject + "\n" + body)
    if hit:
        rec["reason"] = f"本文に秘密が混ざっている（SDP: {','.join(hit)}）"; _ledger(rec); return rec
    if _sent_today() >= DAILY_LIMIT:
        rec["reason"] = f"1 日の上限 {DAILY_LIMIT} 通に達した"; _ledger(rec); return rec
    cfg = config()
    if not cfg:
        rec["reason"] = "送信元が未設定（outbox に残す）"; _ledger(rec); return rec
    msg = EmailMessage()
    msg["From"] = formataddr(("あとのこと", cfg["from"])); msg["To"] = to; msg["Subject"] = subject
    msg["Auto-Submitted"] = "auto-generated"; msg.set_content(body)
    try:
        port = int(cfg.get("port", 587))
        if port == 465:
            with smtplib.SMTP_SSL(cfg["host"], port, context=ssl.create_default_context(), timeout=30) as s:
                s.login(cfg["user"], cfg["password"]); s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], port, timeout=30) as s:
                if cfg.get("starttls", True): s.starttls(context=ssl.create_default_context())
                if cfg.get("user"): s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        rec["sent"] = True
    except Exception as e:
        rec["reason"] = f"送信失敗: {str(e)[:120]}"
    _ledger(rec); return rec

if __name__ == "__main__":
    # ローカルの試験用 SMTP（TLS 無し）に対して送る: ATONOKOTO_SMTP_JSON='{"host":"127.0.0.1","port":8025,"from":"a@b.c","starttls":false}'
    import sys
    print(send(sys.argv[1], "あとのこと: 試験", "これは試験です。", {sys.argv[1]}, "test"))
