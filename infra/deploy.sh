#!/usr/bin/env bash
# Cloud Run に載せる。サービス（web）とジョブ（見張り）を同じイメージから作り、Scheduler が毎朝ジョブを叩く。
# 状態は GCS バケットをボリュームで /app/data に、秘密は Secret Manager を /app/secrets に読み取り専用でマウントする。
set -euo pipefail
PROJECT=${PROJECT:-forward-vector-470012-n8}
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
REGION=${REGION:-asia-northeast1}
SA=atonokoto-run@$PROJECT.iam.gserviceaccount.com
BUCKET=gs://atonokoto-data-$PROJECT
IMAGE=$REGION-docker.pkg.dev/$PROJECT/atonokoto/app:latest
cd "$(dirname "$0")/.."

gcloud services enable run.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com modelarmor.googleapis.com dlp.googleapis.com youtube.googleapis.com --project $PROJECT
gcloud artifacts repositories describe atonokoto --location=$REGION --project $PROJECT >/dev/null 2>&1 || gcloud artifacts repositories create atonokoto --repository-format=docker --location=$REGION --project $PROJECT
gcloud iam service-accounts describe $SA --project $PROJECT >/dev/null 2>&1 || gcloud iam service-accounts create atonokoto-run --display-name="atonokoto (Cloud Run)" --project $PROJECT
gcloud storage buckets describe $BUCKET >/dev/null 2>&1 || gcloud storage buckets create $BUCKET --location=$REGION --uniform-bucket-level-access --project $PROJECT
# 最小権限: バケット読み書き、Vertex AI 利用、指定シークレットの読み取りだけ
gcloud storage buckets add-iam-policy-binding $BUCKET --member=serviceAccount:$SA --role=roles/storage.objectUser >/dev/null
# 追記専用の監査バケット: 保持 400 日、SA は objectCreator だけ（削除も上書きもできない）
AUDITB=gs://atonokoto-audit-files-$PROJECT
gcloud storage buckets describe $AUDITB >/dev/null 2>&1 || gcloud storage buckets create $AUDITB --location=$REGION --uniform-bucket-level-access --retention-period=400d --project $PROJECT
gcloud storage buckets add-iam-policy-binding $AUDITB --member=serviceAccount:$SA --role=roles/storage.objectCreator >/dev/null
# Vertex は predict だけ（カスタムロール）。aiplatform.user は広すぎる
gcloud iam roles describe atonokotoVertexPredict --project $PROJECT >/dev/null 2>&1 || gcloud iam roles create atonokotoVertexPredict --project $PROJECT --title="atonokoto: Vertex predict only" --permissions=aiplatform.endpoints.predict --stage=GA
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=projects/$PROJECT/roles/atonokotoVertexPredict --condition=None >/dev/null
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/modelarmor.user --condition=None >/dev/null
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/dlp.user --condition=None >/dev/null
[ -f secrets/session_key ] || { python3 -c "import secrets;print(secrets.token_hex(32))" > secrets/session_key; chmod 600 secrets/session_key; }
for s in client_secret client_secret_web token_watch confirm_key session_key; do
  f=secrets/$s.json; { [ "$s" = confirm_key ] || [ "$s" = session_key ]; } && f=secrets/$s
  [ -f "$f" ] || { echo "skip $s (no $f)"; continue; }
  gcloud secrets describe atonokoto-$s --project $PROJECT >/dev/null 2>&1 || gcloud secrets create atonokoto-$s --replication-policy=automatic --project $PROJECT
  gcloud secrets versions add atonokoto-$s --data-file="$f" --project $PROJECT >/dev/null
  gcloud secrets add-iam-policy-binding atonokoto-$s --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor --project $PROJECT >/dev/null
