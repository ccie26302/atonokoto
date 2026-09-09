#!/usr/bin/env python3
"""遺志の解釈エージェント（ADK）。
「写真は妻に」「サブスクは全部止めて」のような一言を、資産の地図に対する塗り分けに変換する。
曖昧なら決めずに聞き返す。パスワードは誰にも渡さない（設計で固定）。

  python agent.py "Netflix は解約して"            → JSON
  python agent.py --bench [N]                      → tests/will_cases.json を N 回ずつ回して採点
"""
import json, os, sys, asyncio
from typing import Optional
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "forward-vector-470012-n8")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
MODEL = os.environ.get("ATONOKOTO_MODEL", "gemini-3.5-flash")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data")

class Decision(BaseModel):
    asset: str = Field(description="地図にある資産名。地図に無いものは書かない")
    action: str = Field(description="give / erase / keep のいずれか")
    to: Optional[str] = Field(default=None, description="give のときの渡す相手")
    confidence: float = Field(description="0〜1")
    note: Optional[str] = Field(default=None, description="注意点（年払い・依存など）")

class Interpretation(BaseModel):
    decisions: list[Decision]
    ask: Optional[str] = Field(default=None, description="曖昧で決められないとき、本人に返す質問。決められたら null")
    refused: Optional[str] = Field(default=None, description="設計上できないこと（パスワードを渡す等）を求められたときの説明")

def assets_text():
    a = json.load(open(os.path.join(DATA, "assets.json")))
    a = a if isinstance(a, list) else a.get("assets", [])
    rows = []
    for x in a:
        n = x.get("name") or x.get("service")
        if not n: continue
        rows.append(f"- {n} | {x.get('category')} | 月額 {x.get('monthly_cost',0)} | 課金 {x.get('billing_via')} | ログイン {x.get('login_via')}"
                    + (f" | 依存 {','.join(x['depends_on'])}" if x.get("depends_on") else "")
                    + (" | 使っていない" if x.get("unused") else ""))
    return "\n".join(rows)

INSTRUCTION = """あなたは「あとのこと」の聞き役。本人の一言を、資産の地図への塗り分け（渡す give / 消す erase / 触るな keep）に変換する。

資産の地図:
{assets}

守ること:
- 地図にある資産にだけ決定を出す。地図に無いものは決めない
- 一言が複数の資産を指すなら（「サブスクは全部」「会社のものは全部」）、該当する資産を全部列挙する
  - 「サブスク」＝月額が 0 より大きい「契約」の資産。仕事用の有料（Google Cloud・Notion・GitHub・ドメイン）は含めず、ask で確認する
  - 「会社のもの」＝「仕事」の資産
  - 「銀行」「証券」「お金」＝「金融」の資産
- 曖昧なら決めずに ask で聞き返す。例: 「写真」がどのサービスの写真か地図から一意に決まらないとき
- ハブ（Google アカウント・Apple ID）を消す指示には、依存している資産を名指しして ask で確認する。ハブ自体の decision は出してよい
- 年払いや解約手数料の注意は note に書く
- パスワードや認証情報を誰かに渡す指示は、設計上できない。decisions は空にし、refused に「パスワードは渡さず、代わりに資産そのものを渡す（所有権移転・共有）か、止めるかを選ぶ」旨を書く
- 出力は JSON だけ"""

def build():
    return LlmAgent(name="will_interpreter", model=MODEL, instruction=INSTRUCTION.replace("{assets}", assets_text()),
                    output_schema=Interpretation, output_key="interpretation")

async def interpret(text: str) -> dict:
    svc = InMemorySessionService(); sid = f"s{abs(hash(text)) % 10**8}"
    await svc.create_session(app_name="atonokoto", user_id="taro", session_id=sid)
    runner = Runner(agent=build(), app_name="atonokoto", session_service=svc)
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    out = None
    async for ev in runner.run_async(user_id="taro", session_id=sid, new_message=msg):
        if ev.is_final_response() and ev.content and ev.content.parts and ev.content.parts[0].text:
            out = ev.content.parts[0].text
    try: return json.loads(out)
    except Exception: return {"decisions": [], "ask": None, "refused": None, "_raw": out}

