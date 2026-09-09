#!/usr/bin/env python3
"""見張りのシグナルを本物の Google アカウントから取る。読み取りのみ。本文は取らない。

  python signals_google.py [days]   → 直近 days 日（既定 90）の足跡を源ごとに数え、最終活動日を出す
                                      結果は data/footprint_real.json（メール本文・件名は含めない）

源:
  gmail_sent   送信済み（in:sent）の internalDate            ← 本人が能動的に何かをした最強の痕跡
  gmail_read   受信メールのうち UNREAD で無いものの internalDate  ← 「既読にした」の近似。受信日しか分からないので
                                                                日付は受信日で代用し、既読率の変化で見る
  drive        Drive Activity の本人 actor のタイムスタンプ
  calendar     Calendar の updated（本人が更新した予定）
  youtube      YouTube の高評価（LL プレイリストに入った日時）とチャンネル登録の日時 ← 観ている人しか押さない。視聴履歴そのものは API に無い
  purchase     受信箱の注文確認・予約・決済の通知（差出人ドメイン＋件名の型で判定。purchases.py）
               ← 利用者側の合図。Amazon・楽天・メルカリ・PayPay など、API を持たないサービスをここで拾う。
                 定期便やサブスクの自動更新は数えない。記録に残すのは店の名前と日付だけで、件名は保存しない
"""
import json, os, sys, time, datetime as dt, collections
from googleapiclient.discovery import build
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from google_auth import load
import purchases

HERE = os.path.dirname(os.path.abspath(__file__))
UID = os.environ.get("ATONOKOTO_UID") or None
OUT = os.path.join(os.environ.get("ATONOKOTO_USER_DIR") or os.path.join(HERE, "..", "..", "data"), "footprint_real.json")
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 90
TODAY = dt.datetime.now(dt.timezone.utc)
SINCE = TODAY - dt.timedelta(days=DAYS)

