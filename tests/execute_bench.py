#!/usr/bin/env python3
"""執行エージェントの試験。
 1) 計画とゲート（決定的）: 触るな・未定は触らない、ハブは最後、Google アカウントは閉じずに IAM に委ねる、確認者不足では全部拒否
 2) 文面（LLM、N 回）: 解約依頼・お渡しの手紙・本人への最後の通知に、資格情報や口座が混ざらない／サービス名と必要な要素が入る"""
import os, sys, json, asyncio, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, ".."); sys.path.insert(0, os.path.join(ROOT, "agents", "execute")); sys.path.insert(0, os.path.join(ROOT, "agents", "gate"))
import agent as ex
from policy import Context

assets = ex.load_map(os.path.join(ROOT, "data", "assets.json"), os.path.join(ROOT, "data", "will_demo.json"))
steps = ex.plan(assets)
by = {a["name"]: a for a in assets}
T = []
touched = {s["asset"] for s in steps if s["action"] != "report"}
T.append(("触るな・未定の資産には操作が無い", not any(by[n]["will"] in ("keep", "undecided") for n in touched)))
T.append(("ハブの操作は最後", all(s["action"] != "close_hub" or i >= len(steps) - 3 for i, s in enumerate(steps))))
T.append(("Google アカウントは閉じずに Google に委ねる", any(s["asset"] == "Google アカウント" and s["how"] == "google_iam" for s in steps)))
T.append(("止める → 渡す の順", [s["track"] for s in steps if s["track"] != "none"] == sorted([s["track"] for s in steps if s["track"] != "none"], key=lambda t: {"stop":0,"hand":1}[t])))
ctx1 = Context(confirmers=1, unlocked_tracks={"stop", "hand"}, remaining={a["name"]: True for a in assets})
r1 = ex.execute(assets, steps, ctx1, "山田太郎", "/tmp/atonokoto_bench_outbox", "/tmp/atonokoto_bench_audit.jsonl", do_letters=False)
T.append(("確認者 1 人では操作が全部拒否", all(not r["allowed"] for r in r1["results"] if r["action"] != "report")))
ctx2 = Context(confirmers=2, unlocked_tracks={"stop"}, remaining={a["name"]: True for a in assets})
r2 = ex.execute(assets, steps, ctx2, "山田太郎", "/tmp/atonokoto_bench_outbox", "/tmp/atonokoto_bench_audit.jsonl", do_letters=False)
T.append(("stop だけ解放なら 渡す は拒否", all(not r["allowed"] for r in r2["results"] if r["track"] == "hand") and all(r["allowed"] for r in r2["results"] if r["track"] == "stop")))
T.append(("ブレーキ: 発火直後は動かない", not ex.brake_ok(dt.date(2026,11,1), {"gmail_read": "2026-10-20"}, dt.date(2026,11,3))[0]))
T.append(("ブレーキ: 7 日後に活動が無ければ解除", ex.brake_ok(dt.date(2026,11,1), {"gmail_read": "2026-10-20"}, dt.date(2026,11,8))[0]))
T.append(("ブレーキ: 発火後に活動が見えたら中止", not ex.brake_ok(dt.date(2026,11,1), {"gmail_read": "2026-11-05"}, dt.date(2026,11,8))[0]))
for name, ok in T: print(f"  {'OK ' if ok else 'NG '} {name}")
print(f"決定的: {sum(o for _,o in T)}/{len(T)}\n")

async def letters(n):
    cases = [("cancel", by["Netflix"], None, ["Netflix", "遺族の連絡先"]), ("share", by["GitHub"], "田中さん", ["GitHub", "田中", "パスワード"]), ("notice", {"name": "あとのこと"}, None, ["7", "返事は要りません"])]
    total = passed = 0
    for kind, a, to, must in cases:
        rs = await asyncio.gather(*[ex.letter(kind, a, "山田太郎", to) for _ in range(n)])
        ok = 0
        for t in rs:
            t = t.translate(str.maketrans("０１２３４５６７８９", "0123456789"))   # 全角の数字は同じ意味
            good = all(m in t for m in must) and not any(f in t for f in ex.FORBIDDEN_IN_LETTER) and 80 <= len(t) <= 900
            ok += good
            if not good: print("     落ち:", [m for m in must if m not in t], len(t), t[-90:].replace(chr(10), " "))
        total += n; passed += ok
        print(f"  {ok}/{n}  {kind}   例: {rs[0][:100].replace(chr(10),' ')}")
    print(f"\n文面: {passed}/{total}")
asyncio.run(letters(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
