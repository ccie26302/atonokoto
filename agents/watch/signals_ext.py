#!/usr/bin/env python3
"""足したサービスを生存の合図に使う。読み取りのみ。
今すぐ使えるのは認証不要で公開情報から取れるもの。本人の同意（OAuth）が要るものはサービスごとにアプリ登録が要るので、
できたものから増やす。取れないものは正直に「準備中」と返す。

  fetch(name, ident) -> {"ok": bool, "last_activity": "YYYY-MM-DD" | None, "events_90d": int, "note": str}
"""
from __future__ import annotations
import json, urllib.request, datetime as dt

UA = {"User-Agent": "atonokoto-watch/0.1 (read-only liveness signal)"}
TODAY = dt.datetime.now(dt.timezone.utc)

def _get(url, headers=None):
    assert url.startswith("https://"), url
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    return json.load(urllib.request.urlopen(req, timeout=20))

def github(user: str) -> dict:
    """公開イベント（push・issue・star 等）。非公開リポジトリの活動は含まない。認証不要。"""
    try:
        ev = _get(f"https://api.github.com/users/{urllib.request.quote(user, safe='')}/events/public?per_page=100")
    except Exception as e:
        return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}
    ts = sorted((e["created_at"] for e in ev if e.get("created_at")), reverse=True)
    since = (TODAY - dt.timedelta(days=90)).isoformat()
    n90 = sum(1 for t in ts if t >= since)
    return {"ok": True, "last_activity": ts[0][:10] if ts else None, "events_90d": n90,
            "note": "公開イベントのみ。非公開の活動は見えない" + ("" if ts else "。90 日以内の公開活動なし")}

def _recent(dates, note):
    ds = sorted((x for x in dates if x), reverse=True)
    since = (TODAY - dt.timedelta(days=90)).strftime("%Y-%m-%d")
    return {"ok": True, "last_activity": ds[0][:10] if ds else None, "events_90d": sum(1 for x in ds if x[:10] >= since), "note": note + ("" if ds else "。活動なし")}

def zenn(user: str) -> dict:
    """Zenn の公開フィード（記事・本の公開日）。認証不要。"""
    import re as _re, email.utils as eu
    try:
        raw = urllib.request.urlopen(urllib.request.Request(f"https://zenn.dev/{urllib.request.quote(user, safe='')}/feed", headers=UA), timeout=20).read().decode("utf-8", "ignore")
    except Exception as e:
        return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}
    dates = []
    for m in _re.findall(r"<pubDate>([^<]+)</pubDate>", raw):
        try: dates.append(eu.parsedate_to_datetime(m).astimezone(dt.timezone.utc).strftime("%Y-%m-%d"))
        except Exception: pass
    return _recent(dates, "公開した記事の日付のみ。下書きは見えない")

def qiita(user: str) -> dict:
    """Qiita の公開記事（作成・更新日）。認証不要（レート制限あり）。"""
    try:
        items = _get(f"https://qiita.com/api/v2/users/{urllib.request.quote(user, safe='')}/items?per_page=100")
    except Exception as e:
        return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}
    return _recent([i.get("updated_at", "") for i in items], "公開記事の作成・更新日のみ")

def bluesky(handle: str) -> dict:
    """Bluesky の公開投稿。認証不要の公開 API。"""
    try:
        feed = _get(f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor={urllib.request.quote(handle, safe='')}&limit=100")
    except Exception as e:
        return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}
    return _recent([f.get("post", {}).get("record", {}).get("createdAt", "") for f in feed.get("feed", [])], "公開投稿のみ")

def steam(steamid64: str) -> dict:
    return {"ok": False, "last_activity": None, "events_90d": 0, "note": "準備中: Steam Web API キーが要る"}

def _rss_dates(url, tag="pubDate"):
    import re as _re, email.utils as eu
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", "ignore")
    dates = []
    for m in _re.findall(rf"<{tag}>([^<]+)</{tag}>", raw):
        try: dates.append(eu.parsedate_to_datetime(m).astimezone(dt.timezone.utc).strftime("%Y-%m-%d") if "," in m or m[:1].isalpha() else m[:10])
        except Exception: pass
    return dates

def note(user: str) -> dict:
    """note の公開 RSS（記事の公開日）。認証不要。"""
    try: return _recent(_rss_dates(f"https://note.com/{urllib.request.quote(user, safe='')}/rss"), "公開した記事の日付のみ。下書きは見えない")
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

def mastodon(acct: str) -> dict:
    """Mastodon の公開プロフィール（last_status_at = 最後に投稿した日）。user@instance の形。認証不要。"""
    try:
        import re as _re
        user, inst = (acct.lstrip("@").split("@", 1) + ["mastodon.social"])[:2]
        if not _re.fullmatch(r"[a-z0-9.-]{1,80}", inst.lower()) or not _re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", user):
            return {"ok": False, "last_activity": None, "events_90d": 0, "note": "user@instance の形で入れてください"}
        j = _get(f"https://{inst}/api/v1/accounts/lookup?acct={urllib.request.quote(user, safe='')}")
        la = (j.get("last_status_at") or "")[:10]
        n = int(j.get("statuses_count") or 0)
        since = (TODAY - dt.timedelta(days=90)).strftime("%Y-%m-%d")
        return {"ok": True, "last_activity": la or None, "events_90d": 3 if la and la >= since and n else 0, "note": "最後に投稿した日のみ（回数は取れないので、90 日以内なら合図として数える）"}
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

