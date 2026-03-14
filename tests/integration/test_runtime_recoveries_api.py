from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.services.compute_job_store import compute_job_store
from app.services.lineage_metadata_store import lineage_metadata_store
from main import app


def test_runtime_recoveries_returns_filtered_events():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)
    compute_id = uuid4()
    lineage_id = uuid4()

    compute_job_store.enqueue_job(
        calculation_id=compute_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-1"},
    )
    with compute_job_store._session() as session:
        row = compute_job_store._get_model(session, compute_id)
        row.attempt_count = 1
        row.last_error_at_utc = now - timedelta(seconds=5)

    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=lineage_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )
    lineage_metadata_store.increment_attempt_count(lineage_id)
    lineage_metadata_store.mark_pending(lineage_id)

    try:
        with TestClient(app) as client:
            response = client.get(
                "/integration/runtime-recoveries",
                params={
                    "queue": "both",
                    "limit": 1,
                    "compute_analytics_type": "ReturnsSeries",
                    "lineage_calculation_type": "TWR",
                    "recovered_after": (now - timedelta(seconds=30)).isoformat(),
                    "recovered_before": (now + timedelta(seconds=5)).isoformat(),
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["queue_filter"] == "both"
        assert body["compute_queue"]["total_count"] == 1
        assert body["lineage_queue"]["total_count"] == 1
        assert "next_offset" not in body["compute_queue"]
        assert "next_offset" not in body["lineage_queue"]
        assert body["recovered_after"] is not None
        assert body["recovered_before"] is not None
        assert body["compute_recoveries"][0]["calculation_id"] == str(compute_id)
        assert body["compute_recoveries"][0]["execution_path"] == f"/performance/executions/{compute_id}"
        assert body["compute_recoveries"][0]["lineage_path"] == f"/performance/lineage/{compute_id}"
        assert body["compute_recoveries"][0]["result_path"] == f"/integration/returns/series/results/{compute_id}"
        assert body["lineage_recoveries"][0]["calculation_id"] == str(lineage_id)
        assert body["lineage_recoveries"][0]["execution_path"] == f"/performance/executions/{lineage_id}"
        assert body["lineage_recoveries"][0]["lineage_path"] == f"/performance/lineage/{lineage_id}"
        assert "result_path" not in body["lineage_recoveries"][0]
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_recoveries_returns_next_offset_for_additional_matching_events():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)
    compute_ids = [uuid4(), uuid4()]

    for seconds_ago, calculation_id in zip([20, 10], compute_ids, strict=True):
        compute_job_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
        )
        with compute_job_store._session() as session:
            row = compute_job_store._get_model(session, calculation_id)
            row.attempt_count = 1
            row.last_error_at_utc = now - timedelta(seconds=seconds_ago)

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-recoveries", params={"queue": "compute", "limit": 1})

        assert response.status_code == 200
        body = response.json()
        assert body["compute_queue"]["total_count"] == 2
        assert body["compute_queue"]["returned_count"] == 1
        assert body["compute_queue"]["next_offset"] == 1
        assert body["lineage_queue"]["status"] == "excluded"
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()
