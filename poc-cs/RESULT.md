# Confidential Space attestation PoC ― 結果

実施日: 2026-09-04 / project: forward-vector-470012-n8 / zone: asia-northeast1-a
CS image family: confidential-space-debug / machine: n2d-standard-2 / SEV

## 結論

**同じコード・同じ動作で digest だけが違う2つのイメージを用意し、片方の digest にだけ
Secret Manager の secretAccessor を付与した。承認した digest だけが読めた。**

```
=== cs-vm-a ===
  === workload build=a ===
    image_digest: sha256:e6fbb7945cf8015516bdc6b0ec623df0642847a0a59d444d59f1a536267dfc88
    swname      : CONFIDENTIAL_SPACE
    STS         : OK
    SECRET      : THIS-IS-THE-EXECUTION-CREDENTIAL-1788487923
  RESULT=ALLOWED

=== cs-vm-b ===
  === workload build=b ===
    image_digest: sha256:dffe23e0aa1b4c9e395f2396bcd60b3ff37510364f24bacd5224594b1951ce46
    swname      : CONFIDENTIAL_SPACE
    STS         : OK
    ERROR: SecretManager 403: {
  RESULT=DENIED

```

## 第三者が検証できる形（IAM ポリシー）

```
roles/secretmanager.secretAccessor
  principalSet://iam.googleapis.com/projects/856208492603/locations/global/workloadIdentityPools/cs-pool/attribute.image_digest/sha256:e6fbb7945cf8015516bdc6b0ec623df0642847a0a59d444d59f1a536267dfc88
```

## 途中で踏んだ罠（記事の材料）

1. **IAM の伝播待ち。** workloadUser 付与の直後に起動した VM は
   `confidentialcomputing.locations.list denied` で launcher ごと落ちる。20秒遅れた方は通った
2. **allowed-audiences の既定値。** `--allowed-audiences=https://sts.googleapis.com` を指定すると
   実トークンの aud（provider のリソースパス）と食い違い `invalid_grant` になる。
   `--clear-allowed-audiences` は存在しないので、provider のリソースパスを明示指定して合わせる
3. **配列クレームはマップできない。** `assertion.google_service_accounts` は配列で、
   そのまま attribute-mapping に入れると `must be of type STRING` で STS が落ちる

## 使ったクレーム

```
iss  : https://confidentialcomputing.googleapis.com
attribute-mapping:
  google.subject          = assertion.sub
  attribute.image_digest  = assertion.submods.container.image_digest
  attribute.swname        = assertion.swname
attribute-condition: assertion.swname=='CONFIDENTIAL_SPACE'
付与先: principalSet://iam.googleapis.com/<pool>/attribute.image_digest/<digest>
```
