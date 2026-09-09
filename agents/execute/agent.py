#!/usr/bin/env python3
"""執行エージェント。発火後に、地図と遺志どおりに動く。
LLM がするのは文面（解約依頼・遺族への手紙・レポートの要約）だけ。何をするかの決定は決定的で、全部ゲートを通る。

  順序: 止める（解約依頼・連携解除）→ 渡す（存在を伝える・所有権移転の案内）→ ハブは最後（依存が残る限り閉じない）
  ブレーキ: 発火から 7 日、本人の活動が一つでも見えたら中止（brake_ok が False なら何もしない）

  python agent.py --plan  data/assets.json data/will.json     → 計画だけ表示（ゲートの判定つき）
  python agent.py --run   data/assets.json data/will.json     → 実行（outbox に手紙、report.md、audit）
"""
from __future__ import annotations
import json, os, sys, asyncio, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(ROOT, "agents", "gate")); sys.path.insert(0, os.path.join(ROOT, "agents", "watch"))
from policy import gate, Asset, Context
import policy

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE"); os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "forward-vector-470012-n8"); os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
MODEL = os.environ.get("ATONOKOTO_MODEL", "gemini-3.5-flash")
BRAKE_DAYS = 7

def load_map(assets_path, will_path):
    a = json.load(open(assets_path)); a = a if isinstance(a, list) else a.get("assets", [])
    w = json.load(open(will_path)) if os.path.exists(will_path) else {}
    out = []
    for x in a:
        n = x.get("name") or x.get("service")
        if not n: continue
        wv = w.get(n, {})
        out.append({"name": n, "category": x.get("category"), "cost": x.get("monthly_cost", 0) or 0, "billing_via": x.get("billing_via", "free"),
                    "login_via": wv.get("login") or x.get("login_via", "password"), "depends_on": x.get("depends_on") or [],
                    "will": wv.get("will", "undecided"), "to": wv.get("to"), "sealed": bool(wv.get("sealed")),
                    "hub": bool(x.get("hub")) or ("アカウント" in n and x.get("category") == "基盤") or n in ("Apple ID", "Yahoo! JAPAN ID")})
    return out

def plan(assets: list[dict]) -> list[dict]:
    """決定的な計画。1 資産に 1 つの主操作。ハブは最後。"""
    hubs = {a["name"] for a in assets if a["hub"]}
    dependents = {h: [a["name"] for a in assets if h in a["depends_on"] or (a["login_via"] == "google" and "google" in h.lower())] for h in hubs}
    steps = []
    for a in assets:
        if a["hub"]: continue
        if a["will"] == "erase":
            if a["cost"] > 0:
                steps.append({"track": "stop", "action": "cancel_subscription", "asset": a["name"], "how": "sealed_credential" if a["sealed"] else "request_mail"})
            steps.append({"track": "stop", "action": "revoke_oauth", "asset": a["name"], "how": "request_mail" if a["login_via"] != "atonokoto" else "api"})
        elif a["will"] == "give":
            steps.append({"track": "hand", "action": "share", "asset": a["name"], "to": a["to"], "how": "notify_recipient"})
        elif a["will"] == "keep":
            steps.append({"track": "none", "action": "report", "asset": a["name"], "how": "mention_in_report"})
        else:
            steps.append({"track": "none", "action": "report", "asset": a["name"], "how": "undecided_in_report"})
    # ハブは最後。Google アカウント自体は閉じない（Google の無効化管理ツールに委ねる）
    for a in assets:
        if not a["hub"]: continue
        if a["will"] == "erase" and "google" not in a["name"].lower():
            steps.append({"track": "hand", "action": "close_hub", "asset": a["name"], "how": "request_mail", "dependents": dependents.get(a["name"], [])})
        else:
            steps.append({"track": "none", "action": "report", "asset": a["name"], "how": "google_iam" if "google" in a["name"].lower() else "mention_in_report", "dependents": dependents.get(a["name"], [])})
    order = {"stop": 0, "hand": 1, "none": 2}
    steps.sort(key=lambda st: (order[st["track"]], st["action"] == "close_hub"))
    return steps

def brake_ok(fired_at: dt.date | None, last_activity: dict, today: dt.date) -> tuple[bool, str]:
    """発火から 7 日経ち、その間に本人の活動が無いときだけ True。"""
    if not fired_at: return False, "発火していない"
    if (today - fired_at).days < BRAKE_DAYS: return False, f"最後の通知から {BRAKE_DAYS} 日待つ（あと {BRAKE_DAYS - (today - fired_at).days} 日）"
    for src, la in (last_activity or {}).items():
        if la and dt.date.fromisoformat(la[:10]) >= fired_at: return False, f"発火後に本人の活動が見えた（{src} {la[:10]}）。中止して いつもどおり に戻す"
    return True, "7 日間、本人の動きは見えなかった。ブレーキは掛からず、執行に進む"

