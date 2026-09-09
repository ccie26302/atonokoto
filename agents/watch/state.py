#!/usr/bin/env python3
"""見張りの状態機械（床つき）。常に裏で動くのではなく、期限が来たときに評価される。

  ALIVE ──沈黙 30日──▶ QUIET ──沈黙 60日──▶ WAITING（確認者に通知）──14日 or 確認──▶ FIRED
                                                            ▲
  UNWATCHABLE（使える源が無い人）──Google の無効化通知（検証済み）──┘
  どの段階でも本人の活動が観測されたら ALIVE に戻る。

床の原則:
  - 30 / 60 / 14 日はモデルが縮められない下限。モデルにできるのは「延ばす」だけ
  - 「読めない」と「静か」を区別する。シグナル源が読めない期間は沈黙に数えない
  - 複数のシグナル源の AND（全部が沈黙して初めて沈黙）
  - 発火は状態機械ではなく、確認者 2 人以上の合意で起きる。状態機械は WAITING までしか進めない
"""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field

FLOOR_QUIET, FLOOR_WAITING, FLOOR_GRACE = 30, 60, 14

@dataclass
class Signal:
    source: str
    last_activity: dt.date | None   # 最後に本人の活動が見えた日
    readable: bool                  # この源が今読めるか（トークン失効などで読めない＝沈黙ではない）
    applicable: bool = True         # この人の見張りに使える源か（基準期間に活動が無かった源は使わない）
    weak: bool = False              # 弱い源（買い物の通知）。第三者でも作れる合図なので、単独では WAITING を止められない

@dataclass
class State:
    name: str = "ALIVE"
    since: dt.date | None = None    # この状態に入った日
    waiting_since: dt.date | None = None
    extension_days: int = 0         # モデルが延ばした日数（縮めることはできない）
    history: list = field(default_factory=list)

BASELINE_DAYS, BASELINE_MIN_EVENTS = 90, 3

def applicable_sources(baseline: dict[str, int]) -> set[str]:
    """基準期間（加入前 90 日）に活動が BASELINE_MIN_EVENTS 回以上あった源だけを、その人の見張りに使う。
    Drive を使わない人の Drive の沈黙で発火したら事故になる。"""
    return {src for src, n in baseline.items() if n >= BASELINE_MIN_EVENTS}

def silence_days(signals: list[Signal], today: dt.date) -> int | None:
    """使える源のうち読める源で、全てが沈黙している日数（AND なので最小値）。
    読める源が無ければ None（＝判断しない）。使える源がそもそも無い人は UNWATCHABLE で、ここには来ない。"""
    usable = [s for s in signals if s.applicable]
    readable = [s for s in usable if s.readable]
    strong = [s for s in readable if not s.weak]
    if not strong: return None                               # 弱い源だけでは判断しない（買い物の通知だけの人は見張れない）
    def d(s): return 10**6 if s.last_activity is None else (today - s.last_activity).days   # 使える源なのに一度も無い → 無限
    sd = min(d(s) for s in strong)
    # 弱い源は、強い源の沈黙が WAITING の床に届くまでしか効かない。届いたら確認者に問う（第三者の注文通知で無期限に延ばせないように）
    weak = [d(s) for s in readable if s.weak]
    if weak and sd < FLOOR_WAITING: sd = min(sd, min(weak))
    return sd

def step(state: State, signals: list[Signal], today: dt.date, model_delay: int = 0) -> State:
    """1回の評価。model_delay はモデルの「もう少し待つ」提案（日数、0 以上のみ有効）。"""
    if model_delay < 0: model_delay = 0                      # 縮めるのは無効
    ev = {"date": today.isoformat(), "from": state.name}
    if state.name == "DONE":
        ev["to"] = "DONE"; ev["note"] = "執行済み。何もしない"; state.history.append(ev); return state
    if not any(s.applicable for s in signals):
        # 見張れない人。沈黙を数えず、Google の無効化通知（最外殻）だけを待つ。本人にはそう告げてある
        if state.name != "UNWATCHABLE": state.name, state.since = "UNWATCHABLE", today
        ev["to"] = state.name; ev["note"] = "使える源が無い。Google の無効化通知だけを待つ"; state.history.append(ev); return state
    if state.name == "UNWATCHABLE":                          # 源が増えた（サービスを足した等）ら見張りに戻る
        state.name, state.since = "ALIVE", today
    sd = silence_days(signals, today); ev["silence"] = sd
    if sd is None:
        ev["note"] = "読める源が無い。判断しない"; state.history.append(ev); return state
    if sd < FLOOR_QUIET:                                    # 生きている
        if state.name != "ALIVE":
            state.name, state.since, state.waiting_since, state.extension_days = "ALIVE", today, None, 0
        ev["to"] = state.name; state.history.append(ev); return state
    if state.name == "ALIVE":
        state.name, state.since = "QUIET", today; state.extension_days = model_delay
    elif state.name == "QUIET" and sd >= FLOOR_WAITING + state.extension_days:
        state.name, state.since, state.waiting_since = "WAITING", today, today; state.extension_days = model_delay
    elif state.name == "QUIET":
        state.extension_days = max(state.extension_days, model_delay)
    elif state.name == "WAITING":
        # 猶予は確認者のためのもの。モデルは延ばせるが、状態機械はここで止まり、発火は確認者の合意で行う
        state.extension_days = max(state.extension_days, model_delay)
    ev["to"] = state.name; ev["extension"] = state.extension_days; state.history.append(ev); return state

