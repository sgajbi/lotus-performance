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
        "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
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
    assert "daily_results.csv" in lineage_data["artifacts"]
    artifact_url = lineage_data["artifacts"]["request.json"]["url"]
    artifact_response = client.get(artifact_url)
    assert artifact_response.status_code == 200
    assert '"portfolio_id": "LINEAGE_TEST"' in artifact_response.text


def test_stateful_twr_lineage_captures_resolved_request(client, monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-01-15",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "STATEFUL_LINEAGE_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    calculation_id = response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200

    request_artifact_url = lineage_response.json()["artifacts"]["request.json"]["url"]
    artifact_response = client.get(request_artifact_url)

    assert artifact_response.status_code == 200
    assert '"performance_start_date": "2024-01-15"' in artifact_response.text
    assert '"valuation_points"' in artifact_response.text
    assert '"stateful_input"' not in artifact_response.text


def test_twr_benchmark_lineage_captures_resolved_portfolio_and_benchmark_request(client):
    payload = {
        "portfolio_id": "LINEAGE_TWR_BENCHMARK",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "benchmark": {
            "benchmark_id": "BMK_LINEAGE_1",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-01-02", "weight_bop": 1.0, "component_return": 0.015},
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    calculation_id = response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200

    request_artifact_url = lineage_response.json()["artifacts"]["request.json"]["url"]
    artifact_response = client.get(request_artifact_url)

    assert artifact_response.status_code == 200
    assert '"portfolio"' in artifact_response.text
    assert '"benchmark"' in artifact_response.text
    assert '"benchmark_id": "BMK_LINEAGE_1"' in artifact_response.text
    assert '"benchmark_start_date": "2025-01-01"' in artifact_response.text


def test_benchmark_price_point_lineage_captures_resolved_request(client):
    payload = {
        "benchmark_id": "BMK_LINEAGE_PRICE_1",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_price_points": [
                {"component_id": "IDX_A", "perf_date": "2026-01-01", "weight_bop": 1.0, "index_price": 100.0},
                {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 1.0, "index_price": 101.0},
            ],
        },
    }

    response = client.post("/performance/benchmark", json=payload)
    assert response.status_code == 200
    calculation_id = response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200

    request_artifact_url = lineage_response.json()["artifacts"]["request.json"]["url"]
    artifact_response = client.get(request_artifact_url)

    assert artifact_response.status_code == 200
    assert '"component_observations"' in artifact_response.text
    assert '"component_price_points"' not in artifact_response.text


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