done
# 棚卸しトークンの入れ物（未ログイン = 空）。サービスはトークンを新バージョンとして書けるようにする
gcloud secrets describe atonokoto-token_inventory --project $PROJECT >/dev/null 2>&1 || { gcloud secrets create atonokoto-token_inventory --replication-policy=automatic --project $PROJECT; printf '{}' | gcloud secrets versions add atonokoto-token_inventory --data-file=- --project $PROJECT >/dev/null; }
for s in token_watch token_inventory; do
  gcloud secrets add-iam-policy-binding atonokoto-$s --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor --project $PROJECT >/dev/null
  gcloud secrets add-iam-policy-binding atonokoto-$s --member=serviceAccount:$SA --role=roles/secretmanager.secretVersionAdder --project $PROJECT >/dev/null
done
# 利用者ごとのトークン秘密（atonokoto-u-<id>-watch / -inventory）を作って読める最小の権限
gcloud iam roles describe atonokotoUserSecrets --project $PROJECT >/dev/null 2>&1 || gcloud iam roles create atonokotoUserSecrets --project $PROJECT --title="atonokoto: per-user token secrets" \
  --permissions=secretmanager.secrets.create,secretmanager.secrets.get,secretmanager.versions.add,secretmanager.versions.access,secretmanager.versions.list,secretmanager.versions.disable --stage=GA
# 条件: 利用者の秘密（atonokoto-u-*）と、secrets.create のために Project 型だけ。
# 以前の「resource.type != Secret」は SecretVersion（型が違う）を全部通してしまい、全秘密が読めた（2026-09-09 の外部レビューで発覚）。無条件のフォールバックも置かない
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=projects/$PROJECT/roles/atonokotoUserSecrets --condition="expression=resource.name.startsWith(\"projects/$PROJECT_NUMBER/secrets/atonokoto-u-\") || resource.type == \"cloudresourcemanager.googleapis.com/Project\",title=atonokoto-user-secrets-only" >/dev/null
# Confidential Space の WIF: 本番イメージ（STABLE、dbgstat=disabled-since-boot）だけ。デバッグ版は SSH で中に入れるので弾く。
# 起動元プロジェクトも縛る（同じ digest のイメージを他プロジェクトの Confidential Space で起動しても同じ principal になるため。2026-09-19 の記事査読で発覚）
gcloud iam workload-identity-pools providers update-oidc cs-provider --workload-identity-pool cs-pool --location global --project $PROJECT \
  --attribute-condition="assertion.swname == 'CONFIDENTIAL_SPACE' && 'STABLE' in assertion.submods.confidential_space.support_attributes && assertion.dbgstat == 'disabled-since-boot' && assertion.submods.gce.project_id == '$PROJECT'" >/dev/null 2>&1 || true
# 初期データをバケットへ（無ければ）
gcloud storage cp data/catalog.json data/assets.json data/will_demo.json data/inbox.json data/oauth.json data/signals.json data/truth.json data/inventory_demo_log.txt $BUCKET/ 2>/dev/null || true

gcloud builds submit --tag $IMAGE --project $PROJECT --quiet .
if gcloud run services describe atonokoto-web --region $REGION --project $PROJECT --format='value(status.conditions[0].status)' 2>/dev/null | grep -q False; then
  gcloud run services delete atonokoto-web --region $REGION --project $PROJECT --quiet || true
fi
# 秘密は環境変数で受け取り、起動時にコンテナ内へ書く（google_auth._materialize_from_env）。ファイルマウントは 1 ディレクトリ 1 シークレットの制約があるため
# サービスは web 用クライアント（run.app へのリダイレクト）。ジョブはログインしないので同じでよい
SECRET_ENVS="ATONOKOTO_CLIENT_SECRET_JSON=atonokoto-client_secret_web:latest,ATONOKOTO_TOKEN_WATCH_JSON=atonokoto-token_watch:latest,ATONOKOTO_TOKEN_INVENTORY_JSON=atonokoto-token_inventory:latest,ATONOKOTO_CONFIRM_KEY=atonokoto-confirm_key:latest,ATONOKOTO_SESSION_KEY=atonokoto-session_key:latest"
# 審査用アカウント（ID/パスワード）は secrets/judge.json があれば登録
if [ -f secrets/judge.json ]; then
  gcloud secrets describe atonokoto-judge --project $PROJECT >/dev/null 2>&1 || gcloud secrets create atonokoto-judge --replication-policy=automatic --project $PROJECT
  gcloud secrets versions add atonokoto-judge --data-file=secrets/judge.json --project $PROJECT >/dev/null
  gcloud secrets add-iam-policy-binding atonokoto-judge --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor --project $PROJECT >/dev/null
  SECRET_ENVS="$SECRET_ENVS,ATONOKOTO_JUDGE_JSON=atonokoto-judge:latest"
