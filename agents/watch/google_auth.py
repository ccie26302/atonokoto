#!/usr/bin/env python3
"""同意を 2 回に分けて取る。全て読み取りのみ。書き込み系のスコープは一切含めない。

  python google_auth.py inventory   → 棚卸しの同意（Gmail 本文まで。一回きり。読み終えたら token を消す）
  python google_auth.py watch       → 見張りの同意（Gmail メタデータ・Drive 活動・Calendar。本文は読まない）
  python google_auth.py status      → 今持っているトークンとスコープを表示
  python google_auth.py forget inventory|watch → トークンを捨てる（Google 側の revoke も呼ぶ）

前提: secrets/client_secret.json（OAuth クライアント「デスクトップ アプリ」）。同意画面は External + Testing、
本人をテストユーザーに登録しておく。トークンは secrets/token_<name>.json にだけ置く（git 管理外）。"""
import json, os, sys, urllib.request, urllib.parse
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.environ.get("ATONOKOTO_SECRETS_DIR", os.path.join(HERE, "..", "..", "secrets"))
CLIENT = os.path.join(SECRETS, "client_secret.json")

def _materialize_from_env():
    """Cloud Run では Secret Manager を環境変数で受け取り、起動時にコンテナ内のファイルへ書く（永続化しない）。
    ローカルでは何もしない。"""
    pairs = {"ATONOKOTO_CLIENT_SECRET_JSON": "client_secret.json", "ATONOKOTO_TOKEN_WATCH_JSON": "token_watch.json",
             "ATONOKOTO_TOKEN_INVENTORY_JSON": "token_inventory.json", "ATONOKOTO_CONFIRM_KEY": "confirm_key", "ATONOKOTO_SESSION_KEY": "session_key"}
    for env, fn in pairs.items():
        v = os.environ.get(env)
        if not v or v.strip() in ("", "{}"): continue   # 未ログイン（空のバージョン）
        os.makedirs(SECRETS, exist_ok=True); p = os.path.join(SECRETS, fn)
        if not os.path.exists(p):
            open(p, "w").write(v); os.chmod(p, 0o600)
_materialize_from_env()

SCOPES = {
    # 棚卸し: 受信箱を読む（本文まで）。一回きり
    "inventory": ["https://www.googleapis.com/auth/gmail.readonly"],
    # 見張り: 本文は読まない。既読・送信の日時、Drive の活動、予定の更新だけ
    "watch": ["https://www.googleapis.com/auth/gmail.metadata",
              "https://www.googleapis.com/auth/drive.activity.readonly",
              "https://www.googleapis.com/auth/calendar.readonly",
              "https://www.googleapis.com/auth/youtube.readonly"],   # 高評価・チャンネル登録の日付（利用者側の合図）
}
READ_ONLY_MARKERS = ("readonly", "metadata", "activity.readonly")

import hashlib as _hl
def user_id(email: str) -> str:
    """Google アカウントのメールから利用者 ID。メールそのものはパスや秘密名に使わない。"""
    return _hl.sha256(email.strip().lower().encode()).hexdigest()[:16]

def token_path(name, uid: str | None = None):
    return os.path.join(SECRETS, "users", uid, f"token_{name}.json") if uid else os.path.join(SECRETS, f"token_{name}.json")

def _secret_name(name, uid): return f"atonokoto-u-{uid}-{name}"

