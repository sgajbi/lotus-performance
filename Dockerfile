FROM python:3.11-slim

ARG APP_VERSION=0.1.0
ARG APP_GIT_COMMIT_SHA=local
ARG APP_GIT_BRANCH=local
ARG APP_BUILD_TIMESTAMP=local
ARG APP_REPOSITORY_URL=https://github.com/sgajbi/lotus-performance
ARG APP_IMAGE_DIGEST=unavailable-before-push
ARG APP_CI_PIPELINE_RUN_ID=local

LABEL org.opencontainers.image.title="lotus-performance" \
      org.opencontainers.image.description="Portfolio Performance Analytics API" \
      org.opencontainers.image.source="${APP_REPOSITORY_URL}" \
      org.opencontainers.image.revision="${APP_GIT_COMMIT_SHA}" \
      org.opencontainers.image.ref.name="${APP_GIT_BRANCH}" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.created="${APP_BUILD_TIMESTAMP}" \
      lotus.image.digest="${APP_IMAGE_DIGEST}" \
      lotus.ci.pipeline_run_id="${APP_CI_PIPELINE_RUN_ID}"

ENV APP_VERSION="${APP_VERSION}" \
    APP_GIT_COMMIT_SHA="${APP_GIT_COMMIT_SHA}" \
    APP_GIT_BRANCH="${APP_GIT_BRANCH}" \
    APP_BUILD_TIMESTAMP="${APP_BUILD_TIMESTAMP}" \
    APP_REPOSITORY_URL="${APP_REPOSITORY_URL}" \
    APP_IMAGE_DIGEST="${APP_IMAGE_DIGEST}" \
    APP_CI_PIPELINE_RUN_ID="${APP_CI_PIPELINE_RUN_ID}"

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir --root-user-action=ignore --upgrade pip && \
    pip install --no-cache-dir --root-user-action=ignore -r requirements.txt -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
