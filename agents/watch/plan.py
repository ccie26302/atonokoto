#!/usr/bin/env python3
"""見張りの計画。加入時に、その人の足跡から「何で見張れるか／見張れないか」を決めて本人に告げる。

  決める部分は決定的（コード）: 使える源、型（A/B/C）、床
  説明する部分だけ Gemini（ADK, output_schema）: 本人への言葉、足したサービスの合図の有無

  python plan.py                → 3 つの人物像（A/B/C）で計画を作る
  python plan.py --bench [N]    → N 回ずつ回して、説明が嘘をついていないかを採点
"""
from __future__ import annotations
import json, os, sys, asyncio
from typing import Optional
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state import applicable_sources, FLOOR_QUIET, FLOOR_WAITING, FLOOR_GRACE, BASELINE_MIN_EVENTS

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "forward-vector-470012-n8")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
MODEL = os.environ.get("ATONOKOTO_MODEL", "gemini-3.5-flash")
HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = {c["name"]: c for c in json.load(open(os.path.join(HERE, "..", "..", "data", "catalog.json")))["services"]}
GOOGLE_SOURCES = {"gmail_read": "メールの既読", "gmail_sent": "メールの送信", "drive": "Drive の編集", "calendar": "予定の変更", "purchase": "買い物・予約の通知", "youtube": "YouTube の高評価・登録"}
GOOGLE_NOTICE_MIN_DAYS = 90   # アカウント無効化管理ツールの最短

# ---------------- 決定的な部分 ----------------
def classify(footprint: dict[str, int], added: list[str]) -> dict:
    """footprint: 加入前 90 日の源ごとの活動回数。added: 手で足したサービス名。"""
    usable_google = sorted(applicable_sources({k: v for k, v in footprint.items() if k in GOOGLE_SOURCES}))
    extra = []
    for name in added:
        c = CATALOG.get(name)
        if not c: continue
        sig = c["signal"]
        extra.append({"name": name, "auth": sig["auth"], "how": sig["how"],
                      "usable": sig["auth"] in ("none", "oauth") and footprint.get(name, 0) >= BASELINE_MIN_EVENTS})
    usable_extra = [e["name"] for e in extra if e["usable"]]
    if any(s in usable_google for s in ("drive", "calendar", "purchase", "youtube")): kind = "A"
    elif usable_google: kind = "B"
    else: kind = "C"
    watchable = bool(usable_google or usable_extra)
    return {
        "kind": kind, "watchable": watchable,
        "usable_sources": usable_google + usable_extra,
        "unused_google": [k for k in GOOGLE_SOURCES if k not in usable_google],
        "added": extra,
        "floors": {"quiet": FLOOR_QUIET, "waiting": FLOOR_WAITING, "grace": FLOOR_GRACE} if watchable else None,
        "outermost": {"google_notice_min_days": GOOGLE_NOTICE_MIN_DAYS, "required": True},
    }

# ---------------- 説明する部分 ----------------
class Plan(BaseModel):
    to_person: str = Field(description="本人に告げる言葉。3〜5 文。何で見張れるか、見張れないなら見張れないと言う")
    watchable: bool = Field(description="こちらから沈黙を見張れるか（決定的な判定をそのまま写す）")
    ask_google_notice: bool = Field(description="Google の無効化管理ツールの設定を頼むか。常に true")
    added_services: list[str] = Field(description="足したサービスのうち、見張りの源にできるもの")
    ask_consent_for: list[str] = Field(description="源にするために本人の同意が要るもの")

INSTRUCTION = """あなたは「あとのこと」の見張り係。加入した本人に、見張りの計画を正直に説明する。
決定的な判定（JSON）が与えられる。あなたはそれを覆さない。判定に無い約束をしない。

守ること:
- watchable が false なら「沈黙は見張れません」とはっきり言う。曖昧にしない
- Google の無効化管理ツールを 3 か月に設定し、信頼できる連絡先に atonokoto を入れるよう、必ず頼む（これが最外殻）
- 足したサービスのうち usable が true のものは、源にできると伝える。auth が oauth なら同意が要ると言う。auth が no のものは「地図には載るが合図にはならない」と言う
- 見張れる場合、床（沈黙 30 日で気にかけ、60 日で確認者に連絡、14 日の猶予）を短く伝える
- 受信箱の本文は読まない、と一言入れる（既読と送信の日時だけ見る）
- 出力は JSON だけ"""