# ---------------- ベンチ ----------------
def norm(s): return str(s or "").lower().replace(" ", "").replace("　", "")
def check(case, r):
    got = {(norm(d["asset"]), d["action"]) for d in r.get("decisions", [])}
    exp = {(norm(a), act) for a, act in case["expect"]}
    # 期待した (資産, 行為) が全て含まれ、期待に反する行為が無い
    ok_set = exp <= got and not any((a, act) in got for a, act in [(x, y) for x, y in
              [(e[0], o) for e in exp for o in ("give", "erase", "keep") if o != e[1]]])
    ok_ask = (bool(r.get("ask")) == case.get("ask", False)) if "ask" in case else True
    ok_ref = (bool(r.get("refused")) == case.get("refused", False)) if "refused" in case else True
    ok_to = True
    if case.get("to"):
        ok_to = all(norm(case["to"]) in norm(d.get("to")) for d in r.get("decisions", []) if d["action"] == "give")
    forbidden = case.get("forbid", [])
    ok_forbid = not any(norm(f) == a for f in forbidden for a, _ in got)
    return dict(set=ok_set, ask=ok_ask, refused=ok_ref, to=ok_to, forbid=ok_forbid,
                all=ok_set and ok_ask and ok_ref and ok_to and ok_forbid)

async def bench(n):
    cases = json.load(open(os.path.join(HERE, "..", "..", "tests", "will_cases.json")))
    sem = asyncio.Semaphore(6)
    async def one(c, k):
        async with sem: return c, k, await interpret(c["say"])
    results = await asyncio.gather(*[one(c, k) for c in cases for k in range(n)])
    per = {}
    log = []
    for c, k, r in results:
        ck = check(c, r); per.setdefault(c["say"], []).append(ck)
        log.append({"say": c["say"], "run": k, "result": r, "check": ck})
    json.dump(log, open(os.path.join(DATA, "will_bench.json"), "w"), ensure_ascii=False, indent=1)
    total = 0; passed = 0
    for say, cks in per.items():
        p = sum(x["all"] for x in cks); total += len(cks); passed += p
        fails = [k for k in ("set", "ask", "refused", "to", "forbid") if any(not x[k] for x in cks)]
        print(f"  {p}/{len(cks)}  {say}" + (f"   落ちた項目: {fails}" if fails else ""))
    print(f"\n合計 {passed}/{total}  ({passed/total:.2f})  N={n}/ケース, {len(per)} ケース")

def rescore():
    cases = {c["say"]: c for c in json.load(open(os.path.join(HERE, "..", "..", "tests", "will_cases.json")))}
    log = json.load(open(os.path.join(DATA, "will_bench.json"))); per = {}
    for r in log:
        ck = check(cases[r["say"]], r["result"]); r["check"] = ck; per.setdefault(r["say"], []).append(ck)
    json.dump(log, open(os.path.join(DATA, "will_bench.json"), "w"), ensure_ascii=False, indent=1)
    total = passed = 0
    for say, cks in per.items():
        p = sum(x["all"] for x in cks); total += len(cks); passed += p
        fails = [k for k in ("set", "ask", "refused", "to", "forbid") if any(not x[k] for x in cks)]
        print(f"  {p}/{len(cks)}  {say}" + (f"   落ちた項目: {fails}" if fails else ""))
    print(f"\n合計 {passed}/{total}  ({passed/total:.2f})")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--rescore":
        rescore()
    elif len(sys.argv) > 1 and sys.argv[1] == "--bench":
        asyncio.run(bench(int(sys.argv[2]) if len(sys.argv) > 2 else 5))
    else:
        print(json.dumps(asyncio.run(interpret(" ".join(sys.argv[1:]) or "Netflix は解約して")), ensure_ascii=False, indent=1))
