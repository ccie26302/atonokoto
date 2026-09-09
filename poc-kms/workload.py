#!/usr/bin/env python3
"""Confidential Space ワークロード（KMS 版）。
attestation トークン → STS → KMS asymmetricDecrypt で、封印された資格情報を開く。
承認された image digest でなければ KMS が 403 を返すのが正しい挙動。"""
import base64, http.client, json, os, socket, urllib.request

PROJECT_NUMBER = os.environ["PROJECT_NUMBER"]
PROJECT_ID = os.environ["PROJECT_ID"]
POOL = os.environ.get("POOL", "cs-pool")
PROVIDER = os.environ.get("PROVIDER", "cs-provider")
SEALED_SECRET = os.environ.get("SEALED_SECRET", "sealed-cred")
KEY = os.environ.get("KEY", f"projects/{PROJECT_ID}/locations/asia-northeast1/keyRings/atonokoto/cryptoKeys/seal/cryptoKeyVersions/1")
AUDIENCE = (f"//iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global"
            f"/workloadIdentityPools/{POOL}/providers/{PROVIDER}")
MARK = os.environ.get("BUILD_MARK", "?")


class UnixConn(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost"); self.path_ = path
    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(self.path_); self.sock = s


def attestation_token():
    c = UnixConn("/run/container_launcher/teeserver.sock")
    c.request("POST", "/v1/token", body=json.dumps({"audience": AUDIENCE, "token_type": "OIDC"}),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read().decode()
    if r.status != 200:
        raise RuntimeError(f"teeserver {r.status}: {raw[:300]}")
    return raw.strip().strip('"')


def sts_exchange(tok):
    payload = {"audience": AUDIENCE,
               "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
               "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
               "scope": "https://www.googleapis.com/auth/cloud-platform",
               "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
               "subjectToken": tok}
    req = urllib.request.Request("https://sts.googleapis.com/v1/token",
                                 data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))["access_token"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"STS {e.code}: {e.read().decode()[:300]}")


def get_json(url, at, data=None):
    req = urllib.request.Request(url, data=(json.dumps(data).encode() if data else None),
                                 headers={"Authorization": f"Bearer {at}", "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{url.split('/')[2]} {e.code}: {e.read().decode()[:300]}")


if __name__ == "__main__":
    print(f"=== workload(kms) build={MARK} ===", flush=True)
    try:
        tok = attestation_token()
        p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
        claims = json.loads(base64.urlsafe_b64decode(p))
        print("  image_digest:", claims.get("submods", {}).get("container", {}).get("image_digest"), flush=True)
        at = sts_exchange(tok); print("  STS         : OK", flush=True)
        # 1) 暗号文は誰でも読める（開発者も）。これは秘密ではない
        sm = get_json(f"https://secretmanager.googleapis.com/v1/projects/{PROJECT_NUMBER}/secrets/{SEALED_SECRET}/versions/latest:access", at)
        sealed_b64 = sm["payload"]["data"]
        print("  sealed      :", len(base64.b64decode(sealed_b64)), "bytes (ciphertext)", flush=True)
        # 2) 復号は attested な digest にしか許されていない
        r = get_json(f"https://cloudkms.googleapis.com/v1/{KEY}:asymmetricDecrypt", at, {"ciphertext": sealed_b64})
        plain = base64.b64decode(r["plaintext"]).decode()
        print("  KMS decrypt : OK", flush=True)
        print("  PLAINTEXT   :", plain, flush=True)
        print("RESULT=ALLOWED", flush=True)
    except Exception as e:
        print("  ERROR:", e, flush=True)
        print("RESULT=DENIED", flush=True)