def grace_over(state: State, today: dt.date) -> bool:
    """WAITING に入ってから猶予（14日＋延長）が過ぎたか。発火の下限。過ぎても 2 人の合意が無ければ発火しない。"""
    return state.name == "WAITING" and state.waiting_since is not None and (today - state.waiting_since).days >= FLOOR_GRACE + state.extension_days

def google_notice(state: State, today: dt.date, verified: bool) -> State:
    """Google の無効化通知（最外殻）。DKIM 検証済みなら、どの状態からでも WAITING に進める（UNWATCHABLE の人の唯一の合図）。
    発火はしない。確認者の合意が要るのは同じ。"""
    if not verified:
        state.history.append({"date": today.isoformat(), "from": state.name, "to": state.name, "note": "無効化通知の検証に失敗。無視"}); return state
    if state.name in ("ALIVE", "QUIET", "UNWATCHABLE"):
        state.history.append({"date": today.isoformat(), "from": state.name, "to": "WAITING", "note": "Google の無効化通知"})
        state.name, state.since, state.waiting_since = "WAITING", today, today
    return state

def done(state: State, today: dt.date, summary: str) -> State:
    """執行が終わった。以後は毎日走っても何もしない（再執行しない）。"""
    if state.name == "FIRED":
        state.history.append({"date": today.isoformat(), "from": "FIRED", "to": "DONE", "note": summary}); state.name, state.since = "DONE", today
    return state

def fire(state: State, confirmers: int, today: dt.date) -> State:
    """確認者の合意。2人未満、WAITING でない、または猶予（14 日＋延長）が過ぎていなければ何も起きない。
    猶予は発火の下限。60 日の沈黙の直後に 2 人が押しても、最短 14 日は本人に戻る余地を残す。"""
    if state.name == "WAITING" and confirmers >= 2 and grace_over(state, today):
        state.name, state.since = "FIRED", today
        state.history.append({"date": today.isoformat(), "from": "WAITING", "to": "FIRED", "confirmers": confirmers})
    else:
        state.history.append({"date": today.isoformat(), "from": state.name, "to": state.name, "confirmers": confirmers, "note": "発火せず"})
    return state

