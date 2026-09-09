#!/usr/bin/env python3
"""Confidential Space の中で走る執行。ここだけが封印を開けられる。

  入力: GCS の users/<uid>/enclave_in_<round>.json（地図・遺志・封印済み資格情報の暗号文・確認者数）
  1. attestation トークン → STS（Workload Identity Pool、image digest 条件）→ KMS asymmetricDecrypt で封印を開ける
     承認された digest 以外のコードには KMS が 403 を返す（poc-kms で実測済み）
  2. 開けた資格情報は enclave のメモリにだけ置く。手紙に載せるのはアカウント ID だけ。パスワードは外に出さない
  3. 決定的な計画 → ゲート → 文面（Gemini）→ 遺族へのご報告
  4. 出力: users/<uid>/enclave_out_<round>.json、outbox、report.md を GCS へ。監査は追記専用バケットへ
  終わったらプロセスを終える（Confidential Space は VM を止める）
"""
from __future__ import annotations
import base64, hashlib, http.client, json, os, socket, sys, urllib.request, urllib.parse, datetime as dt

PROJECT_NUMBER = os.environ["PROJECT_NUMBER"]; PROJECT_ID = os.environ["PROJECT_ID"]
POOL = os.environ.get("POOL", "cs-pool"); PROVIDER = os.environ.get("PROVIDER", "cs-provider")
KEY = os.environ.get("KEY", f"projects/{PROJECT_ID}/locations/asia-northeast1/keyRings/atonokoto/cryptoKeys/seal/cryptoKeyVersions/1")
BUCKET = os.environ["DATA_BUCKET"]; AUDIT_BUCKET = os.environ.get("ATONOKOTO_AUDIT_BUCKET")
UID = os.environ["UID"]; ROUND = os.environ["ROUND"]
AUDIENCE = f"//iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/{POOL}/providers/{PROVIDER}"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "agents", "execute")); sys.path.insert(0, os.path.join(ROOT, "agents", "gate"))

def log(*a): print("[enclave]", *a, flush=True)

class UnixConn(http.client.HTTPConnection):
    def __init__(self, path): super().__init__("localhost"); self.path_ = path
    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(self.path_); self.sock = s

