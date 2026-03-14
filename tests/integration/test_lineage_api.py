# tests/integration/test_lineage_api.py
import os
import shutil
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.lineage_metadata_store import lineage_metadata_store
from main import app
from tests.conftest import drain_lineage_queue

settings = get_settings()


@pytest.fixture(scope="module")
def client():
    # Clean up lineage directory before tests
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    os.makedirs(settings.LINEAGE_STORAGE_PATH)
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()

    with TestClient(app) as c:
        yield c

    # Clean up after tests
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    lineage_metadata_store.clear_all_records()


def test_lineage_end_to_end_flow(client):
    """Tests the full lineage flow: TWR calc -> lineage capture -> lineage retrieval."""
    twr_payload = {
        "portfolio_id": "LINEAGE_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }

    # 1. Run a calculation
    twr_response = client.post("/performance/twr", json=twr_payload)
    assert twr_response.status_code == 200
    twr_data = twr_response.json()
    calculation_id = twr_data["calculation_id"]
    assert drain_lineage_queue() >= 1

    # 2. Retrieve lineage data
    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()

    assert lineage_data["calculation_id"] == calculation_id
    assert lineage_data["calculation_type"] == "TWR"
    assert lineage_data["status"] == "complete"
    assert "Z" in lineage_data["timestamp_utc"]
    assert "request.json" in lineage_data["artifacts"]
    assert "response.json" in lineage_data["artifacts"]
    assert "twr_calculation_details.csv" in lineage_data["artifacts"]
    artifact_url = lineage_data["artifacts"]["request.json"]["url"]
    artifact_response = client.get(artifact_url)
    assert artifact_response.status_code == 200
    assert '"portfolio_id": "LINEAGE_TEST"' in artifact_response.text


def test_get_lineage_data_not_found(client):
    """Tests that a 404 is returned for a non-existent calculation_id."""
    non_existent_id = uuid4()
    response = client.get(f"/performance/lineage/{non_existent_id}")
    assert response.status_code == 404


def test_get_lineage_manifest_not_found(client):
    """Tests that a 404 is returned when lineage dir exists but manifest is missing."""
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(calculation_id=calculation_id, artifact_names=["request.json"])
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)

    response = client.get(f"/performance/lineage/{calculation_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Lineage manifest not found."


def test_get_lineage_internal_error_returns_500(client, mocker):
    """Tests that unexpected lineage retrieval failures map to HTTP 500."""
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(calculation_id=calculation_id, artifact_names=["request.json"])
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)

    manifest_path = os.path.join(lineage_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        f.write('{"calculation_type":"TWR","timestamp_utc":"2026-01-01T00:00:00Z"}')

    mocker.patch("app.api.endpoints.lineage.json.load", side_effect=Exception("manifest parse failure"))
    response = client.get(f"/performance/lineage/{calculation_id}")
    assert response.status_code == 500
    assert "Failed to retrieve lineage artifacts" in response.json()["detail"]


def test_get_lineage_invalid_manifest_returns_503(client):
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(calculation_id=calculation_id, artifact_names=["request.json"])
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)

    manifest_path = os.path.join(lineage_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("{not-json")

    response = client.get(f"/performance/lineage/{calculation_id}")
    assert response.status_code == 503
    assert response.json()["detail"] == "Lineage manifest is invalid."


def test_get_lineage_inconsistent_manifest_returns_503(client):
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(
        calculation_id=calculation_id,
        artifact_names=["request.json", "response.json"],
    )
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)

    manifest_path = os.path.join(lineage_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json_manifest = (
            '{"calculation_type":"TWR","timestamp_utc":"2026-01-01T00:00:00Z",'
            '"status":"complete","artifact_names":["request.json"]}'
        )
        f.write(json_manifest)

    response = client.get(f"/performance/lineage/{calculation_id}")

    assert response.status_code == 503
    assert response.json()["detail"] == "Lineage manifest is inconsistent with durable metadata."


def test_get_lineage_returns_503_when_declared_artifact_missing_from_storage(client):
    calculation_id = uuid4()
    completion_timestamp = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(
        calculation_id=calculation_id,
        artifact_names=["request.json", "response.json"],
        timestamp_utc=completion_timestamp,
    )
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)
    with open(os.path.join(lineage_dir, "manifest.json"), "w", encoding="utf-8") as f:
        f.write(
            '{"calculation_type":"TWR","timestamp_utc":"2026-03-14T12:00:00Z",'
            '"status":"complete","artifact_names":["request.json","response.json"]}'
        )
    with open(os.path.join(lineage_dir, "request.json"), "w", encoding="utf-8") as f:
        f.write("{}")

    response = client.get(f"/performance/lineage/{calculation_id}")

    assert response.status_code == 503
    assert response.json()["detail"] == "Lineage artifacts are incomplete in storage."


