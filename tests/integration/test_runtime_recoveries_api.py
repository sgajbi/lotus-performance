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
                    "limit": 10,
                    "compute_analytics_type": "ReturnsSeries",
                    "lineage_calculation_type": "TWR",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["queue_filter"] == "both"
        assert body["compute_queue"]["total_count"] == 1
        assert body["lineage_queue"]["total_count"] == 1
        assert body["compute_recoveries"][0]["calculation_id"] == str(compute_id)
        assert body["lineage_recoveries"][0]["calculation_id"] == str(lineage_id)
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()