def gmail_dates(svc, label, cap=400, headers=False):
    """メタデータだけ。本文は取らない。headers=False なら format=minimal（id/labelIds/internalDate）。
    headers=True は差出人と件名のヘッダだけを足す（買い物の判定に使い、判定が終わればメモリからも捨てる。保存しない）。
    metadata スコープは q（検索）を使えないので、ラベルで一覧し新しい順に読んで、期間より古くなったら止める。
    100 通 = 500 units。1 分 15,000 units の上限に収まるよう、束ねた要求の間に少し待つ。"""
    since_ms = int(SINCE.timestamp() * 1000)
    out = []; token = None
    while len(out) < cap:
        r = svc.users().messages().list(userId="me", labelIds=[label], maxResults=100, pageToken=token).execute()
        page = r.get("messages", []); token = r.get("nextPageToken")
        if not page: break
        got = []
        def _cb(_id, resp, exc):
            if exc is None and resp: got.append(resp)
        b = svc.new_batch_http_request(callback=_cb)   # 100 通を 1 回の HTTP に束ねる
        for x in page:
            b.add(svc.users().messages().get(userId="me", id=x["id"], format="metadata", metadataHeaders=["From", "Subject"]) if headers
                  else svc.users().messages().get(userId="me", id=x["id"], format="minimal"))
        b.execute(); time.sleep(2.5)
        stop = False
        for m in sorted(got, key=lambda m: -int(m["internalDate"])):
            ts = int(m["internalDate"])
            if ts < since_ms: stop = True; break
            h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])} if headers else {}
            out.append((ts // 1000, "UNREAD" in m.get("labelIds", []), h.get("from", ""), h.get("subject", "")))
            if len(out) >= cap: break
        if stop or not token: break
    return out

def main():
    c = load("watch", UID)
    if not c: sys.exit("見張りの同意が無い。python google_auth.py watch")
    fp = {}; last = {}; daily = collections.defaultdict(lambda: collections.Counter())
    gm = build("gmail", "v1", credentials=c)
    sent = gmail_dates(gm, "SENT")
    fp["gmail_sent"] = len(sent); last["gmail_sent"] = max((t for t, *_ in sent), default=None)
    for t, *_ in sent: daily["gmail_sent"][dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()] += 1
    inbox = gmail_dates(gm, "INBOX", cap=600, headers=True)
    read = [(t, u) for t, u, _, _ in inbox if not u]
    fp["gmail_read"] = len(read); fp["gmail_inbox_total"] = len(inbox)
    last["gmail_read"] = max((t for t, _ in read), default=None)
    for t, _ in read: daily["gmail_read"][dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()] += 1
    # 買い物・予約・決済の通知（既読かどうかは問わない。注文した事実が合図）
    vendors = {}
    bought = []
    for t, _, frm, subj in inbox:
        hit = purchases.classify(frm, subj)   # 変数名は c にしない（c は資格情報。上書きすると以後の API が無認証になる。2026-09-09 に踏んだ）
        if not hit: continue
        day = dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()
        bought.append(t); daily["purchase"][day] += 1
        v = vendors.setdefault(hit["vendor"], {"kind": hit["kind"], "n": 0, "last": None})
        v["n"] += 1; v["last"] = max(v["last"] or day, day)
    del inbox   # 差出人・件名はここで捨てる
    fp["purchase"] = len(bought); last["purchase"] = max(bought, default=None)

    da = build("driveactivity", "v2", credentials=c)
    me_ts = []; token = None
    while True:
        r = da.activity().query(body={"filter": f"time >= \"{SINCE.isoformat()}\"", "pageSize": 100, "pageToken": token}).execute()
        for a in r.get("activities", []):
            if any(ac.get("user", {}).get("knownUser", {}).get("isCurrentUser") for ac in a.get("actors", [])):
                ts = a.get("timestamp") or a.get("timeRange", {}).get("endTime")
                if ts: me_ts.append(ts)
        token = r.get("nextPageToken")
        if not token or len(me_ts) > 1000: break
    fp["drive"] = len(me_ts); last["drive"] = max(me_ts, default=None)
    for ts in me_ts: daily["drive"][ts[:10]] += 1

    cal = build("calendar", "v3", credentials=c)
    try:
        ev = cal.events().list(calendarId="primary", updatedMin=SINCE.isoformat(), showDeleted=True, maxResults=500, singleEvents=True).execute()
    except Exception:
        # updatedMin は遠い過去を受け付けない（410）。期間内の予定を取り、更新日時で絞る
        ev = cal.events().list(calendarId="primary", timeMin=SINCE.isoformat(), timeMax=(TODAY + dt.timedelta(days=90)).isoformat(),
                               maxResults=500, singleEvents=True).execute()
    upd = [e["updated"] for e in ev.get("items", []) if e.get("updated") and e["updated"] >= SINCE.isoformat()[:19]]
    # 沈黙の説明にだけ使う手がかり: 前後 30 日の予定の題名と日付（本文・参加者は取らない）
    try:
        near = cal.events().list(calendarId="primary", timeMin=(TODAY - dt.timedelta(days=30)).isoformat(), timeMax=(TODAY + dt.timedelta(days=30)).isoformat(),
                                 maxResults=50, singleEvents=True, orderBy="startTime").execute()
        titles = [{"date": (e.get("start", {}).get("date") or e.get("start", {}).get("dateTime", ""))[:10], "title": (e.get("summary") or "")[:40]} for e in near.get("items", [])]
    except Exception:
        titles = []
    fp["calendar"] = len(upd); last["calendar"] = max(upd, default=None)
    for ts in upd: daily["calendar"][ts[:10]] += 1

    # YouTube: 高評価（LL）とチャンネル登録の日時だけ。動画の題名は取らない。同意にスコープが無ければ 403 → その源は無い扱い
    yt_note = ""
    try:
        yt = build("youtube", "v3", credentials=c)
        yts = []
        r = yt.playlistItems().list(playlistId="LL", part="snippet", maxResults=50, fields="items/snippet/publishedAt").execute()
        yts += [i["snippet"]["publishedAt"] for i in r.get("items", []) if i.get("snippet", {}).get("publishedAt")]
        r = yt.subscriptions().list(mine=True, part="snippet", maxResults=50, fields="items/snippet/publishedAt").execute()
        yts += [i["snippet"]["publishedAt"] for i in r.get("items", []) if i.get("snippet", {}).get("publishedAt")]
        yts = [t for t in yts if t >= SINCE.isoformat()[:19]]
        fp["youtube"] = len(yts); last["youtube"] = max(yts, default=None)
        for ts in yts: daily["youtube"][ts[:10]] += 1
    except Exception as e:
        msg = str(e)
        yt_note = "同意に YouTube が含まれていない（同意を取り直すと使える）" if "403" in msg or "insufficient" in msg.lower() else f"取れない: {msg[:80]}"
        fp["youtube"] = 0; last["youtube"] = None

    def fmt(v): return dt.datetime.fromtimestamp(v, dt.timezone.utc).date().isoformat() if isinstance(v, int) else (v[:10] if v else None)
    result = {"days": DAYS, "as_of": TODAY.date().isoformat(), "footprint": fp, "calendar_titles": titles, "purchases": vendors, "youtube_note": yt_note,
              "last_activity": {k: fmt(v) for k, v in last.items()},
              "daily": {k: dict(sorted(v.items())) for k, v in daily.items()}}
    json.dump(result, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"直近 {DAYS} 日の足跡（本文・件名は取っていない）")
    for k in ("gmail_sent", "gmail_read", "drive", "calendar", "purchase", "youtube"):
        print(f"  {k:11s} {fp.get(k,0):4d} 回  最終 {result['last_activity'].get(k)}")
    print(f"  受信 {fp['gmail_inbox_total']} 通のうち既読 {fp['gmail_read']}")
    if yt_note: print("  youtube: " + yt_note)
    if vendors: print("  買い物・予約: " + "、".join(f"{k} {v['n']} 件（最終 {v['last']}）" for k, v in sorted(vendors.items(), key=lambda kv: -kv[1]['n'])))
    print(f"→ {OUT}")

if __name__ == "__main__":
    main()