def test_get_lineage_pending_returns_pending_status(client):
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")

    response = client.get(f"/performance/lineage/{calculation_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["artifacts"] == {}


def test_get_lineage_failed_returns_failed_status(client):
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_failed(calculation_id=calculation_id, error_message="write failed")

    response = client.get(f"/performance/lineage/{calculation_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_message"] == "write failed"


def test_get_lineage_artifact_not_found_for_unknown_artifact(client):
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(calculation_id=calculation_id, artifact_names=["request.json"])
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)
    with open(os.path.join(lineage_dir, "manifest.json"), "w") as f:
        f.write('{"calculation_type":"TWR","timestamp_utc":"2026-01-01T00:00:00Z"}')
    with open(os.path.join(lineage_dir, "request.json"), "w") as f:
        f.write("{}")

    response = client.get(f"/performance/lineage/{calculation_id}/artifacts/unknown.json")

    assert response.status_code == 404


def test_get_lineage_artifact_returns_503_when_manifest_missing(client):
    calculation_id = uuid4()
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(calculation_id=calculation_id, artifact_names=["request.json"])
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)
    with open(os.path.join(lineage_dir, "request.json"), "w", encoding="utf-8") as f:
        f.write("{}")

    response = client.get(f"/performance/lineage/{calculation_id}/artifacts/request.json")

    assert response.status_code == 503
    assert response.json()["detail"] == "Lineage manifest not found."


def test_get_lineage_artifact_returns_503_when_manifest_is_inconsistent(client):
    calculation_id = uuid4()
    completion_timestamp = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(
        calculation_id=calculation_id,
        artifact_names=["request.json"],
        timestamp_utc=completion_timestamp,
    )
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)
    with open(os.path.join(lineage_dir, "request.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    with open(os.path.join(lineage_dir, "manifest.json"), "w", encoding="utf-8") as f:
        f.write(
            '{"calculation_type":"TWR","timestamp_utc":"2026-03-14T12:00:00Z",'
            '"status":"complete","artifact_names":["response.json"]}'
        )

    response = client.get(f"/performance/lineage/{calculation_id}/artifacts/request.json")

    assert response.status_code == 503
    assert response.json()["detail"] == "Lineage manifest is inconsistent with durable metadata."


def test_get_lineage_artifact_returns_503_when_file_missing_from_storage(client):
    calculation_id = uuid4()
    completion_timestamp = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    lineage_metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    lineage_metadata_store.mark_complete(
        calculation_id=calculation_id,
        artifact_names=["request.json"],
        timestamp_utc=completion_timestamp,
    )
    lineage_dir = os.path.join(settings.LINEAGE_STORAGE_PATH, str(calculation_id))
    os.makedirs(lineage_dir, exist_ok=True)
    with open(os.path.join(lineage_dir, "manifest.json"), "w", encoding="utf-8") as f:
        f.write(
            '{"calculation_type":"TWR","timestamp_utc":"2026-03-14T12:00:00Z",'
            '"status":"complete","artifact_names":["request.json"]}'
        )

    response = client.get(f"/performance/lineage/{calculation_id}/artifacts/request.json")

    assert response.status_code == 503
    assert response.json()["detail"] == "Lineage artifact is missing from storage."
