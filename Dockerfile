FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir google-adk==2.7.1 google-genai==2.19.0 google-auth-oauthlib==1.4.1 google-api-python-client==2.200.0 pydantic==2.13.4 \
 && useradd -r -u 10001 -d /app app
COPY --chown=app:app agents ./agents
COPY --chown=app:app web ./web
COPY --chown=app:app data/catalog.json data/assets.json data/will_demo.json data/inbox.json data/oauth.json data/signals.json data/truth.json data/inventory_demo_log.txt ./data/
ENV PYTHONUNBUFFERED=1 GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global ATONOKOTO_SECRETS_DIR=/tmp/secrets
USER app
CMD ["python", "web/server.py"]
