#!/usr/bin/env python3
"""配備先の IAM が文書の主張どおりかを検査する（読み取りのみ）。
  - KMS の復号は infra/enclave_digest.txt の digest ひとつだけ
  - Cloud Run の SA は KMS の公開鍵閲覧だけ（復号できない）
  - WIF の条件に CONFIDENTIAL_SPACE と STABLE、起動元プロジェクト、dbgstat
  - 利用者秘密のロールは atonokoto-u-* と Project 型に限定（SecretVersion を全部通す条件が無い）
  - 監査バケットの SA は objectCreator だけ
"""
import json, subprocess, sys, os
P = os.environ.get("ATONOKOTO_PROJECT", "forward-vector-470012-n8")
HERE = os.path.dirname(os.path.abspath(__file__))
def g(*args):
    return json.loads(subprocess.run(["gcloud", *args, "--project", P, "--format", "json"], capture_output=True, text=True, check=True).stdout)
digest = open(os.path.join(HERE, "..", "infra", "enclave_digest.txt")).read().strip()
T = []
kms = g("kms", "keys", "get-iam-policy", "seal", "--keyring", "atonokoto", "--location", "asia-northeast1")
dec = [m for b in kms.get("bindings", []) if b["role"] == "roles/cloudkms.cryptoKeyDecrypter" for m in b["members"]]
T.append(("KMS 復号は digest ひとつ", len(dec) == 1 and dec[0].endswith("/attribute.image_digest/" + digest), dec))
T.append(("Cloud Run の SA は復号できない", not any("atonokoto-run@" in m for m in dec), None))
prov = g("iam", "workload-identity-pools", "providers", "describe", "cs-provider", "--workload-identity-pool", "cs-pool", "--location", "global")
cond = prov.get("attributeCondition", "")
T.append(("WIF は CONFIDENTIAL_SPACE かつ STABLE", "CONFIDENTIAL_SPACE" in cond and "STABLE" in cond, cond))
T.append(("WIF は起動元プロジェクトと非デバッグ（dbgstat）も縛る", f"submods.gce.project_id == '{P}'" in cond and "dbgstat == 'disabled-since-boot'" in cond, cond))
pol = g("projects", "get-iam-policy", P)
us = [b for b in pol["bindings"] if b["role"].endswith("atonokotoUserSecrets")]
T.append(("利用者秘密のロールは条件付きで、SecretVersion を全部通す条件が無い",
          all(b.get("condition") and "atonokoto-u-" in b["condition"]["expression"] and "!=" not in b["condition"]["expression"] for b in us) and bool(us),
          [b.get("condition", {}).get("expression") for b in us]))
for s in ("sealed-cred", "exec-cred"):
    try:
        sp = g("secrets", "get-iam-policy", s)
        acc = [m for b in sp.get("bindings", []) if b["role"] == "roles/secretmanager.secretAccessor" for m in b["members"]]
        T.append((f"PoC の秘密 {s} に承認外 digest の読み取りが無い", all(m.endswith(digest) for m in acc), acc))
    except subprocess.CalledProcessError: T.append((f"PoC の秘密 {s} は無い", True, None))
buckets = json.loads(subprocess.run(["gcloud", "storage", "ls", "--project", P, "--format", "json"], capture_output=True, text=True).stdout or "[]")
aud = [b["name"] if isinstance(b, dict) else str(b) for b in buckets if "audit-files" in json.dumps(b)]
if aud:
    name = aud[0] if aud[0].startswith("gs://") else "gs://" + aud[0].strip("/")
    bp = json.loads(subprocess.run(["gcloud", "storage", "buckets", "get-iam-policy", name, "--project", P, "--format", "json"], capture_output=True, text=True).stdout)
    roles = {m: b["role"] for b in bp.get("bindings", []) for m in b["members"] if "atonokoto-run@" in m or "cs-workload@" in m}
    T.append(("監査バケットの SA は objectCreator だけ", bool(roles) and all(r == "roles/storage.objectCreator" for r in roles.values()), roles))
ok = 0
for name, res, ev in T:
    ok += bool(res); print(("ok " if res else "NG ") + name + ("" if res else f"  ← {ev}"))
print(f"{ok}/{len(T)}")
sys.exit(0 if ok == len(T) else 1)
