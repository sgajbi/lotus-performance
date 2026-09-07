FROM python:3.11-slim AS runtime

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
    APP_CI_PIPELINE_RUN_ID="${APP_CI_PIPELINE_RUN_ID}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
# setuptools and wheel ship with the base image and carry fixable HIGH
# advisories there (path traversal in setuptools, privilege escalation in
# wheel, path traversal in setuptools' vendored jaraco.context). They are build
# tooling rather than runtime dependencies, so they are upgraded rather than
# pinned in requirements.txt, which governs what the service imports.
#
# pip and wheel are then removed, because a runtime image has no reason to carry
# a package installer: nothing here installs packages, and one that cannot is a
# smaller target. It also removes the last HIGH findings the image reported.
# Both -- msgpack 1.1.2 and setuptools 70.3.0 -- came from pip's own vendored
# manifest at pip/_vendor/vendor.txt rather than from installed packages:
# `import setuptools` resolves to the 84.0.0 installed above, and msgpack is not
# installed at all. No dependency bump could have reached either, because they
# are declarations inside pip. Deleting the manifest would have hidden the
# finding; removing the installer removes the thing the manifest describes.
#
# setuptools stays, and is pinned. It remains importable through pkg_resources for
# libraries that still expect it, and an unpinned upgrade would resolve whatever PyPI
# serves at build time -- so the same commit could produce a different SBOM, or start
# failing this now-blocking gate, with no change in this repository to point at. pip and
# wheel need no pin because they do not survive into the image.
RUN pip install --no-cache-dir --root-user-action=ignore --upgrade pip 'setuptools==84.0.0' wheel && \
    pip install --no-cache-dir --root-user-action=ignore -r requirements.txt && \
    find /usr/local/lib/python3.11/ensurepip -name '*.whl' -delete && \
    python -m pip uninstall --yes pip wheel

RUN groupadd --system --gid 10001 lotus && \
    useradd --system --uid 10001 --gid lotus --home-dir /app --shell /usr/sbin/nologin lotus && \
    mkdir -p /app/lineage_data /app/artifacts /app/output && \
    chown -R lotus:lotus /app

COPY --chown=lotus:lotus . .

USER lotus

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
