#!/usr/bin/env python3
"""ポリシーゲート。執行エージェントが呼ぶ全ての操作は、実行前にここを通る。
LLM は関与しない。決定は決定的で、全件が監査記録に残る。

  gate(action, asset, will, ctx) -> Decision(allowed, reason)

設計（ARCHITECTURE.md）:
  - 遺志が keep のものは触らない
  - 取り消せない操作は、遺志が明示的に許したものだけ
  - ハブ（Google アカウント等）は、依存している資産が残っている間は閉じない
  - 返金は支払額を超えない
  - パスワード・認証情報そのものを渡す操作は存在しない（ここに来ても拒否）
  - 「止める」トラックと「渡す」トラックで解放される操作が違う
"""
from __future__ import annotations
import json, os, time, hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional

IRREVERSIBLE = {"delete_account", "delete_files", "close_hub", "transfer_ownership", "refund"}
STOP_TRACK = {"cancel_subscription", "revoke_oauth", "refund", "report"}          # 2人の確認で解放
HAND_TRACK = {"transfer_ownership", "share", "export", "delete_files", "delete_account", "close_hub"}  # 渡す側の解放
NEVER = {"reveal_password", "export_credentials", "reset_password_to"}           # 存在しない操作

@dataclass
class Asset:
    name: str
    will: str                      # give / erase / keep / undecided
    is_hub: bool = False
    paid_total: int = 0            # 返金の上限に使う
    dependents: list = field(default_factory=list)   # このハブに依存している資産名
    to: Optional[str] = None

@dataclass
class Context:
    confirmers: int = 0            # 発火時に揃った確認者の数
    unlocked_tracks: set = field(default_factory=set)   # {"stop", "hand"}
    remaining: dict = field(default_factory=dict)       # 資産名 -> 未処理か（True=まだ残っている）

@dataclass
class Decision:
    allowed: bool
    reason: str
    action: str
    asset: str
    at: float = field(default_factory=time.time)

AUDIT_PATH = os.environ.get("ATONOKOTO_AUDIT", os.path.join(os.path.dirname(__file__), "audit.jsonl"))

AUDIT_BUCKET = os.environ.get("ATONOKOTO_AUDIT_BUCKET")   # 追記専用（objectCreator のみ、保持 400 日）。設定があれば 1 判定 = 1 オブジェクト
_bucket_token = {"tok": None, "exp": 0}

