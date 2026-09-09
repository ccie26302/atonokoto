#!/usr/bin/env python3
"""配備したサイトに対する安全側の検査。合格・不合格を並べる。
  python tests/security_check.py https://…run.app
"""
import json, sys, json, urllib.request, urllib.error, html

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8765"
R = []
def get(path, method="GET", data=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=30); return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e: return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()

# 1) 個人データ・状態・ソース・秘密が静的に取れない
for p in ["/data/watch_state.json", "/data/footprint_real.json", "/data/confirmations.json", "/data/will.json", "/data/confirmers.json",
          "/data/ext_sources.json", "/data/report.md", "/agents/watch/run.py", "/web/server.py", "/Dockerfile", "/secrets/token_watch.json", "/.dockerignore", "/data/../web/server.py"]:
    st, _, _ = get(p); R.append((f"静的に取れない {p}", st in (403, 404)))
# 2) 許可したものは取れる
for p in ["/web/index.html", "/data/catalog.json", "/data/assets.json"]:
    st, _, _ = get(p); R.append((f"許可した静的ファイル {p}", st == 200))
# 3) 個人 API はセッション無しで拒否
for p in ["/api/watch", "/api/assets?me=1", "/api/footprint", "/api/source_check?name=GitHub&id=x"]:
    st, _, _ = get(p); R.append((f"セッション無しで拒否 {p}", st == 401))
st, _, _ = get("/logout"); R.append(("GET /logout は状態を変えない（405）", st == 405))
st, _, _ = get("/logout", "POST"); R.append(("POST /logout もセッション無しでは 401", st == 401))
for p in ["/api/will", "/api/confirmers", "/api/sources", "/api/inventory"]:
    st, _, _ = get(p, "POST", b"{}", {"Content-Type": "application/json"}); R.append((f"セッション無しで拒否 POST {p}", st == 401))
# 4) 偽のセッション Cookie は通らない
st, _, _ = get("/api/watch", headers={"Cookie": "atonokoto_session=a@b.c|9999999999|deadbeefdeadbeefdeadbeefdeadbeef"}); R.append(("偽の署名の Cookie を拒否", st == 401))
st, _, _ = get("/api/watch", headers={"Cookie": "atonokoto_session=a@b.c|1|" + "0"*32}); R.append(("期限切れの Cookie を拒否", st == 401))
# 5) 偽の確認トークンは無効
st, _, body = get("/api/confirm_info", "POST", json.dumps({"u": "0123456789abcdef", "t": "0"*32}).encode(), {"Content-Type": "application/json"}); R.append(("偽の確認リンクは『無効』", st == 200 and '"valid": false' in body.decode()))
st, _, body = get("/confirm?u=0123456789abcdef"); R.append(("確認ページはトークン無しでは中身を出さない", st == 200 and "explanation" not in body.decode().split("__CTX__")[0][-200:] and '"u": "0123456789abcdef"' in body.decode()))

st, _, _ = get("/api/confirm", "POST", json.dumps({"t": "0"*32, "vote": "unreachable"}).encode(), {"Content-Type": "application/json"}); R.append(("偽トークンでの投票を拒否", st == 403))
# 6) 安全側のヘッダ
st, h, _ = get("/web/index.html")
R.append(("CSP がある", "content-security-policy" in h))
R.append(("CSP の script に unsafe-inline が無い（nonce 方式）", "unsafe-inline" not in h.get("content-security-policy", "").split("style-src")[0]))
st, _, body = get("/api/me"); R.append(("未ログインの /api/me は最小限", st == 200 and b"inventory_consent" not in body))
R.append(("frame-ancestors none", "frame-ancestors 'none'" in h.get("content-security-policy", "")))
R.append(("nosniff", h.get("x-content-type-options") == "nosniff"))
R.append(("no-store", "no-store" in h.get("cache-control", "")))
# 7) 開発用の /dev/session が本番に無い
st, _, _ = get("/dev/session"); R.append(("/dev/session が本番に無い", st == 404 or BASE.startswith("http://localhost")))
# 8) デモの連打制限（3 回目まで 200、以降 429。ただし直前に叩いていれば早く 429 になる）
codes = [get("/api/demo/fire", "POST")[0] for _ in range(4)]
R.append((f"デモ発火の連打制限 {codes}", 429 in codes))
st, _, _ = get("/api/demo/fire", "POST", headers={"X-Forwarded-For": "203.0.113.9"}); R.append(("X-Forwarded-For の偽装で制限を抜けられない", st == 429 or BASE.startswith("http://localhost")))
codes = [get("/api/interpret", "POST", b'{"say":"x"}', {"Content-Type": "application/json"})[0] for _ in range(6)]
R.append((f"一言（Gemini）の連打制限 {codes[-1]}", 429 in codes))
# 9) エスケープ関数の単体（画面と同じ規則）
def esc(v): return html.escape(str(v), quote=True).replace("&#x27;", "&#39;")
R.append(("エスケープで < が消える", "<" not in esc("<img src=x onerror=alert(1)>")))

ok = sum(1 for _, v in R if v)
for name, v in R: print(f"  {'OK ' if v else 'NG '} {name}")
print(f"\n{ok}/{len(R)}  ({BASE})")
sys.exit(0 if ok == len(R) else 1)
