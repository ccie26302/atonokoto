#!/usr/bin/env python3
"""Confidential Space のワークロード。
launcher から attestation トークンを取り、STS で交換して Secret Manager を読む。
承認された image digest でなければ、ここで落ちるのが正しい挙動。"""
import http.client, json, os, socket, sys, urllib.request

PROJECT_NUMBER = os.environ["PROJECT_NUMBER"]
POOL = os.environ.get("POOL", "cs-pool")
PROVIDER = os.environ.get("PROVIDER", "cs-provider")
SECRET = os.environ.get("SECRET", "exec-cred")
AUDIENCE = (f"//iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global"
            f"/workloadIdentityPools/{POOL}/providers/{PROVIDER}")
MARK = os.environ.get("BUILD_MARK", "?")


class UnixConn(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost")
        self.path_ = path
    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.path_)
        self.sock = s


def attestation_token():
    """launcher の teeserver から attestation トークンを貰う。"""
    body = json.dumps({"audience": AUDIENCE, "token_type": "OIDC"})
    c = UnixConn("/run/container_launcher/teeserver.sock")
    c.request("POST", "/v1/token", body=body, headers={"Content-Type": "application/json"})
    r = c.getresponse()
    raw = r.read().decode()
    if r.status != 200:
        raise RuntimeError(f"teeserver {r.status}: {raw[:300]}")
    return raw.strip().strip('"')


def sts_exchange(tok):
    """STS で federated access token に交換する。"""
    payload = {
        "audience": AUDIENCE,
        "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
        "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
        "scope": "https://www.googleapis.com/auth/cloud-platform",
        "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
        "subjectToken": tok,
    }
    req = urllib.request.Request("https://sts.googleapis.com/v1/token",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))["access_token"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"STS {e.code}: {e.read().decode()[:400]}")


def read_secret(access_token):
    url = (f"https://secretmanager.googleapis.com/v1/projects/{PROJECT_NUMBER}"
           f"/secrets/{SECRET}/versions/latest:access")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        import base64
        d = json.load(urllib.request.urlopen(req))
        return base64.b64decode(d["payload"]["data"]).decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"SecretManager {e.code}: {e.read().decode()[:400]}")


if __name__ == "__main__":
    print(f"=== workload build={MARK} ===", flush=True)
    try:
        tok = attestation_token()
        import base64
        payload = tok.split(".")[1]; payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        print("  image_digest:", claims.get("submods", {}).get("container", {}).get("image_digest"), flush=True)
        print("  swname      :", claims.get("swname"), flush=True)
        at = sts_exchange(tok)
        print("  STS         : OK", flush=True)
        print("  SECRET      :", read_secret(at), flush=True)
        print("RESULT=ALLOWED", flush=True)
    except Exception as e:
        print("  ERROR:", e, flush=True)
        print("RESULT=DENIED", flush=True)
