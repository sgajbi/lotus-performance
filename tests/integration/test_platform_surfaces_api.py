import os

import pytest
from fastapi.testclient import TestClient

from main import app


def test_version_endpoint_exposes_support_safe_build_identity() -> None:
    """Asserted against the values the build supplies, not against non-emptiness.

    Five of these were truthiness checks, and every one of them passed against a
    response carrying no build identity at all: with the build environment cleared the
    endpoint answers `git_commit_sha='local'`, `git_branch='local'`,
    `build_timestamp='local'`, `image_digest='unavailable-before-push'`. So the test
    could not have caught CI ceasing to supply the values, which is the single
    regression the field exists to prevent.

    The defaults are pinned exactly rather than loosely, so a change in what an
    unsupplied build reports is a decision someone makes here rather than a silent
    drift -- and the supplied case below proves a real value reaches the response.

    Found by the lotus-platform owner auditing this cycle: my new Compose-provenance
    tests assert against `git rev-parse HEAD`, and this older test never got the same
    treatment.
    """

    with TestClient(app) as client:
        response = client.get("/version")

    assert response.status_code == 200
    body = response.json()
    assert body["service_name"] == "Portfolio Performance Analytics API"
    assert body["service_version"] == "0.1.0"
    assert body["repository_url"] == "https://github.com/sgajbi/lotus-performance"

    # Every provenance field is a non-empty string in the response. The *values* are
    # asserted below against settings built in isolation, because a developer with
    # `APP_GIT_COMMIT_SHA` exported or a local `.env` would otherwise fail this for
    # having configured their machine -- which would be the opposite mistake to the
    # truthiness assertions this replaced, and just as unhelpful.
    for field in (
        "git_commit_sha",
        "git_branch",
        "build_timestamp",
        "ci_pipeline_run_id",
        "image_digest",
    ):
        assert isinstance(body[field], str) and body[field], f"{field} is absent or empty"


def test_an_unsupplied_build_reports_the_declared_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What a build that supplied nothing says, isolated from the developer's machine.

    Isolation takes both halves: `_env_file=None` for a local `.env`, and clearing the
    variables from the process environment, because pydantic-settings reads `os.environ`
    regardless of the file setting. Written after `_env_file=None` alone still failed
    under an exported `APP_GIT_COMMIT_SHA`.

    Without this the test would fail for a developer who has configured their machine —
    the opposite mistake to the truthiness assertions it replaced, and just as
    unhelpful, since neither tells you anything about the build.

    `local` says the build supplied nothing; `unavailable-before-push` says a digest
    cannot exist before the image does. Pinned exactly, so a change to what an
    unidentified build reports is a decision rather than a drift.
    """

    from app.core.config import Settings
    from app.services.build_metadata_service import build_runtime_metadata

    provenance_variables = {
        "APP_GIT_COMMIT_SHA",
        "APP_GIT_BRANCH",
        "APP_BUILD_TIMESTAMP",
        "APP_CI_PIPELINE_RUN_ID",
        "APP_IMAGE_DIGEST",
    }
    # Matched case-insensitively, because that is how the settings read them. On POSIX
    # `app_git_commit_sha` is a distinct key that `delenv` on the uppercase name leaves
    # in place, and pydantic-settings would still resolve it -- so the defaults this
    # test is about would silently not be the values under test.
    for name in [key for key in os.environ if key.upper() in provenance_variables]:
        monkeypatch.delenv(name, raising=False)

    metadata = build_runtime_metadata(Settings(_env_file=None))

    assert metadata.git_commit_sha == "local"
    assert metadata.git_branch == "local"
    assert metadata.build_timestamp == "local"
    assert metadata.ci_pipeline_run_id == "local"
    assert metadata.image_digest == "unavailable-before-push"


def test_a_supplied_build_identity_reaches_the_response() -> None:
    """The other half: a value CI supplies has to reach the response.

    Pinning the defaults alone would be satisfied by a surface that always reports
    them, which is the same defect one step along.

    Driven through `build_runtime_metadata` with settings rather than by setting
    environment variables around the client. `Settings` is read once at import, so an
    env var set afterwards never reaches the endpoint -- which is correct for
    production, where the container's environment is fixed before startup, and means a
    test that sets one is testing nothing. Found by writing that test first and
    watching it report `'local'`.
    """

    from app.core.config import Settings
    from app.services.build_metadata_service import build_runtime_metadata

    supplied = Settings(
        APP_GIT_COMMIT_SHA="deadbeefcafe",
        APP_GIT_BRANCH="release/probe",
        APP_IMAGE_DIGEST="sha256:probe",
    )

    metadata = build_runtime_metadata(supplied)

    assert metadata.git_commit_sha == "deadbeefcafe"
    assert metadata.git_branch == "release/probe"
    assert metadata.image_digest == "sha256:probe"


def test_root_response_includes_same_build_identity_as_version_endpoint() -> None:
    with TestClient(app) as client:
        root_response = client.get("/")
        version_response = client.get("/version")

    assert root_response.status_code == 200
    assert version_response.status_code == 200
    root_body = root_response.json()
    assert root_body["message"].startswith("Welcome to the Portfolio Performance Analytics API")
    assert root_body["build"] == version_response.json()