fi
# 送信元（SMTP）は secrets/smtp.json があれば登録。無ければ送らず outbox に残る
if [ -f secrets/smtp.json ]; then
  gcloud secrets describe atonokoto-smtp --project $PROJECT >/dev/null 2>&1 || gcloud secrets create atonokoto-smtp --replication-policy=automatic --project $PROJECT
  gcloud secrets versions add atonokoto-smtp --data-file=secrets/smtp.json --project $PROJECT >/dev/null
  gcloud secrets add-iam-policy-binding atonokoto-smtp --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor --project $PROJECT >/dev/null
  SECRET_ENVS="$SECRET_ENVS,ATONOKOTO_SMTP_JSON=atonokoto-smtp:latest"
fi
gcloud run deploy atonokoto-web --image $IMAGE --region $REGION --project $PROJECT --service-account $SA --allow-unauthenticated \
  --memory 1Gi --cpu 2 --min-instances 0 --max-instances 1 --concurrency 20 --timeout 900 \
  --add-volume name=data,type=cloud-storage,bucket=${BUCKET#gs://} --add-volume-mount volume=data,mount-path=/app/data \
  --set-secrets "$SECRET_ENVS" \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global,ATONOKOTO_SECRETS_DIR=/tmp/secrets,ATONOKOTO_AUDIT_BUCKET=atonokoto-audit-files-$PROJECT --quiet
URL=$(gcloud run services describe atonokoto-web --region $REGION --project $PROJECT --format='value(status.url)')
gcloud run services update atonokoto-web --region $REGION --project $PROJECT --update-env-vars ATONOKOTO_BASE_URL=$URL --quiet
# 見張りのジョブ
gcloud run jobs describe atonokoto-watch --region $REGION --project $PROJECT >/dev/null 2>&1 && ACTION=update || ACTION=create
gcloud run jobs $ACTION atonokoto-watch --image $IMAGE --region $REGION --project $PROJECT --service-account $SA --command python --args agents/watch/run.py \
  --add-volume name=data,type=cloud-storage,bucket=${BUCKET#gs://} --add-volume-mount volume=data,mount-path=/app/data \
  --set-secrets "$SECRET_ENVS" --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global,ATONOKOTO_BASE_URL=$URL,ATONOKOTO_SECRETS_DIR=/tmp/secrets,ATONOKOTO_AUDIT_BUCKET=atonokoto-audit-files-$PROJECT,ATONOKOTO_PROJECT_NUMBER=$PROJECT_NUMBER --max-retries 1 --task-timeout 1200 --quiet
# 毎朝 6:30 JST
gcloud run jobs add-iam-policy-binding atonokoto-watch --region $REGION --project $PROJECT --member=serviceAccount:$SA --role=roles/run.invoker >/dev/null
gcloud scheduler jobs describe atonokoto-watch-daily --location $REGION --project $PROJECT >/dev/null 2>&1 && SACT=update || SACT=create
gcloud scheduler jobs $SACT http atonokoto-watch-daily --location $REGION --project $PROJECT --schedule "30 6 * * *" --time-zone Asia/Tokyo \
  --uri "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/atonokoto-watch:run" --http-method POST --oauth-service-account-email $SA --quiet
echo "URL: $URL"
