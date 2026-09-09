# 書き込み経路 PoC（KMS 非対称鍵で封をする）― 結果

実施日: 2026-09-04 / project: forward-vector-470012-n8 / KMS: asia-northeast1/atonokoto/seal（RSA_DECRYPT_OAEP_4096_SHA256）

## 結論（言えることと、言えないこと）

| 主張 | 結果 |
|---|---|
| 平文はブラウザを出た瞬間に暗号文になり、サーバは一度も平文を持たない | **成立**。公開鍵で暗号化してから送るので、書き込み経路に平文が流れない |
| 承認済み digest の Confidential Space ワークロードだけが復号できる | **成立**。同一コード・digest 違いの2イメージで、A は復号成功、B は KMS 403 |
| 暗号文そのものは誰でも読める（開発者も） | **成立**。秘密なのは復号能力であって暗号文ではない |
| 開発者（project owner）は復号できない | **不成立**。owner は `roles/owner` で復号できた。「Owner に KMS 復号は含まれない」という前提は誤りだった |
| owner が復号すれば必ずログに残る | **条件付きで成立**。KMS の DATA_READ 監査ログは**既定で無効**。有効化前の復号2回はログ0件。有効化後は `data_access` に記録された |

## 実測

```
kms-a（承認済み digest 24f84f5d…）
  STS: OK → sealed 512 bytes → KMS decrypt: OK → PLAINTEXT 一致   RESULT=ALLOWED
kms-b（未承認 digest b6ad2ed8…）
  STS: OK → sealed 512 bytes → cloudkms 403                        RESULT=DENIED

owner（gcloud kms asymmetric-decrypt）
  監査ログ有効化前: 復号成功、ログ 0 件
  監査ログ有効化後: 復号成功、data_access に AsymmetricDecrypt が記録
```

## 鍵の IAM（第三者が検証できる）

```
roles/cloudkms.cryptoKeyDecrypter
  principalSet://iam.googleapis.com/projects/856208492603/locations/global/workloadIdentityPools/cs-pool
    /attribute.image_digest/sha256:24f84f5de00e4c3be76de165205ac5540c463c91ec5ff63d226a27ac684f7612
```
暗号文（Secret Manager `sealed-cred`）の secretAccessor は A・B 両方に付与。**読めるのは両方、開けるのは A だけ。**

## 設計への帰結

- 「開発者も読めない」は、開発者が owner のプロジェクト内では**どう組んでも言えない**。主張は可視性版にする
- 可視性版は、**KMS の DATA_READ 監査ログを有効化し、ログバケットをロックする**ことが前提。有効化しないと嘘になる
- 本当に「開発者も読めない」に近づけるには、鍵を本人のプロジェクトに置く（設計書に図として残す。6週間では実装しない）

## 踏んだ罠

1. RSA 4096 の鍵は生成に時間がかかり、`PENDING_GENERATION` 中は公開鍵が取れない。その状態で走らせた「owner は復号できない」は、ファイルが無かっただけの偽の結果だった
2. KMS の DATA_READ 監査ログは既定で無効。「読めば痕跡が残る」は設定しないと成り立たない
3. `gcloud kms asymmetric-decrypt --plaintext-file=/dev/null` は書き込み拒否で落ちる（API 呼び出し自体は行われ、ログには残る）