def _upload_audit_object(name: str, rec: dict):
    """監査記録を追記専用バケットへ 1 オブジェクトとして書く。上書き禁止（ifGenerationMatch=0）。失敗しても判定は止めない。"""
    if not AUDIT_BUCKET: return
    try:
        import urllib.request, urllib.parse
        if time.time() > _bucket_token["exp"]:
            from google.auth import default as _default
            from google.auth.transport.requests import Request as _Req
            c, _ = _default(scopes=["https://www.googleapis.com/auth/devstorage.read_write"]); c.refresh(_Req())
            _bucket_token["tok"], _bucket_token["exp"] = c.token, time.time() + 1800
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{AUDIT_BUCKET}/o?uploadType=media&name={urllib.parse.quote(name, safe='')}&ifGenerationMatch=0"
        req = urllib.request.Request(url, data=json.dumps(rec, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {_bucket_token['tok']}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(json.dumps({"severity": "WARNING", "message": "atonokoto.audit_upload_failed", "error": str(e)[:120]}), flush=True)

class Auditor:
    """執行 1 回分の監査鎖。ファイルは呼び出し側が指定し、鎖の先頭は呼び出し側が持つ。追記専用バケットにも 1 判定 1 オブジェクトで残す。"""
    def __init__(self, path: str, chain: list, upload: bool = True):
        # upload=False はデモ用。鎖はファイルに残すが、本物の監査バケット（追記専用・400 日）には書かない
        self.path, self.chain, self.seq, self.round, self.upload = path, chain, 0, chain[0].replace(":", "_"), upload
    def write(self, d: "Decision"):
        rec = _audit(d, self.chain, self.path); self.seq += 1
        if self.upload: _upload_audit_object(f"gate/{self.round}/{self.seq:04d}-{rec['hash'][:12]}.json", rec)

def _audit(d: Decision, prev_hash: list, path: str | None = None):
    path = path or AUDIT_PATH
    rec = asdict(d); rec["prev"] = prev_hash[0]
    rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    prev_hash[0] = rec["hash"]
    with open(path, "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # Cloud Run では標準出力の JSON が Cloud Logging に構造化ログとして入り、監査バケット（400 日保持）に写される
    if os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"):
        print(json.dumps({"severity": "NOTICE", "message": "atonokoto.gate", "logName": "atonokoto-gate", **rec}, ensure_ascii=False), flush=True)
    return rec

_chain = ["genesis"]

def gate(action: str, asset: Asset, ctx: Context, amount: int = 0, audit: bool = True, auditor: "Auditor | None" = None) -> Decision:
    def out(ok, why):
        d = Decision(ok, why, action, asset.name)
        if auditor is not None: auditor.write(d)
        elif audit: _audit(d, _chain)
        return d
    if action in NEVER:
        return out(False, "そういう操作は無い（パスワードや認証情報は誰にも渡さない）")
    if action not in STOP_TRACK | HAND_TRACK:
        return out(False, f"未知の操作 {action}")
    if ctx.confirmers < 2:
        return out(False, f"確認者が足りない（{ctx.confirmers}/2）")
    track = "stop" if action in STOP_TRACK else "hand"
    if track not in ctx.unlocked_tracks:
        return out(False, f"{track} トラックが解放されていない")
    if asset.will == "keep":
        return out(False, "遺志は『触るな』")
    if asset.will == "undecided" and action in IRREVERSIBLE:
        return out(False, "遺志が未定のまま取り消せない操作はしない")
    if action in {"transfer_ownership", "share", "export"} and asset.will != "give":
        return out(False, "遺志が『渡す』ではない")
    if action in {"transfer_ownership", "share"} and not asset.to:
        return out(False, "渡す相手が決まっていない")
    if action in {"delete_account", "delete_files", "close_hub", "cancel_subscription", "revoke_oauth"} and asset.will != "erase":
        return out(False, "遺志が『消す』ではない")
    if action in {"close_hub", "delete_account"} and asset.is_hub:
        left = [d for d in asset.dependents if ctx.remaining.get(d, True)]
        if left:
            return out(False, f"依存が残っている: {', '.join(left)}")
    if action == "refund" and amount > asset.paid_total:
        return out(False, f"返金が支払額を超える（{amount} > {asset.paid_total}）")
    return out(True, "遺志どおり")

# ---------------- テスト ----------------
if __name__ == "__main__":
    import tempfile
    AUDIT_PATH = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
    both = Context(confirmers=2, unlocked_tracks={"stop", "hand"}, remaining={})
    stop_only = Context(confirmers=2, unlocked_tracks={"stop"}, remaining={})
    one = Context(confirmers=1, unlocked_tracks={"stop", "hand"}, remaining={})
    hub = Asset("Google アカウント", "erase", is_hub=True, dependents=["Netflix", "YouTube Premium"])
    cases = [
        # (説明, action, asset, ctx, amount, 期待)
        ("消す遺志のサブスクを止める", "cancel_subscription", Asset("Netflix", "erase"), both, 0, True),
        ("触るなの銀行を止めようとする", "cancel_subscription", Asset("三菱UFJ銀行", "keep"), both, 0, False),
        ("未定の資産を削除", "delete_files", Asset("Instagram", "undecided"), both, 0, False),
        ("確認者1人で執行", "cancel_subscription", Asset("Netflix", "erase"), one, 0, False),
        ("stop だけ解放で所有権移転", "transfer_ownership", Asset("GitHub", "give", to="田中"), stop_only, 0, False),
        ("両方解放で所有権移転", "transfer_ownership", Asset("GitHub", "give", to="田中"), both, 0, True),
        ("渡す相手が無い", "transfer_ownership", Asset("Notion", "give"), both, 0, False),
        ("依存が残るハブを閉じる", "close_hub", hub, Context(2, {"stop","hand"}, {"Netflix": True, "YouTube Premium": False}), 0, False),
        ("依存を全部処理してからハブを閉じる", "close_hub", hub, Context(2, {"stop","hand"}, {"Netflix": False, "YouTube Premium": False}), 0, True),
        ("過大な返金", "refund", Asset("Adobe Creative Cloud", "erase", paid_total=6480), both, 20000, False),
        ("支払額以内の返金", "refund", Asset("Adobe Creative Cloud", "erase", paid_total=6480), both, 6480, True),
        ("パスワードを渡す", "reveal_password", Asset("Google アカウント", "give", to="妻"), both, 0, False),
        ("認証情報の書き出し", "export_credentials", Asset("Google アカウント", "give", to="妻"), both, 0, False),
        ("渡す遺志の資産を消す", "delete_account", Asset("Slack", "give", to="会社"), both, 0, False),
        ("消す遺志の資産を共有", "share", Asset("Google Cloud", "erase"), both, 0, False),
        ("未知の操作", "format_disk", Asset("Google Cloud", "erase"), both, 0, False),
    ]
    bad = 0
    for desc, act, a, c, amt, exp in cases:
        d = gate(act, a, c, amt)
        ok = d.allowed == exp; bad += not ok
        print(f"  {'OK ' if ok else 'NG '} {desc:24s} → {'許可' if d.allowed else '拒否'}: {d.reason}")
    n = sum(1 for _ in open(AUDIT_PATH))
    # 監査鎖の検証
    prev = "genesis"; chain_ok = True
    for line in open(AUDIT_PATH):
        r = json.loads(line); h = r.pop("hash")
        chain_ok &= r["prev"] == prev and hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == h; prev = h
    print(f"\n{len(cases)-bad}/{len(cases)} 期待どおり / 監査記録 {n} 件, 鎖の検証 {'OK' if chain_ok else 'NG'}")
    raise SystemExit(bad)
