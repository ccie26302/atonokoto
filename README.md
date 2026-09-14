# あとのこと（atonokoto）

何があるかを描く。誰に渡すかを塗る。いなくなったら、そのとおりに。

いなくなった後のデジタルの持ち物（サブスク、写真、アカウント）を、生前に本人が決めたとおりに止め、渡し、報告する AI エージェント。Google Cloud 上で動く。第5回 Agentic AI Hackathon with Google Cloud の応募作。

- 本番: https://atonokoto-web-52kgcfrghq-an.a.run.app/web/index.html （審査用アカウントは `/web/judge.html`。ログイン不要の「架空の人の地図を見る」もある）
- 全体像: `docs/OVERVIEW.md`（何をするもので、どう動いているか。実測値つき）
- 構成図: `docs/architecture.png`

- `DESIGN.md` 設計（v6.3）
- `THREAT_MODEL.md` 脅威モデル。守るもの・誰から・対策と証拠・まだ甘いところ
- `ARCHITECTURE.md` 構成
- `poc-cs/` `poc-kms/` 封印の PoC（検証用。復号結果を標準出力に出す作りなので、本番の鍵からは権限を外してある）
- `agents/inventory/` 棚卸しエージェント（ADK, scout→linker→classifier→verifier）
- `agents/will/` 遺志の解釈エージェント（ADK, 一言→塗り分け／聞き返し／拒否）
- `agents/gate/` ポリシーゲート（LLM 不在・決定的・監査鎖つき）
- `agents/execute/` 執行（計画は決定的、LLM は文面だけ。止める → 渡す → ハブは最後）。`enclave.py` は Confidential Space の中で走り、封印を開ける唯一の経路（`Dockerfile.cs`、digest は `infra/enclave_digest.txt`）
- `agents/watch/` 見張り。`run.py` が 1 日 1 回裏で走る（本番は Cloud Scheduler → Cloud Run ジョブ）。`state.py` 床つき状態機械（弱い源、猶予の下限）、`plan.py` 加入時の見張り計画、`signals_google.py` Gmail メタデータ・Drive・Calendar・YouTube、`purchases.py` 買い物・予約・振込の通知メール（33 店。件名は保存しない）、`signals_ext.py` 足したサービスの合図（GitHub・Zenn・Qiita・Bluesky・note・Mastodon・Wikipedia・AtCoder・Lichess・Chess.com・Stack Overflow・Letterboxd は認証不要で動作）。説明が要るときは ADK の調査係（読み取り専用ツール 4 つ）→ 判断係。確認者の承認は署名つきリンク → `/confirm`
- `data/` 架空の故人の合成データと、手で足せるサービスの一覧（`catalog.json`。合図になるかを持つ）
- `web/` 星図と、一言の入力（`server.py` が解釈エージェントを HTTP で呼ぶ）
- `tests/` 採点と両側検証（Model Armor の検知率、注入への追従、遺志解釈のケース、見張りの判断、執行、配備先の安全側検査 `security_check.py`、IAM の検査 `infra_check.py`、innerHTML の未エスケープ検出 `xss_lint.py`、確認者の承認経路 `confirm_flow.py`、送信の制約 `mailer_check.py`）

## 動かす

棚卸しエージェント（ADK, gemini-3.5-flash / Vertex global）。合成データ `data/` を読んで `data/assets.json` を作る。何も変更しない。

```bash
source ../airlock/.venv/bin/activate
python data/make_inbox.py            # 架空の故人「山田太郎」の受信箱・OAuth 連携・活動を生成（data/ 内で実行）
python agents/inventory/agent.py data
python tests/score_inventory.py data # truth.json と突き合わせて採点。data/runs/ に複数回分を置けば N 回の平均と幅
```

遺志の解釈。一言を JSON にする。`--bench` で `tests/will_cases.json` を N 回ずつ回す。

```bash
python agents/will/agent.py "写真は妻に"
python agents/will/agent.py --bench 5
```

見張りの状態機械（25 ケース）と見張り計画（3 人物像 × N）。

```bash
python agents/watch/state.py
python agents/watch/plan.py --bench 3
```