def wikipedia(user: str) -> dict:
    """Wikipedia（日本語版）の編集履歴。認証不要。"""
    try:
        j = _get("https://ja.wikipedia.org/w/api.php?action=query&list=usercontribs&uclimit=100&format=json&ucuser=" + urllib.request.quote(user))
        return _recent([c.get("timestamp", "") for c in j.get("query", {}).get("usercontribs", [])], "公開の編集履歴のみ")
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

def atcoder(user: str) -> dict:
    """AtCoder の提出（AtCoder Problems の非公式 API）。認証不要。反映に数日かかることがある。"""
    try:
        import time as _t
        j = _get(f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={urllib.request.quote(user, safe='')}&from_second={int(_t.time()) - 90*86400}")
        return _recent([dt.datetime.fromtimestamp(x["epoch_second"], dt.timezone.utc).strftime("%Y-%m-%d") for x in j], "提出のみ。反映が遅れることがある")
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

def _seen(la: str | None, note: str) -> dict:
    since = (TODAY - dt.timedelta(days=90)).strftime("%Y-%m-%d")
    return {"ok": True, "last_activity": la, "events_90d": 3 if la and la >= since else 0, "note": note}

def lichess(user: str) -> dict:
    """Lichess の seenAt（サイトを最後に開いた日時）。投稿しなくても更新される。認証不要。"""
    try:
        j = _get(f"https://lichess.org/api/user/{urllib.request.quote(user, safe='')}")
        la = dt.datetime.fromtimestamp(j["seenAt"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d") if j.get("seenAt") else None
        return _seen(la, "サイトを最後に開いた日（対局しなくても更新される）")
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

def chesscom(user: str) -> dict:
    """Chess.com の last_online。認証不要。"""
    try:
        j = _get(f"https://api.chess.com/pub/player/{urllib.request.quote(user, safe='')}")
        la = dt.datetime.fromtimestamp(j["last_online"], dt.timezone.utc).strftime("%Y-%m-%d") if j.get("last_online") else None
        return _seen(la, "サイトを最後に開いた日")
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

def stackoverflow(user_id: str) -> dict:
    """Stack Overflow の last_access_date（数字のユーザー ID）。認証不要（1 日 300 回）。"""
    try:
        j = _get(f"https://api.stackexchange.com/2.3/users/{urllib.request.quote(user_id, safe='')}?site=stackoverflow")
        it = (j.get("items") or [{}])[0]
        la = dt.datetime.fromtimestamp(it["last_access_date"], dt.timezone.utc).strftime("%Y-%m-%d") if it.get("last_access_date") else None
        return _seen(la, "サイトを最後に開いた日（読むだけでも更新される）")
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

def letterboxd(user: str) -> dict:
    """Letterboxd の公開 RSS（観た日）。認証不要。"""
    try: return _recent(_rss_dates(f"https://letterboxd.com/{urllib.request.quote(user, safe='')}/rss/", "letterboxd:watchedDate"), "日記に記録した「観た日」のみ")
    except Exception as e: return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"取れない: {str(e)[:80]}"}

FETCHERS = {"GitHub": ("username", github), "Zenn": ("username", zenn), "Qiita": ("username", qiita), "Bluesky": ("handle", bluesky), "Steam": ("steamid64", steam),
            "note": ("username", note), "Mastodon": ("acct", mastodon), "Wikipedia": ("username", wikipedia), "AtCoder": ("username", atcoder),
            "Lichess": ("username", lichess), "Chess.com": ("username", chesscom), "Stack Overflow": ("userid", stackoverflow), "Letterboxd": ("username", letterboxd)}
PENDING_OAUTH = {"Spotify": "user-read-recently-played", "Notion": "read_content", "Strava": "activity:read", "Instagram": "instagram_basic", "Slack": "users:read", "Google Cloud": "cloud-platform.read-only", "X": "有料 API 枠"}

def fetch(name: str, ident: str) -> dict:
    if name in FETCHERS:
        return FETCHERS[name][1](ident)
    if name in PENDING_OAUTH:
        return {"ok": False, "last_activity": None, "events_90d": 0, "note": f"準備中: {name} 側でアプリ登録と本人の同意（{PENDING_OAUTH[name]}）が要る"}
    return {"ok": False, "last_activity": None, "events_90d": 0, "note": "このサービスは合図にならない（地図に載るだけ）"}

def needs(name: str) -> dict:
    """UI 用: 何を入力すれば合図にできるか。"""
    if name in FETCHERS: return {"kind": "id", "label": {"username": f"{name} のユーザー名", "handle": "Bluesky のハンドル", "steamid64": "Steam ID（64 桁）", "acct": "user@instance の形", "userid": "数字のユーザー ID"}[FETCHERS[name][0]], "ready": name != "Steam"}
    if name in PENDING_OAUTH: return {"kind": "oauth", "label": f"{name} の同意（準備中）", "ready": False}
    return {"kind": "none", "label": "", "ready": False}

if __name__ == "__main__":
    import sys
    print(json.dumps(fetch(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""), ensure_ascii=False, indent=1))