def _sm_call(method, url, body=None):
    import urllib.request
    from google.auth import default as _default
    from google.auth.transport.requests import Request as _Req
    c, project = _default(scopes=["https://www.googleapis.com/auth/cloud-platform"]); c.refresh(_Req())
    req = urllib.request.Request(url.replace("{project}", os.environ.get("GOOGLE_CLOUD_PROJECT", project)), method=method,
                                 data=(json.dumps(body).encode() if body is not None else None),
                                 headers={"Authorization": f"Bearer {c.token}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=20))

def _sm_fetch(name, uid) -> str | None:
    """本番: 利用者のトークンを Secret Manager から読む（無ければ None）。"""
    import base64, urllib.error
    try:
        r = _sm_call("GET", f"https://secretmanager.googleapis.com/v1/projects/{{project}}/secrets/{_secret_name(name, uid)}/versions/latest:access")
        v = base64.b64decode(r["payload"]["data"]).decode()
        return None if v.strip() in ("", "{}") else v
    except urllib.error.HTTPError as e:
        if e.code in (404, 403): return None
        raise

def persist_token(name: str, payload: str, uid: str | None = None):
    """Cloud Run ではコンテナのファイルは消えるので、トークンを Secret Manager に保存する（利用者ごとの秘密。無ければ作る）。
    古いバージョンは無効化し、最新だけを有効にする。ローカルでは何もしない。空文字列を保存すると『未ログイン』になる。"""
    if not os.environ.get("K_SERVICE"): return
    import base64, urllib.error
    sname = _secret_name(name, uid) if uid else f"atonokoto-token_{name}"
    base = "https://secretmanager.googleapis.com/v1/projects/{project}"
    try:
        _sm_call("GET", f"{base}/secrets/{sname}")
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
        _sm_call("POST", f"{base}/secrets?secretId={sname}", {"replication": {"automatic": {}}, "labels": {"app": "atonokoto", "kind": name}})
    r = _sm_call("POST", f"{base}/secrets/{sname}:addVersion", {"payload": {"data": base64.b64encode((payload or "{}").encode()).decode()}})
    new_ver = r.get("name", "").rsplit("/", 1)[-1]
    try:
        for v in _sm_call("GET", f"{base}/secrets/{sname}/versions?filter=state:ENABLED").get("versions", []):
            ver = v["name"].rsplit("/", 1)[-1]
            if ver != new_ver: _sm_call("POST", f"{base}/secrets/{sname}/versions/{ver}:disable", {})
    except Exception: pass

def load(name, uid: str | None = None) -> Credentials | None:
    p = token_path(name, uid)
    if uid and not os.path.exists(p) and os.environ.get("K_SERVICE", os.environ.get("CLOUD_RUN_JOB")):
        v = _sm_fetch(name, uid)
        if not v: return None
        os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(v); os.chmod(p, 0o600)   # コンテナ内だけ。永続化しない
    if not os.path.exists(p): return None
    info = json.load(open(p))
    # 同意した時点のスコープで読む。後から足したスコープ（YouTube 等）を refresh で要求すると invalid_scope になるため。
    # 足りないスコープの源は API が 403 を返すので、その源は「無い」として扱う（再同意すれば増える）
    c = Credentials.from_authorized_user_info(info, info.get("scopes") or SCOPES[name])
    if c.expired and c.refresh_token:
        try: c.refresh(Request())
        except Exception as e: print(f"  {name}: 更新できない（読めない状態）: {e}"); return None
        try: open(p, "w").write(c.to_json())
        except OSError: pass   # Secret Manager を読み取り専用でマウントしている場合。refresh_token は変わらないので問題ない
    return c

def consent(name):
    for s in SCOPES[name]:
        assert any(m in s for m in READ_ONLY_MARKERS), f"書き込みスコープは禁止: {s}"
    if not os.path.exists(CLIENT):
        sys.exit(f"{CLIENT} が無い。Console で OAuth クライアント（デスクトップ アプリ）を作って置いてください")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT, SCOPES[name])
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    os.makedirs(SECRETS, exist_ok=True); open(token_path(name), "w").write(creds.to_json()); os.chmod(token_path(name), 0o600)
    print(f"  {name}: 同意を取得。スコープ: {sorted(creds.scopes or [])}")
    print(f"  refresh_token: {'あり' if creds.refresh_token else '無し（prompt=consent で再取得）'}")

def forget(name, uid: str | None = None):
    c = load(name, uid)
    if c:
        try:
            urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/revoke",
                data=urllib.parse.urlencode({"token": c.refresh_token or c.token}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"}))
            print(f"  {name}: Google 側で revoke した")
        except Exception as e: print(f"  {name}: revoke 失敗: {e}")
    if os.path.exists(token_path(name, uid)): os.remove(token_path(name, uid)); print(f"  {name}: token を消した")
    try: persist_token(name, "{}", uid)
    except Exception as e: print(f"  {name}: Secret Manager 側の無効化に失敗: {e}")

def status():
    for name in SCOPES:
        c = load(name)
        print(f"  {name}: {'あり' if c else '無し'}" + (f"  scopes={sorted(c.scopes or [])}" if c else ""))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd in SCOPES: consent(cmd)
    elif cmd == "forget": forget(sys.argv[2])
    else: status()
