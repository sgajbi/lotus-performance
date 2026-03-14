from datetime import datetime, timedelta, timezone
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
    assert body["runtime_degradation_reasons"] == []
    assert body["draining"] is False
    assert body["durable_metadata_store"]["status"] == "ready"
    assert body["compute_queue"]["status"] == "available"
    assert body["compute_queue"]["degradation_reasons"] == []
    assert body["compute_queue"]["pending_jobs"] == 1
    assert body["compute_queue"]["retry_backlog_jobs"] == 0
    assert body["compute_queue"]["lease_expired_jobs"] == 0
    assert body["compute_queue"]["terminal_failure_jobs"] == 0
    assert body["compute_queue"]["oldest_leased_age_seconds"] == 0.0
    assert body["compute_queue"]["oldest_running_age_seconds"] == 0.0
    assert body["lineage_queue"]["status"] == "available"
    assert body["lineage_queue"]["degradation_reasons"] == []
    assert body["lineage_queue"]["pending_payloads"] == 1
    assert body["lineage_queue"]["retry_backlog_payloads"] == 0
    assert body["lineage_queue"]["terminal_failure_payloads"] == 0


def test_runtime_status_reports_draining_state():
    with TestClient(app) as client:
        app.state.is_draining = True
        response = client.get("/integration/runtime-status")
    app.state.is_draining = False

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_status"] == "draining"
    assert body["runtime_degradation_reasons"] == []
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
    assert body["runtime_degradation_reasons"] == [
        "compute_queue:durable_metadata_store_unreachable",
        "lineage_queue:durable_metadata_store_unreachable",
    ]
    assert body["durable_metadata_store"] == {
        "status": "unavailable",
        "reason": "durable_metadata_store_unreachable",
    }
    assert body["compute_queue"]["status"] == "unavailable"
    assert "pending_jobs" not in body["compute_queue"]
    assert body["lineage_queue"]["status"] == "unavailable"


def test_runtime_status_reports_degraded_when_compute_age_threshold_is_exceeded():
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_threshold = settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS
    settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS = 30.0

    try:
        compute_job_store.create_schema()
        compute_job_store.clear_all_records()
        calculation_id = uuid4()
        compute_job_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": "PF-AGED"},
        )
        with compute_job_store._session() as session:
            row = compute_job_store._get_model(session, calculation_id)
            row.created_at_utc = datetime.now(timezone.utc) - timedelta(seconds=90)

        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["runtime_status"] == "degraded"
        assert body["runtime_degradation_reasons"] == ["compute_queue:compute_pending_age_exceeded"]
        assert body["compute_queue"]["status"] == "degraded"
        assert body["compute_queue"]["reason"] == "compute_pending_age_exceeded"
        assert body["compute_queue"]["degradation_reasons"] == ["compute_pending_age_exceeded"]
    finally:
        settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS = original_threshold
        compute_job_store.clear_all_records()


def test_runtime_status_exposes_compute_failure_pressure_counts():
    compute_job_store.create_schema()
    compute_job_store.clear_all_records()
    pending_retry_id = uuid4()
    failed_terminal_id = uuid4()

    compute_job_store.enqueue_job(
        calculation_id=pending_retry_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-RETRY"},
    )
    compute_job_store.enqueue_job(
        calculation_id=failed_terminal_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-FAIL"},
    )

    with compute_job_store._session() as session:
        retry_row = compute_job_store._get_model(session, pending_retry_id)
        retry_row.attempt_count = 1
        retry_row.error_type = "LeaseExpired"
        failed_row = compute_job_store._get_model(session, failed_terminal_id)
        failed_row.job_status = "failed"
        failed_row.error_type = "RuntimeError"

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["compute_queue"]["retry_backlog_jobs"] == 1
        assert body["compute_queue"]["lease_expired_jobs"] == 1
        assert body["compute_queue"]["terminal_failure_jobs"] == 1
    finally:
        compute_job_store.clear_all_records()


def test_runtime_status_exposes_lineage_failure_pressure_counts():
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()
    retry_id = uuid4()
    failed_id = uuid4()
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=retry_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request.json": "{}"},
    )
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=failed_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request.json": "{}"},
    )
    lineage_metadata_store.increment_attempt_count(retry_id)
    lineage_metadata_store.increment_attempt_count(failed_id)
    lineage_metadata_store.mark_failed(failed_id, error_message="write failed")

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["lineage_queue"]["retry_backlog_payloads"] == 1
        assert body["lineage_queue"]["terminal_failure_payloads"] == 1
    finally:
        lineage_metadata_store.clear_all_records()


