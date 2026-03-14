from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.services.compute_job_store import ComputeJobStatus, compute_job_store
from app.services.lineage_metadata_store import LineagePayloadModel, LineageRecordModel, lineage_metadata_store
from main import app


def test_runtime_work_items_reports_active_compute_and_lineage_items():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)

    compute_pending_id = uuid4()
    compute_leased_id = uuid4()
    lineage_pending_id = uuid4()
    lineage_leased_id = uuid4()

    for calculation_id in [compute_pending_id, compute_leased_id]:
        compute_job_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
            max_attempts=3,
        )

    with compute_job_store._session() as session:
        pending_row = compute_job_store._get_model(session, compute_pending_id)
        pending_row.created_at_utc = now - timedelta(seconds=120)
        leased_row = compute_job_store._get_model(session, compute_leased_id)
        leased_row.job_status = ComputeJobStatus.LEASED.value
        leased_row.leased_at_utc = now - timedelta(seconds=90)

    for calculation_id in [lineage_pending_id, lineage_leased_id]:
        lineage_metadata_store.enqueue_lineage_payload(
            calculation_id=calculation_id,
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"details.json": "{}"},
        )

    with lineage_metadata_store._session() as session:
        pending_payload = session.get(LineagePayloadModel, str(lineage_pending_id))
        leased_payload = session.get(LineagePayloadModel, str(lineage_leased_id))
        assert pending_payload is not None
        assert leased_payload is not None
        pending_payload.created_at_utc = now - timedelta(seconds=110)
        leased_payload.created_at_utc = now - timedelta(seconds=50)
        leased_payload.leased_at_utc = now - timedelta(seconds=80)
        leased_payload.lease_expires_at_utc = now + timedelta(seconds=60)

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-work-items", params={"status": "active", "limit": 10})

        assert response.status_code == 200
        body = response.json()
        assert body["contract_version"] == "v1"
        assert body["status_filter"] == "active"
        assert body["limit"] == 10
        assert body["durable_metadata_store"]["status"] == "ready"
        assert body["compute_queue"]["status"] == "available"
        assert body["lineage_queue"]["status"] == "available"
        assert [item["calculation_id"] for item in body["compute_items"]] == [
            str(compute_pending_id),
            str(compute_leased_id),
        ]
        assert body["compute_items"][0]["status"] == "pending"
        assert body["compute_items"][1]["status"] == "leased"
        assert [item["calculation_id"] for item in body["lineage_items"]] == [
            str(lineage_pending_id),
            str(lineage_leased_id),
        ]
        assert body["lineage_items"][0]["status"] == "pending"
        assert body["lineage_items"][1]["status"] == "leased"
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_work_items_reports_failed_compute_and_lineage_items():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)

    compute_failed_id = uuid4()
    lineage_failed_id = uuid4()

    compute_job_store.enqueue_job(
        calculation_id=compute_failed_id,
        analytics_type="Contribution",
        request_payload={"portfolio_id": "PF-FAIL"},
        max_attempts=2,
    )
    with compute_job_store._session() as session:
        failed_row = compute_job_store._get_model(session, compute_failed_id)
        failed_row.job_status = ComputeJobStatus.FAILED.value
        failed_row.completed_at_utc = now - timedelta(seconds=20)
        failed_row.error_type = "RuntimeError"
        failed_row.error_message = "compute failed"

    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=lineage_failed_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )
    lineage_metadata_store.mark_failed(lineage_failed_id, error_message="lineage failed")
    with lineage_metadata_store._session() as session:
        failed_record = session.get(LineageRecordModel, str(lineage_failed_id))
        assert failed_record is not None
        failed_record.timestamp_utc = now - timedelta(seconds=15)

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-work-items", params={"status": "failed", "limit": 10})

        assert response.status_code == 200
        body = response.json()
        assert body["status_filter"] == "failed"
        assert body["compute_queue"]["status"] == "available"
        assert body["lineage_queue"]["status"] == "available"
        assert len(body["compute_items"]) == 1
        assert body["compute_items"][0]["calculation_id"] == str(compute_failed_id)
        assert body["compute_items"][0]["status"] == "failed"
        assert body["compute_items"][0]["error_type"] == "RuntimeError"
        assert body["compute_items"][0]["error_message"] == "compute failed"
        assert len(body["lineage_items"]) == 1
        assert body["lineage_items"][0]["calculation_id"] == str(lineage_failed_id)
        assert body["lineage_items"][0]["status"] == "failed"
        assert body["lineage_items"][0]["error_message"] == "lineage failed"
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_work_items_reports_partial_queue_unavailability(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        side_effect=RuntimeError("compute unavailable"),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        return_value=[],
    )

    with TestClient(app) as client:
        response = client.get("/integration/runtime-work-items", params={"status": "active", "limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["durable_metadata_store"]["status"] == "ready"
    assert body["compute_queue"] == {"status": "unavailable", "reason": "RuntimeError"}
    assert body["lineage_queue"] == {"status": "available"}
    assert body["compute_items"] == []
    assert body["lineage_items"] == []
