# Google Cloud Partner Top Engineer 2027 応募用の整理（あとのこと）

応募シートの「ソリューション開発」「技術情報の発信」「社内普及」の欄に、この作品をどう書くかをまとめたもの。数値は 2026-09-14 時点の実測。本文は日本語、固有名は正式名称（Google Cloud、Cloud Run、Vertex AI）で書く。

## 先に日程の注意

| 項目 | 日付 |
|---|---|
| Partner Top Engineer 2027 応募締切 | 2026-10-09 |
| ハッカソン提出締切 | 2026-10-15 |
| Partner Top Engineer 結果発表 | 2026-11-25 |
| ハッカソン最終審査 | 2026-12-01 |

応募締切がハッカソン提出より先なので、応募時点では「応募作として提出済み（審査中）」としか書けない。提出を 10/9 より前に済ませておくと、応募シートに提出済みの URL と GitHub を書ける。入賞は書けないので、書くのは「何を作り、何を測ったか」に絞る。

## 1. ソリューション開発の欄（そのまま貼れる文）

### 200 字版

Google Cloud 上で、死後のデジタル資産を本人の遺志どおりに執行する AI エージェント「あとのこと」を単独で設計・実装・配備。Vertex AI Gemini と ADK による受信箱の棚卸し、床つき状態機械による生存確認、Confidential Space と Cloud KMS による封印資格情報の保護を組み合わせ、注入耐性・最小権限・監査を実測で裏付けた。第5回 Agentic AI Hackathon with Google Cloud に応募。

### 400 字版

「あとのこと」は、人がいなくなった後にサブスクや写真、アカウントを本人の遺志どおりに止め、渡し、報告する AI エージェント。Cloud Run（サービスとジョブ）、Cloud Scheduler、Vertex AI Gemini（ADK の SequentialAgent 4 段と、読み取り専用ツールを持つ調査係）、Secret Manager、Cloud Storage、Cloud KMS、Confidential Space、Workload Identity Federation、Model Armor、Sensitive Data Protection、Cloud Logging を組み合わせた。設計の芯は「死を確定しない」で、判断の床（30/60/14/7 日）は決定的な状態機械が持ち、LLM は説明と延長提案しかできない。封印した資格情報は attestation を通った実行イメージの digest ひとつだけが KMS で復号でき、承認外イメージが 403 になるところまで本番で実測した。プロンプト注入 10 変種で追従 0/20、判断 21/21、ゲート 16/16、状態機械 37/37、配備先の検査 42/42、IAM の検査 6/6。外部レビュー（審査員・攻撃者・初見ユーザーの 3 視点）を受けて指摘を潰し、脅威モデルを公開している。

## 2. 技術実績として書ける項目（数値つき）

| 項目 | 内容 | 証拠 |
|---|---|---|
| Google Cloud サービスの組み合わせ | Cloud Run ×2、Cloud Scheduler、Vertex AI Gemini（global）、ADK、Secret Manager、Cloud Storage ×2、Cloud KMS、Confidential Space、Workload Identity Federation、Model Armor、Sensitive Data Protection、Cloud Logging、Artifact Registry、Cloud Build | `ARCHITECTURE.md`、`docs/architecture.png` |
| Confidential Space の製品組み込み | attestation → STS → KMS 復号。復号の IAM は実行イメージの digest ひとつ。WIF は STABLE（本番イメージ）のみ | `tests/infra_check.py` 6/6、両側実測（承認済みは開く、承認外は 403、Cloud Run の SA は PERMISSION_DENIED） |
| 注入耐性 | 受信箱の注入メール 10 変種 × N=2 で追従 0/20、報告 20/20。予定題名の注入で判断 0/5 追従。確認者向け文面は事実＋検閲つき見立て | `data/inj/`、`tests/watch_scenarios.py` 21/21 |
| 最小権限 | Vertex は predict だけのカスタムロール、利用者ごとの Secret Manager、監査バケットは objectCreator のみ・保持 400 日、Scheduler の起動権限はジョブ 1 つ | `infra/deploy.sh`、`THREAT_MODEL.md` |
| 決定的なゲート | ポリシーゲート 16/16、判定はハッシュ鎖で追記専用バケットへ | `agents/gate/policy.py` |
| 生存確認の源 | Gmail メタデータ、通知メール（Amazon、楽天、メルカリ、PayPay、銀行振込など 33 店）、YouTube、公開 API 12 サービス | `agents/watch/purchases.py`（本人の受信箱 365 日で宣伝混入 0） |
| マルチテナント | Google アカウントごとに置き場・トークン・確認リンクを分離。審査用アカウントを別に用意 | `web/server.py` |
| 外部レビュー | 審査員・攻撃者・初見ユーザーの 3 視点で計 57 件の指摘、致命的・重要は全件対応 | `THREAT_MODEL.md` の追記行 |

