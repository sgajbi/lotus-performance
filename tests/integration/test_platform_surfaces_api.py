from fastapi.testclient import TestClient

from main import app


def test_version_endpoint_exposes_support_safe_build_identity() -> None:
    with TestClient(app) as client:
        response = client.get("/version")

    assert response.status_code == 200
    body = response.json()
    assert body["service_name"] == "Portfolio Performance Analytics API"
    assert body["service_version"] == "0.1.0"
    assert body["git_commit_sha"]
    assert body["git_branch"]
    assert body["build_timestamp"]
    assert body["repository_url"] == "https://github.com/sgajbi/lotus-performance"
    assert body["image_digest"]
    assert body["ci_pipeline_run_id"]


def test_root_response_includes_same_build_identity_as_version_endpoint() -> None:
    with TestClient(app) as client:
        root_response = client.get("/")
        version_response = client.get("/version")

    assert root_response.status_code == 200
    assert version_response.status_code == 200
    root_body = root_response.json()
    assert root_body["message"].startswith("Welcome to the Portfolio Performance Analytics API")
    assert root_body["build"] == version_response.json()
