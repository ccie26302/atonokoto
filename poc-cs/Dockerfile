FROM python:3.12-slim
ARG BUILD_MARK=A
ENV BUILD_MARK=${BUILD_MARK}
COPY workload.py /workload.py
LABEL "tee.launch_policy.allow_env_override"="PROJECT_NUMBER,POOL,PROVIDER,SECRET"
LABEL "tee.launch_policy.log_redirect"="always"
ENTRYPOINT ["python3","/workload.py"]