## 3. 技術情報の発信の欄

いま書けるもの:
- ハッカソン応募（Zenn のダッシュボード経由。提出後に概要が公開される）
- GitHub リポジトリ（公開にすれば URL を書ける。非公開なら「提出済み」とだけ）

10/9 までに増やせるもの（優先順）:
1. Zenn 記事 1 本「Confidential Space で LLM エージェントに秘密を渡す: attestation と KMS の digest 縛りを本番で通した記録」。承認済み・承認外の両側の実測ログをそのまま載せる。PV を後で記入するので、応募直前ではなく 9 月中に出す。
2. Zenn 記事 1 本「エージェントの判断を LLM に渡さない設計: 床つき状態機械と検閲つき説明」。注入 10 変種の結果表と、確認者向け文面の二部構成。
3. ハッカソンの Zenn 記事（任意提出、Idea カテゴリ）。作品の背景と設計判断。提出締切後に公開でもよいが、応募シートに URL を書くなら 10/9 前。

記事は「Google Cloud」と正式名称で書き、リリース日は書かない。PV は応募シートに記入する。

## 4. 社内普及の欄

この作品を社内で使う形:
- 勉強会「エージェントに秘密を持たせない: Confidential Space と KMS の digest 縛り」（60 分）。デモは本番の「本物の enclave で開ける」ボタンで 5 分。
- 勉強会「LLM を判断から外す設計: 床つき状態機械と注入 10 変種の実測」（45 分）。`tests/watch_scenarios.py` をその場で回す。
- 脅威モデルのテンプレート化。`THREAT_MODEL.md` の「資産／攻撃者／対策と証拠（実測・実装・設計のみ・未対応）」の 4 段階表記を、社内のエージェント案件のレビュー様式として提案する。

クライアント適用の視点（コンサルとして書くなら）:
- 金融・保険の「顧客の死後手続き」や、企業の「退職者アカウントの棚卸しと権限剥奪」に同じ骨格（棚卸し → 遺志の塗り分け → 決定的ゲート → 監査）が使える。
- Confidential Space は、エージェントに顧客の資格情報を扱わせる案件の答えになる。復号を実行イメージの digest に縛る構成は、そのまま監査対応の説明になる。

## 5. リンクと数値の一覧（応募シートに転記）

- デプロイ URL: https://atonokoto-web-52kgcfrghq-an.a.run.app/web/index.html
- GitHub: （push 後に記入）
- アーキテクチャ図: `docs/architecture.png`
- 脅威モデル: `THREAT_MODEL.md`
- 実測: 注入 0/20 追従、判断 21/21、ゲート 16/16、状態機械 37/37、承認 9/9、送信 7/7、買い物判定 38/38、配備先 42/42、IAM 6/6、遺志の解釈 59/60
- 費用: 予算アラート 3,000 円/月、Cloud Run は max-instances 1、enclave VM は毎回削除

## 6. 応募前にやること

- [ ] ハッカソンを 10/9 より前に提出（GitHub 連携、動画、ID/PW 転記）
- [ ] GitHub を公開にするか決める（公開なら応募シートに URL）
- [ ] Zenn 記事 1（Confidential Space）を 9 月中に公開
- [ ] Zenn 記事 2（状態機械と注入）を 10 月第 1 週に公開
- [ ] 記事の PV を応募直前に記入
- [ ] 資格の有効期限を 2026-09-30 時点で確認（2027 年度の要件）
- [ ] 応募方式（複数領域型か、AI 特化型か）を決める。この作品は AI とセキュリティの両方に効くので、他の実績の分布で決める