def attestation_token() -> str:
    c = UnixConn("/run/container_launcher/teeserver.sock")
    c.request("POST", "/v1/token", body=json.dumps({"audience": AUDIENCE, "token_type": "OIDC"}), headers={"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read().decode()
    if r.status != 200: raise RuntimeError(f"teeserver {r.status}: {raw[:200]}")
    return raw.strip().strip('"')

def sts_exchange(tok: str) -> str:
    payload = {"audience": AUDIENCE, "grantType": "urn:ietf:params:oauth:grant-type:token-exchange", "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
               "scope": "https://www.googleapis.com/auth/cloud-platform", "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt", "subjectToken": tok}
    req = urllib.request.Request("https://sts.googleapis.com/v1/token", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))["access_token"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"STS {e.code}: {e.read().decode()[:300]}")

def vm_token() -> str:
    """VM に付いたサービスアカウントのトークン（GCS の読み書きに使う。KMS は使えない）。"""
    req = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token", headers={"Metadata-Flavor": "Google"})
    return json.load(urllib.request.urlopen(req))["access_token"]

def gcs_get(tok, name):
    req = urllib.request.Request(f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{urllib.parse.quote(name, safe='')}?alt=media", headers={"Authorization": f"Bearer {tok}"})
    return urllib.request.urlopen(req).read()

def gcs_put(tok, bucket, name, data: bytes, ctype="application/json", no_overwrite=False):
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&name={urllib.parse.quote(name, safe='')}" + ("&ifGenerationMatch=0" if no_overwrite else "")
    req = urllib.request.Request(url, data=data, headers={"Authorization": f"Bearer {tok}", "Content-Type": ctype})
    urllib.request.urlopen(req).read()

def kms_decrypt(at: str, ciphertext_b64: str) -> str:
    req = urllib.request.Request(f"https://cloudkms.googleapis.com/v1/{KEY}:asymmetricDecrypt", data=json.dumps({"ciphertext": ciphertext_b64}).encode(),
                                 headers={"Authorization": f"Bearer {at}", "Content-Type": "application/json"})
    try:
        return base64.b64decode(json.load(urllib.request.urlopen(req))["plaintext"]).decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"KMS {e.code}: {e.read().decode()[:200]}")

def main():
    out = {"round": ROUND, "uid": UID, "started": dt.datetime.now(dt.timezone.utc).isoformat(), "opened": [], "failed": [], "digest": None}
    vt = vm_token()
    inp = json.loads(gcs_get(vt, f"users/{UID}/enclave_in_{ROUND}.json"))
    try:
        tok = attestation_token()
        p = tok.split(".")[1]; p += "=" * (-len(p) % 4); claims = json.loads(base64.urlsafe_b64decode(p))
        out["digest"] = claims.get("submods", {}).get("container", {}).get("image_digest"); log("image_digest:", out["digest"])
        at = sts_exchange(tok); log("STS: OK")
    except Exception as e:
        out["error"] = f"attestation/STS 失敗: {str(e)[:200]}"; log(out["error"]); at = None
    # 1) 封印を開ける（このコードの digest が承認されていなければ KMS が拒否する）
    opened = {}
    for asset, ct in (inp.get("sealed") or {}).items():
        try:
            plain = kms_decrypt(at, ct) if at else None
            if plain is None: raise RuntimeError("attestation 無し")
            data = json.loads(plain) if plain.strip().startswith("{") else {"account_id": plain.strip()}
            opened[asset] = data
            out["opened"].append({"asset": asset, "proof": hashlib.sha256(plain.encode()).hexdigest()[:12], "fields": sorted(k for k in data.keys())})
            log("opened:", asset, "fields:", sorted(data.keys()))
        except Exception as e:
            out["failed"].append({"asset": asset, "error": str(e)[:160]}); log("failed:", asset, str(e)[:160])
    # 2) 計画 → ゲート → 文面 → 報告（execute agent）。開けた資格情報はアカウント ID だけを手紙に使う
    import agent as ex
    from policy import Context
    tmp = "/tmp/enclave"; os.makedirs(tmp, exist_ok=True)
    json.dump(inp["assets"], open(f"{tmp}/assets.json", "w"), ensure_ascii=False); json.dump(inp["will"], open(f"{tmp}/will.json", "w"), ensure_ascii=False)
    assets = ex.load_map(f"{tmp}/assets.json", f"{tmp}/will.json")
    for a in assets:
        if a["name"] in opened: a["account_id"] = opened[a["name"]].get("account_id")   # パスワード等は渡さない
    steps = ex.plan(assets)
    ctx = Context(confirmers=int(inp.get("confirmers", 0)), unlocked_tracks={"stop", "hand"}, remaining={a["name"]: True for a in assets})
    audit_path = f"{tmp}/audit.jsonl"
    os.environ["ATONOKOTO_AUDIT_BUCKET"] = AUDIT_BUCKET or ""
    execd = ex.execute(assets, steps, ctx, inp.get("person", "本人"), f"{tmp}/outbox", audit_path, do_letters=bool(inp.get("letters", True)), round_id=ROUND)
    rp = ex.report(assets, execd, f"{tmp}/report.md")
    out["results"] = execd["results"]; out["finished"] = dt.datetime.now(dt.timezone.utc).isoformat()
    del opened   # メモリ上の平文はここで終わり
    # 3) 出力を GCS へ（VM の SA で）。監査は追記専用バケットへ
    for fn in os.listdir(f"{tmp}/outbox"):
        gcs_put(vt, BUCKET, f"users/{UID}/outbox/{fn}", open(f"{tmp}/outbox/{fn}", "rb").read(), "text/plain")
    gcs_put(vt, BUCKET, f"users/{UID}/report.md", open(rp, "rb").read(), "text/markdown")
    if AUDIT_BUCKET:
        gcs_put(vt, AUDIT_BUCKET, f"enclave/{UID}/{ROUND}/audit.jsonl", open(audit_path, "rb").read(), "text/plain", no_overwrite=True)
        gcs_put(vt, AUDIT_BUCKET, f"enclave/{UID}/{ROUND}/result.json", json.dumps(out, ensure_ascii=False).encode(), no_overwrite=True)
    gcs_put(vt, BUCKET, f"users/{UID}/enclave_out_{ROUND}.json", json.dumps(out, ensure_ascii=False).encode())
    log("done:", len(out["opened"]), "opened,", len(out["failed"]), "failed,", len(out["results"]), "steps")

if __name__ == "__main__":
    try: main()
    except Exception as e:
        log("FATAL:", str(e)[:300])
        try: gcs_put(vm_token(), BUCKET, f"users/{UID}/enclave_out_{ROUND}.json", json.dumps({"round": ROUND, "error": str(e)[:300]}).encode())
        except Exception: pass
        sys.exit(1)