async def letter(kind: str, asset: dict, person: str, recipient: str | None) -> str:
    """文面だけ LLM。資格情報・口座・パスワードは絶対に書かない。"""
    try:
        from pydantic import BaseModel, Field
        from google.adk.agents import LlmAgent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types
    except Exception as e:
        return f"（文面を作れない: {e}）"
    class Letter(BaseModel):
        subject: str = Field(description="件名")
        body: str = Field(description="本文。丁寧で短く。5〜8 文")
    spec = {"cancel": f"{asset['name']} の運営宛てに、契約者（{person}）が亡くなったため契約の解約を依頼する手紙。本文の末尾に、そのままの文字列で「ご遺族の連絡先: [遺族の連絡先]」という行を必ず入れる。パスワードや口座番号は書かない",
            "share": f"{recipient} 宛てに、{person} が生前に「{asset['name']} をあなたに渡す」と決めていたことを伝える手紙。何が渡るか、次に何をすればよいか（あとのことから案内が届く）を書く。パスワードは渡さないと明記する",
            "notice": f"{person} 本人宛ての最後の通知。あなたが登録した確認者 2 人が「本人と連絡が取れない」と答えたので、{BRAKE_DAYS} 日後に生前に決めたことを実行すること、この {BRAKE_DAYS} 日の間に Google を一度でも使えば自動的に止まること、を静かに伝える。本文の末尾に「返事は要りません。」という一文を必ず入れる"}[kind]
    agent = LlmAgent(name="letter", model=MODEL, output_schema=Letter, output_key="l",
        instruction="あなたは「あとのこと」の書記。頼まれた手紙を日本語で書く。事実だけ。感情を煽らない。資格情報・パスワード・口座番号・住所は絶対に書かない。出力は JSON だけ")
    svc = InMemorySessionService(); sid = f"l{abs(hash(spec)) % 10**8}"; await svc.create_session(app_name="atonokoto", user_id="x", session_id=sid)
    runner = Runner(agent=agent, app_name="atonokoto", session_service=svc)
    out = None
    async for ev in runner.run_async(user_id="x", session_id=sid, new_message=types.Content(role="user", parts=[types.Part(text=spec)])):
        if ev.is_final_response() and ev.content and ev.content.parts and ev.content.parts[0].text: out = ev.content.parts[0].text
    try:
        j = json.loads(out); return f"件名: {j['subject']}\n\n{j['body']}"
    except Exception: return "（文面を作れなかった）"

FORBIDDEN_IN_LETTER = ("パスワード:", "password:", "口座番号", "暗証", "1234-567890")

def execute(assets, steps, ctx: Context, person: str, outbox: str, audit_path: str, do_letters=True, today=None, round_id: str | None = None) -> dict:
    today = today or dt.date.today()
    # 監査鎖はこの執行だけのもの（グローバルを共有しない。並行する別の執行やデモと交差しない）
    chain = [f"genesis:{round_id or today.isoformat()}"]
    audit = policy.Auditor(audit_path, chain)
    os.makedirs(outbox, exist_ok=True)
    by = {a["name"]: a for a in assets}
    remaining = {a["name"]: True for a in assets}
    results = []
    for st in steps:
        a = by[st["asset"]]
        pa = Asset(a["name"], a["will"], is_hub=a["hub"], paid_total=a["cost"] * 12, dependents=st.get("dependents", []), to=a.get("to"))
        d = gate(st["action"], pa, ctx, auditor=audit) if st["action"] != "report" else None
        allowed = (d.allowed if d else True); reason = (d.reason if d else "報告のみ")
        r = {**st, "allowed": allowed, "reason": reason}
        if allowed and do_letters and st["action"] in ("cancel_subscription", "share", "close_hub"):
            kind = "share" if st["action"] == "share" else "cancel"
            text = asyncio.run(letter(kind, a, person, a.get("to")))
            if any(f in text for f in FORBIDDEN_IN_LETTER):
                text = "（文面に秘密が混ざったため破棄。手動で作成）"; r["letter_rejected"] = True
            fn = os.path.join(outbox, f"{today.isoformat()}_{st['action']}_{a['name']}.txt".replace("/", "_"))
            open(fn, "w").write(text); r["letter"] = fn
        if allowed and st["action"] != "report":
            remaining[a["name"]] = False
            ctx.remaining = remaining
        results.append(r)
    return {"date": today.isoformat(), "round": round_id, "results": results, "audit": audit_path, "chain_head": chain[0]}

