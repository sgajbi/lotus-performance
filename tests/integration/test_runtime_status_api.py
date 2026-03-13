from uuid import uuid4

from fastapi.testclient import TestClient

from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import lineage_metadata_store
from main import app


def test_runtime_status_reports_durable_queue_state():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()

    compute_job_store.enqueue_job(
        calculation_id=uuid4(),
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-001"},
    )
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=uuid4(),
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request_payload.json": "request.json"},
    )

    with TestClient(app) as client:
        response = client.get("/integration/runtime-status")

    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["source_service"] == "lotus-performance"
    assert body["runtime_status"] == "ready"
    assert body["draining"] is False
    assert body["durable_metadata_store"]["status"] == "ready"
    assert body["compute_queue"]["status"] == "available"
    assert body["compute_queue"]["pending_jobs"] == 1
    assert body["lineage_queue"]["status"] == "available"
    assert body["lineage_queue"]["pending_payloads"] == 1


def test_runtime_status_reports_draining_state():
    with TestClient(app) as client:
        app.state.is_draining = True
        response = client.get("/integration/runtime-status")
    app.state.is_draining = False

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_status"] == "draining"
    assert body["draining"] is True


def test_runtime_status_reports_unavailable_durable_store(mocker):
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/integration/runtime-status")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_status"] == "unavailable"
    assert body["durable_metadata_store"] == {
        "status": "unavailable",
        "reason": "durable_metadata_store_unreachable",
    }
    assert body["compute_queue"]["status"] == "unavailable"
    assert "pending_jobs" not in body["compute_queue"]
    assert body["lineage_queue"]["status"] == "unavailable"
