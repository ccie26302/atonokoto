#!/usr/bin/env python3
"""確認者の承認経路の試験（サーバ無し）。THREAT_MODEL の「承認経路 8/8」の実体。"""
import os, sys, json, datetime as dt, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents", "watch"))
import run as w
from state import State, fire
tmp = tempfile.mkdtemp()
w.DATA = tmp; w.OUTBOX = os.path.join(tmp, "outbox"); w.WHO = os.path.join(tmp, "confirmers.json"); w.VOTES = os.path.join(tmp, "confirmations.json"); w.KEYF = os.path.join(tmp, "confirm_key")
os.environ["ATONOKOTO_SMTP_JSON"] = ""   # 送らない（outbox 止まり）
json.dump([{"name":"妻","mail":"hanako@example.com"},{"name":"田中","mail":"tanaka@example.com"},{"name":"兄","mail":"ani@example.com"}], open(w.WHO,"w"), ensure_ascii=False)
T = dt.date(2026, 11, 10); st = State(name="WAITING", since=T, waiting_since=T)
n = w.notify_confirmers(st, "説明（試験）"); v = w.load_votes(); toks = {x["mail"]: t for t, x in v.items()}; rid = T.isoformat()
R = []
R.append(("リンクを 3 人に発行", n == 3))
R.append(("再通知で増えない（冪等）", w.notify_confirmers(st, "x") == 0))
R.append(("偽トークンは無効", "deadbeef" not in v))
v[toks["hanako@example.com"]]["vote"] = "unreachable"; w.save_votes(v)
R.append(("1 人では発火しない", w.unreachable_count(rid) == 1 and fire(State(name="WAITING", since=T, waiting_since=T), w.unreachable_count(rid), T).name == "WAITING"))
v[toks["tanaka@example.com"]]["vote"] = "unreachable"; w.save_votes(v)
R.append(("猶予の内は 2 人でも発火しない", fire(State(name="WAITING", since=T, waiting_since=T), w.unreachable_count(rid), T).name == "WAITING"))
R.append(("猶予（14 日）が過ぎれば 2 人で FIRED", fire(State(name="WAITING", since=T, waiting_since=T), w.unreachable_count(rid), T + dt.timedelta(days=14)).name == "FIRED"))
v2 = w.load_votes(); v2[toks["ani@example.com"]]["vote"] = "reachable"; w.save_votes(v2)
R.append(("誰かが『取れた』なら reachable_any", w.reachable_any(rid)))
R.append(("ラウンドが違えばトークンも違う", w.confirm_token("hanako@example.com", "2026-12-01") != toks["hanako@example.com"]))
R.append(("outbox にリンク入りの手紙（未送信の理由つき）", all("link" in json.load(open(os.path.join(w.OUTBOX, f))) and json.load(open(os.path.join(w.OUTBOX, f))).get("sent") is False for f in os.listdir(w.OUTBOX))))
for name, ok in R: print(f"  {'OK ' if ok else 'NG '} {name}")
print(f"{sum(o for _,o in R)}/{len(R)}"); shutil.rmtree(tmp); sys.exit(0 if all(o for _,o in R) else 1)