async def explain(judgement: dict) -> dict:
    agent = LlmAgent(name="watch_planner", model=MODEL, instruction=INSTRUCTION, output_schema=Plan, output_key="plan")
    svc = InMemorySessionService(); sid = "p" + str(abs(hash(json.dumps(judgement, sort_keys=True))) % 10**8)
    await svc.create_session(app_name="atonokoto", user_id="taro", session_id=sid)
    runner = Runner(agent=agent, app_name="atonokoto", session_service=svc)
    msg = types.Content(role="user", parts=[types.Part(text="判定:\n" + json.dumps(judgement, ensure_ascii=False, indent=1))])
    out = None
    async for ev in runner.run_async(user_id="taro", session_id=sid, new_message=msg):
        if ev.is_final_response() and ev.content and ev.content.parts and ev.content.parts[0].text: out = ev.content.parts[0].text
    try: return json.loads(out)
    except Exception: return {"_raw": out}

PERSONAS = {
    "A 型（山田太郎: Drive も Calendar も使う）": ({"gmail_read": 80, "gmail_sent": 20, "drive": 40, "calendar": 15, "GitHub": 30}, ["GitHub", "Netflix"]),
    "B 型（メールは読むが他は使わない）": ({"gmail_read": 50, "gmail_sent": 2, "drive": 0, "calendar": 1}, ["Spotify", "銀行（三菱UFJ 等）"]),
    "C 型（ID としてしか使わない）": ({"gmail_read": 1, "gmail_sent": 0, "drive": 0, "calendar": 0, "Spotify": 60}, ["Spotify", "Netflix"]),
}

def check(judgement: dict, plan: dict) -> dict:
    t = plan.get("to_person", "")
    ok_watch = plan.get("watchable") == judgement["watchable"]
    ok_c = judgement["watchable"] or ("見張れません" in t or "見張れない" in t)
    ok_notice = plan.get("ask_google_notice") is True and ("無効化" in t)
    usable_added = {e["name"] for e in judgement["added"] if e["usable"]}
    ok_added = set(plan.get("added_services", [])) == usable_added
    no_promise = all(name not in plan.get("added_services", []) for name in [e["name"] for e in judgement["added"] if not e["usable"]])
    ok_body = "本文" in t
    return dict(watch=ok_watch, honest_c=ok_c, notice=ok_notice, added=ok_added, no_promise=no_promise, body=ok_body,
                all=ok_watch and ok_c and ok_notice and ok_added and no_promise and ok_body)

async def bench(n):
    total = passed = 0; log = []
    for label, (fp, added) in PERSONAS.items():
        j = classify(fp, added)
        plans = await asyncio.gather(*[explain(j) for _ in range(n)])
        cks = [check(j, p) for p in plans]; p_ = sum(c["all"] for c in cks); total += n; passed += p_
        fails = sorted({k for c in cks for k, v in c.items() if k != "all" and not v})
        print(f"  {p_}/{n}  {label}" + (f"   落ちた項目: {fails}" if fails else ""))
        log.append({"persona": label, "judgement": j, "plans": plans, "checks": cks})
    json.dump(log, open(os.path.join(HERE, "..", "..", "data", "plan_bench.json"), "w"), ensure_ascii=False, indent=1)
    print(f"\n合計 {passed}/{total}  N={n}/人物像")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--bench":
        asyncio.run(bench(int(sys.argv[2]) if len(sys.argv) > 2 else 3))
    else:
        for label, (fp, added) in PERSONAS.items():
            j = classify(fp, added)
            print(f"== {label}\n  判定: 型 {j['kind']} / 見張れる {j['watchable']} / 源 {j['usable_sources']}")
            p = asyncio.run(explain(j)); print("  本人へ:", p.get("to_person")); print("  足した源:", p.get("added_services"), "同意が要る:", p.get("ask_consent_for"))
