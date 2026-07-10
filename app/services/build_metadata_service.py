from __future__ import annotations

from app.core.config import Settings
from app.models.platform_surfaces import BuildMetadataResponse


def build_runtime_metadata(settings: Settings) -> BuildMetadataResponse:
    """Project support-safe build identity from runtime settings."""
    return BuildMetadataResponse(
        service_name=settings.APP_NAME,
        service_version=settings.APP_VERSION,
        git_commit_sha=settings.APP_GIT_COMMIT_SHA,
        git_branch=settings.APP_GIT_BRANCH,
        build_timestamp=settings.APP_BUILD_TIMESTAMP,
        repository_url=settings.APP_REPOSITORY_URL,
        image_digest=settings.APP_IMAGE_DIGEST,
        ci_pipeline_run_id=settings.APP_CI_PIPELINE_RUN_ID,
    )