def redact(text: str) -> str:
    """遺族に見せる前に、メールアドレス・電話番号・クレジットカード番号などを Sensitive Data Protection で伏せる。
    API が使えないときは正規表現で最低限を伏せる。"""
    import re
    try:
        import urllib.request
        from google.auth import default as _default
        from google.auth.transport.requests import Request as _Req
        c, project = _default(scopes=["https://www.googleapis.com/auth/cloud-platform"]); c.refresh(_Req())
        body = {"item": {"value": text},
                "inspectConfig": {"infoTypes": [{"name": n} for n in ("EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD_NUMBER", "JAPAN_BANK_ACCOUNT", "PASSWORD")]},
                "deidentifyConfig": {"infoTypeTransformations": {"transformations": [{"primitiveTransformation": {"replaceWithInfoTypeConfig": {}}}]}}}
        req = urllib.request.Request(f"https://dlp.googleapis.com/v2/projects/{os.environ.get('GOOGLE_CLOUD_PROJECT', project)}/locations/global/content:deidentify",
                                     data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {c.token}", "Content-Type": "application/json",
                                                                              "x-goog-user-project": os.environ.get("GOOGLE_CLOUD_PROJECT", project)})
        out = json.load(urllib.request.urlopen(req, timeout=20))["item"]["value"]
        return re.sub(r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b", "[PHONE_NUMBER]", out)   # 日本の電話番号は SDP が拾わないことがあるので二重に
    except Exception:
        text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text)
        text = re.sub(r"\b\d{2,4}-\d{2,4}-\d{3,4}\b", "[PHONE]", text)
        return re.sub(r"\b(?:\d[ -]?){13,16}\b", "[CARD]", text)

def report(assets, execution: dict, path: str, afterword: str | None = None):
    lines = [f"# 遺族へのご報告（{execution['date']}）", "", "本人が生前に決めたとおりに、次のことを行いました。パスワードや資格情報はこの報告に含めていません。", ""]
    if afterword and afterword.strip():
        # 本人が生前に書いた「あとがき」。確認者が揃って執行に進んだときだけ、ここで初めて開く
        lines += ["## 本人からのことば", "", afterword.strip()[:4000], ""]
    for track, title in (("stop", "止めたもの"), ("hand", "お渡しするもの"), ("none", "そのままにしたもの・お知らせ")):
        rs = [r for r in execution["results"] if r["track"] == track]
        if not rs: continue
        lines.append(f"## {title}")
        for r in rs:
            a = next(x for x in assets if x["name"] == r["asset"])
            what = {"cancel_subscription": "解約を依頼", "revoke_oauth": "連携の解除を依頼", "share": f"{a.get('to') or '（相手未定）'} へ存在を伝達", "close_hub": "アカウントの閉鎖を依頼", "report": {"google_iam": "Google の無効化管理ツールに委ねる（本人の設定どおり）", "mention_in_report": "触っていません（本人の意思）", "undecided_in_report": "本人が決めていなかったため、触っていません"}.get(r["how"], "報告")}[r["action"]]
            cost = f"（月額 ¥{a['cost']:,}）" if a["cost"] else ""
            lines.append(f"- {a['name']}{cost}: {what}" + ("" if r["allowed"] else f" → 実行せず（{r['reason']}）"))
        lines.append("")
    lines += ["## 記録", "全ての判定は監査記録（ハッシュ鎖つき）に残っています。何を渡すか・消すかは、確認者ではなく本人が生前に決めたものです。個人情報は Sensitive Data Protection で伏せています。"]
    open(path, "w").write(redact("\n".join(lines))); return path

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--plan"
    ap = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "assets.json")
    wp = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "data", "will.json")
    assets = load_map(ap, wp); steps = plan(assets)
    ctx = Context(confirmers=2, unlocked_tracks={"stop", "hand"}, remaining={a["name"]: True for a in assets})
    if mode == "--plan":
        for st in steps:
            a = next(x for x in assets if x["name"] == st["asset"])
            pa = Asset(a["name"], a["will"], is_hub=a["hub"], paid_total=a["cost"]*12, dependents=st.get("dependents", []), to=a.get("to"))
            d = gate(st["action"], pa, ctx, audit=False) if st["action"] != "report" else None
            print(f"  {st['track']:4s} {st['action']:20s} {st['asset']:24s} {st.get('how',''):18s} → {'許可' if (d is None or d.allowed) else '拒否: ' + d.reason}")
    else:
        ex = execute(assets, steps, ctx, "山田太郎", os.path.join(ROOT, "data", "outbox"), os.path.join(ROOT, "data", "audit_execute.jsonl"))
        rp = report(assets, ex, os.path.join(ROOT, "data", "report.md"))
        print(json.dumps(ex, ensure_ascii=False, indent=1)[:1500]); print("→", rp)