# ---------------- テスト ----------------
if __name__ == "__main__":
    D = lambda d: dt.date(2026, 1, 1) + dt.timedelta(days=d)
    def run(days, act, readable=lambda d: True, delay=lambda d: 0, sources=1):
        st = State(); 
        for d in range(days):
            sig = [Signal(f"s{i}", act(d, i), readable(d)) for i in range(sources)]
            st = step(st, sig, D(d), delay(d))
        return st
    T = []
    # 1) 毎日活動 → ずっと ALIVE
    st = run(120, lambda d, i: D(d)); T.append(("毎日活動は ALIVE", st.name == "ALIVE"))
    # 2) 0日目を最後に沈黙 → 30日で QUIET、60日で WAITING、その後も FIRED にはならない
    st = run(29, lambda d, i: D(0)); T.append(("29日では ALIVE", st.name == "ALIVE"))
    st = run(31, lambda d, i: D(0)); T.append(("30日で QUIET", st.name == "QUIET"))
    st = run(61, lambda d, i: D(0)); T.append(("60日で WAITING", st.name == "WAITING"))
    st = run(200, lambda d, i: D(0)); T.append(("200日でも状態機械は FIRED にしない", st.name == "WAITING"))
    # 3) モデルは延ばせるが縮められない
    st = run(61, lambda d, i: D(0), delay=lambda d: 30); T.append(("延長30日: 60日ではまだ QUIET", st.name == "QUIET"))
    st = run(91, lambda d, i: D(0), delay=lambda d: 30); T.append(("延長30日: 90日で WAITING", st.name == "WAITING"))
    st = run(31, lambda d, i: D(0), delay=lambda d: -25); T.append(("負の提案は無視（縮まない）", st.name == "QUIET" and st.extension_days == 0))
    st = run(45, lambda d, i: D(0), delay=lambda d: -25); T.append(("負の提案で早く WAITING にならない", st.name == "QUIET"))
    # 4) 読めない期間は沈黙に数えない
    st = run(100, lambda d, i: D(0), readable=lambda d: False); T.append(("全部読めない → 判断しない（ALIVE のまま）", st.name == "ALIVE"))
    # 5) 複数源の AND: 片方だけ活動していれば生きている
    st = run(100, lambda d, i: D(d) if i == 0 else D(0), sources=2); T.append(("2源のうち1つで活動 → ALIVE", st.name == "ALIVE"))
    st = run(100, lambda d, i: D(0), sources=2); T.append(("2源とも沈黙 → WAITING", st.name == "WAITING"))
    # 6) 復活: 沈黙 40 日で QUIET → 活動 → ALIVE に戻り延長もリセット
    st = run(41, lambda d, i: D(0), delay=lambda d: 20); st = step(st, [Signal("s0", D(41), True)], D(41))
    T.append(("活動で ALIVE に戻る", st.name == "ALIVE" and st.extension_days == 0))
    # 7) 猶予と発火
    st = run(61, lambda d, i: D(0)); T.append(("WAITING 直後は猶予内", not grace_over(st, D(61))))
    T.append(("14日で猶予切れ", grace_over(st, D(75))))
    fire(st, 2, D(61)); T.append(("猶予の内は 2 人でも発火しない（猶予は発火の下限）", st.name == "WAITING"))
    fire(st, 1, D(75)); T.append(("確認者1人では発火しない", st.name == "WAITING"))
    fire(st, 2, D(75)); T.append(("確認者2人で FIRED", st.name == "FIRED"))
    st2 = run(31, lambda d, i: D(0)); fire(st2, 3, D(31)); T.append(("QUIET では3人でも発火しない", st2.name == "QUIET"))
    # 8) 使える源の選別（C 型: Google をほぼ使わない人）
    T.append(("基準期間に活動が無い源は使わない", applicable_sources({"drive": 0, "calendar": 1, "gmail_read": 12}) == {"gmail_read"}))
    def run_c(days):
        st = State()
        for d in range(days): st = step(st, [Signal("drive", None, True, applicable=False), Signal("calendar", None, True, applicable=False)], D(d))
        return st
    st = run_c(200); T.append(("使える源が無い人は UNWATCHABLE（発火に向かわない）", st.name == "UNWATCHABLE"))
    st = run_c(10); st = step(st, [Signal("drive", None, True, applicable=False), Signal("github", D(10), True)], D(10))
    T.append(("サービスを足して源ができたら ALIVE に戻る", st.name == "ALIVE"))
    st = run_c(10); st = google_notice(st, D(10), verified=False); T.append(("検証できない無効化通知は無視", st.name == "UNWATCHABLE"))
    st = google_notice(st, D(10), verified=True); T.append(("検証済みの無効化通知で WAITING", st.name == "WAITING"))
    fire(st, 2, D(12)); T.append(("無効化通知の後も猶予の内は発火しない", st.name == "WAITING"))
    # 9) 買い物の通知（利用者側の合図）: メールを読まなくなっても買い物が続く人は ALIVE のまま
    stp = State()
    for d in range(45): stp = step(stp, [Signal("gmail_read", D(0), True), Signal("purchase", D(d), True, weak=True)], D(d))
    T.append(("既読が止まっても買い物が続けば ALIVE", stp.name == "ALIVE"))
    T.append(("沈黙は使える源の最小値（買い物が今日なら 0 日）", silence_days([Signal("gmail_read", D(0), True), Signal("purchase", D(45), True, weak=True)], D(45)) == 0))
    T.append(("買い物を使わない人（基準 0）の買い物の沈黙は数えない", silence_days([Signal("gmail_read", D(40), True), Signal("purchase", None, True, applicable=False)], D(45)) == 5))
    # 10) 弱い源: 強い源が 60 日沈黙したら、買い物の通知が毎月来ていても WAITING に進む（第三者の注文通知で無期限に延ばせない）
    stw = State()
    for d in range(70): stw = step(stw, [Signal("gmail_read", D(0), True), Signal("purchase", D(d - d % 20), True, weak=True)], D(d))
    T.append(("弱い源だけでは WAITING を止められない", stw.name == "WAITING"))
    T.append(("弱い源は QUIET までは延ばせる", silence_days([Signal("gmail_read", D(0), True), Signal("purchase", D(40), True, weak=True)], D(45)) == 5))
    T.append(("弱い源だけの人は判断しない", silence_days([Signal("purchase", D(45), True, weak=True)], D(45)) is None))
    fire(st, 2, D(25)); T.append(("その後は確認者 2 人で FIRED", st.name == "FIRED"))
    st = run(5, lambda d, i: D(d)); st = google_notice(st, D(5), verified=True); T.append(("生きている人にも通知が来れば WAITING（確認者が判断する）", st.name == "WAITING"))
    st = run(200, lambda d, i: D(0), delay=lambda d: 30); T.append(("延長は累積しない（毎日 30 日を提案しても 90 日で WAITING）", st.name == "WAITING" and st.extension_days <= 30))
    st = State(name="FIRED", since=D(80)); st = done(st, D(87), "執行 3 件"); T.append(("執行が終わったら DONE", st.name == "DONE"))
    st = step(st, [Signal("s0", D(90), True)], D(90)); T.append(("DONE は活動があっても動かない（再執行しない）", st.name == "DONE"))
    st = fire(st, 5, D(91)); T.append(("DONE は再発火しない", st.name == "DONE"))
    bad = 0
    for name, ok in T:
        bad += not ok; print(f"  {'OK ' if ok else 'NG '} {name}")
    print(f"\n{len(T)-bad}/{len(T)} 期待どおり")
    raise SystemExit(bad)
