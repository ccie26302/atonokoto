# Confidential Space で走る執行ワークロード。同じコードだが、入口は enclave.py。
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir google-adk==2.7.1 google-genai==2.19.0 pydantic==2.13.4 \
 && useradd -r -u 10001 -d /app app
COPY --chown=app:app agents ./agents
ENV PYTHONUNBUFFERED=1 GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global
# Confidential Space の起動ポリシー: 上書きを許す環境変数を明示し、コンテナの出力を Cloud Logging へ
LABEL "tee.launch_policy.allow_env_override"="PROJECT_NUMBER,PROJECT_ID,DATA_BUCKET,ATONOKOTO_AUDIT_BUCKET,UID,ROUND,GOOGLE_CLOUD_PROJECT,KEY,POOL,PROVIDER"
LABEL "tee.launch_policy.log_redirect"="always"
USER app
CMD ["python", "agents/execute/enclave.py"]
