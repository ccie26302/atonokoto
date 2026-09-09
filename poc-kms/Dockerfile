FROM python:3.12-slim
ARG BUILD_MARK=A
ENV BUILD_MARK=${BUILD_MARK}
COPY workload.py /workload.py
LABEL "tee.launch_policy.allow_env_override"="PROJECT_NUMBER,PROJECT_ID,POOL,PROVIDER,SEALED_SECRET,KEY"
LABEL "tee.launch_policy.log_redirect"="always"
ENTRYPOINT ["python3","/workload.py"]