def test_runtime_status_reports_degraded_when_compute_failure_threshold_is_exceeded():
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_threshold = settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT
    settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT = 1

    try:
        compute_job_store.create_schema()
        compute_job_store.clear_all_records()
        retry_id = uuid4()
        compute_job_store.enqueue_job(
            calculation_id=retry_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": "PF-RETRY-DEGRADE"},
        )
        with compute_job_store._session() as session:
            row = compute_job_store._get_model(session, retry_id)
            row.attempt_count = 1

        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["runtime_status"] == "degraded"
        assert body["runtime_degradation_reasons"] == ["compute_queue:compute_retry_backlog_exceeded"]
        assert body["compute_queue"]["status"] == "degraded"
        assert body["compute_queue"]["reason"] == "compute_retry_backlog_exceeded"
        assert body["compute_queue"]["degradation_reasons"] == ["compute_retry_backlog_exceeded"]
    finally:
        settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT = original_threshold
        compute_job_store.clear_all_records()


def test_runtime_status_reports_degraded_when_lineage_failure_threshold_is_exceeded():
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_threshold = settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT
    settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT = 1

    try:
        lineage_metadata_store.create_schema()
        lineage_metadata_store.clear_all_records()
        failed_id = uuid4()
        lineage_metadata_store.enqueue_lineage_payload(
            calculation_id=failed_id,
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"request.json": "{}"},
        )
        lineage_metadata_store.increment_attempt_count(failed_id)
        lineage_metadata_store.mark_failed(failed_id, error_message="write failed")

        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["runtime_status"] == "degraded"
        assert body["runtime_degradation_reasons"] == ["lineage_queue:lineage_terminal_failure_exceeded"]
        assert body["lineage_queue"]["status"] == "degraded"
        assert body["lineage_queue"]["reason"] == "lineage_terminal_failure_exceeded"
        assert body["lineage_queue"]["degradation_reasons"] == ["lineage_terminal_failure_exceeded"]
    finally:
        settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT = original_threshold
        lineage_metadata_store.clear_all_records()


def test_runtime_status_reports_all_active_degradation_reasons():
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    originals = (
        settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
        settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
        settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
        settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS,
        settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT,
    )
    settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS = 1.0
    settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT = 1
    settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT = 1
    settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS = 1.0
    settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT = 1

    try:
        compute_job_store.create_schema()
        compute_job_store.clear_all_records()
        lineage_metadata_store.create_schema()
        lineage_metadata_store.clear_all_records()

        retry_id = uuid4()
        failed_id = uuid4()
        compute_job_store.enqueue_job(
            calculation_id=retry_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": "PF-RUNTIME-DEGRADE"},
        )
        compute_job_store.enqueue_job(
            calculation_id=failed_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": "PF-RUNTIME-FAILED"},
        )
        with compute_job_store._session() as session:
            retry_row = compute_job_store._get_model(session, retry_id)
            retry_row.attempt_count = 1
            retry_row.created_at_utc = datetime.now(timezone.utc) - timedelta(seconds=120)
            failed_row = compute_job_store._get_model(session, failed_id)
            failed_row.job_status = "failed"
            failed_row.error_type = "RuntimeError"

        lineage_id = uuid4()
        lineage_metadata_store.enqueue_lineage_payload(
            calculation_id=lineage_id,
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"request.json": "{}"},
        )
        lineage_metadata_store.increment_attempt_count(lineage_id)
        lineage_metadata_store.mark_failed(lineage_id, error_message="lineage write failed")

        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["runtime_status"] == "degraded"
        assert body["compute_queue"]["degradation_reasons"] == [
            "compute_retry_backlog_exceeded",
            "compute_terminal_failure_exceeded",
            "compute_pending_age_exceeded",
        ]
        assert body["lineage_queue"]["degradation_reasons"] == [
            "lineage_terminal_failure_exceeded",
        ]
        assert body["runtime_degradation_reasons"] == [
            "compute_queue:compute_retry_backlog_exceeded",
            "compute_queue:compute_terminal_failure_exceeded",
            "compute_queue:compute_pending_age_exceeded",
            "lineage_queue:lineage_terminal_failure_exceeded",
        ]
    finally:
        (
            settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
            settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
            settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
            settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS,
            settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT,
        ) = originals
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()
