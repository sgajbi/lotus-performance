from app.core.config import Settings
from app.services.build_metadata_service import build_runtime_metadata


def test_build_runtime_metadata_projects_support_safe_release_identity() -> None:
    settings = Settings(
        APP_NAME="Performance API",
        APP_VERSION="2026.7.10",
        APP_GIT_COMMIT_SHA="0123456789abcdef",
        APP_GIT_BRANCH="main",
        APP_BUILD_TIMESTAMP="2026-07-10T07:45:00Z",
        APP_REPOSITORY_URL="https://github.com/sgajbi/lotus-performance",
        APP_IMAGE_DIGEST="sha256:release-digest",
        APP_CI_PIPELINE_RUN_ID="1234567890",
    )

    metadata = build_runtime_metadata(settings)

    assert metadata.model_dump() == {
        "service_name": "Performance API",
        "service_version": "2026.7.10",
        "git_commit_sha": "0123456789abcdef",
        "git_branch": "main",
        "build_timestamp": "2026-07-10T07:45:00Z",
        "repository_url": "https://github.com/sgajbi/lotus-performance",
        "image_digest": "sha256:release-digest",
        "ci_pipeline_run_id": "1234567890",
    }


def test_build_runtime_metadata_local_defaults_are_explicitly_non_secret() -> None:
    metadata = build_runtime_metadata(Settings())

    assert metadata.git_commit_sha == "local"
    assert metadata.git_branch == "local"
    assert metadata.build_timestamp == "local"
    assert metadata.repository_url == "https://github.com/sgajbi/lotus-performance"
    assert metadata.image_digest == "unavailable-before-push"
    assert metadata.ci_pipeline_run_id == "local"