ポリシーゲートの単体テスト（16 ケース、監査鎖の検証つき）。

```bash
python agents/gate/policy.py
```

地図（星図）。`data/assets.json` を読み、遺志を塗る・聞き返す・あとがきを書く。「一言で」の欄は `server.py` 経由で解釈エージェントを呼ぶ。

```bash
python web/server.py 8765   # → http://localhost:8765/web/index.html
```

Model Armor の両側検証（良性 71 通の誤検知と、注入 10 変種の検知）。

```bash
MA_TEMPLATE=atonokoto-inbox python tests/armor_check.py data inbox.json
MA_TEMPLATE=atonokoto-inbox python tests/armor_check.py data injections.json
```

## 本番（Cloud Run）

```bash
bash infra/deploy.sh
```

稼働中: https://atonokoto-web-52kgcfrghq-an.a.run.app （審査員は「架空の人の地図を見る」から）。同じイメージから、サービス `atonokoto-web`（審査員向けサイト・本人の地図）とジョブ `atonokoto-watch`（見張り、Cloud Scheduler が毎朝 6:30 JST に起動）を作る。状態は GCS バケットを `/app/data` にマウント、秘密（OAuth クライアント・見張りトークン・署名鍵）は Secret Manager を `/app/secrets` に読み取り専用でマウント。サービスアカウントの権限はバケット・Vertex AI・指定シークレットの読み取りだけ。個人の情報を返す API は、ログインした本人の署名つき Cookie が無ければ返さない。利用者は Google アカウントごとに分かれる（置き場 `data/users/<id>/`、トークンは利用者ごとの Secret Manager の秘密）。見張りジョブは全利用者を順に回る。

## データの所在（正直に）

- 受信箱の本文は、棚卸しの一回だけ Vertex AI の Gemini（`global` エンドポイント）に渡す。Google Cloud の生成 AI はお客様データを学習に使わない。通過した本文は保存しない。見張りはメタデータ（既読・送信の日時、買い物・予約の通知の差出人と件名の型）だけを扱い、本文は渡さない。件名は判定に使うだけで保存しない
- 地図・遺志・状態は本人のプロジェクトの GCS バケット（asia-northeast1）。トークンは Secret Manager。どちらもプロジェクト外に出ない
- 手紙の送信先は、本人が登録した確認者・遺志で指定した相手・本人だけ。それ以外へは送らない（`mailer.py` が拒否し、記録する）

## 実測の要点（合成データ、2026-09-04）

- 棚卸し: v0 再現率 0.61 → v2 1.00、適合率 0.99（N=5）。初版は受信箱の先頭 40 通しか読まず、無料サービスを全部見落としていた
- 注入メール 10 変種: Model Armor HIGH 3/10、LOW_AND_ABOVE 7/10（良性 12/71 誤検知）。棚卸しエージェントは 10/10 を報告し、地図を歪めたのは 0/10
- 遺志の解釈: 12 ケース × N=5 で 59/60
- ポリシーゲート: 16/16。状態機械: 37/37。見張り計画の説明: 9/9（見張れない人に見張れないと言う、足したサービスの合図の有無を正しく言う）
- 見張りの判断: 5 筋書き（帰省・入院・失効・沈黙・注入）× N=5 で 21/21。確認者の承認経路: 8/8
- 執行: 決定的 9/9、文面 3 種 × N=3 で 9/9。発火 → 本人へ最後の通知 → 7 日のブレーキ → 票の数え直し → 執行 → 遺族へのご報告 → DONE（再執行しない）
- 外部レビュー（2026-09-06、審査員視点＋攻撃者視点）の指摘: 所有者ロック、`or 2` の迂回、FIRED の終端、監査鎖の共有、XFF 偽装、GET ログアウトの CSRF、CSP の unsafe-inline、鍵の共用、Gmail の N+1、文書の過大主張（Confidential Space・Firestore・未実装サービス）を修正。残りは `THREAT_MODEL.md` の「まだ甘いところ」
- 数字はすべて `ARCHITECTURE.md` に条件つきで記載。合成データであること、棚卸しエージェントは変更ツールを持たないので「従わない」は地図の歪みまでしか測れないこと、を含む
