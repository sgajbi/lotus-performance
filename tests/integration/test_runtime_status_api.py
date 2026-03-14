from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineagePayloadModel, lineage_metadata_store
from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
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
    assert body["runtime_degradation_details"] == []
    assert body["draining"] is False
    assert body["durable_metadata_store"]["status"] == "ready"
    assert body["compute_queue_policy"]["pending_age_seconds"] >= 0.0
    assert body["compute_queue_policy"]["retry_backlog_count"] >= 0
    assert body["lineage_queue_policy"]["pending_age_seconds"] >= 0.0
    assert body["lineage_queue_policy"]["terminal_failure_count"] >= 0
    assert body["compute_queue"]["status"] == "available"
    assert body["compute_queue"]["degradation_reasons"] == []
    assert body["compute_queue"]["degradation_details"] == []
    assert body["compute_queue"]["pending_jobs"] == 1
    assert body["compute_queue"]["retry_backlog_jobs"] == 0
    assert body["compute_queue"]["lease_expired_jobs"] == 0
    assert body["compute_queue"]["reclaimable_jobs"] == 0
    assert body["compute_queue"]["terminal_failure_jobs"] == 0
    assert body["compute_queue"]["oldest_leased_age_seconds"] == 0.0
    assert body["compute_queue"]["oldest_running_age_seconds"] == 0.0
    assert body["compute_queue"]["inspection_anchors"]["oldest_pending_calculation_id"] is not None
    assert body["compute_queue"]["inspection_anchors"].get("oldest_leased_calculation_id") is None
    assert body["compute_queue"]["inspection_anchors"].get("latest_recovered_calculation_id") is None
    assert body["lineage_queue"]["status"] == "available"
    assert body["lineage_queue"]["degradation_reasons"] == []
    assert body["lineage_queue"]["degradation_details"] == []
    assert body["lineage_queue"]["pending_payloads"] == 1
    assert body["lineage_queue"]["leased_payloads"] == 0
    assert body["lineage_queue"]["retry_backlog_payloads"] == 0
    assert body["lineage_queue"]["reclaimable_payloads"] == 0
    assert body["lineage_queue"]["terminal_failure_payloads"] == 0
    assert body["lineage_queue"]["oldest_leased_age_seconds"] == 0.0
    assert body["lineage_queue"]["inspection_anchors"]["oldest_pending_calculation_id"] is not None
    assert body["lineage_queue"]["inspection_anchors"].get("oldest_leased_calculation_id") is None
    assert body["lineage_queue"]["inspection_anchors"].get("latest_recovered_calculation_id") is None
    assert body["recovery_drill"]["status"] == "available"
    assert body["recovery_drill"]["degradation_reasons"] == []
    assert body["recovery_drill_policy"]["max_age_seconds"] >= 0.0


def test_runtime_status_reports_draining_state():
    with TestClient(app) as client:
        app.state.is_draining = True
        response = client.get("/integration/runtime-status")
    app.state.is_draining = False

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_status"] == "draining"
    assert body["runtime_degradation_reasons"] == []
    assert body["runtime_degradation_details"] == []
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
    assert body["runtime_degradation_details"] == []
    assert body["durable_metadata_store"]["status"] == "unavailable"
    assert body["durable_metadata_store"]["reason"] == "durable_metadata_store_unreachable"
    assert "database URL" in body["durable_metadata_store"]["remediation_hint"]
    assert body["compute_queue"]["status"] == "unavailable"
    assert "pending_jobs" not in body["compute_queue"]
    assert body["lineage_queue"]["status"] == "unavailable"


def test_runtime_status_reports_unavailable_recovery_history_snapshot(mocker):
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="unavailable",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name=None,
            retained_file_names=[],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason="artifact_directory_unreadable",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/integration/runtime-status")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_status"] == "degraded"
    assert body["runtime_degradation_reasons"] == ["recovery_drill:artifact_directory_unreadable"]
    assert body["recovery_drill"]["status"] == "unavailable"
    assert body["recovery_drill"]["reason"] == "artifact_directory_unreadable"
    assert "latest_status" not in body["recovery_drill"]


def test_runtime_status_reports_unavailable_lineage_storage(mocker):
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": False, "reason": "lineage_storage_path_missing"})(),
    )

    with TestClient(app) as client:
        response = client.get("/integration/runtime-status")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_status"] == "degraded"
    assert body["runtime_degradation_reasons"] == ["lineage_queue:lineage_storage_path_missing"]
    assert body["lineage_queue"]["status"] == "unavailable"
    assert body["lineage_queue"]["reason"] == "lineage_storage_path_missing"
    assert "configured lineage storage directory" in body["lineage_queue"]["remediation_hint"]
    assert "pending_payloads" not in body["lineage_queue"]


def test_runtime_status_reports_degraded_lineage_storage_capacity_pressure(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_lineage_storage_capacity",
        return_value=type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 850,
                "free_bytes": 150,
                "free_ratio": 0.15,
                "used_ratio": 0.85,
            },
        )(),
    )

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_bytes = settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES
    original_ratio = settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO
    settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES = 200
    settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO = 0.2

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["runtime_status"] == "degraded"
        assert body["runtime_degradation_reasons"] == [
            "lineage_queue:lineage_storage_free_bytes_below_threshold",
            "lineage_queue:lineage_storage_free_ratio_below_threshold",
        ]
        assert body["lineage_queue"]["status"] == "degraded"
        assert body["lineage_queue"]["reason"] == "lineage_storage_free_bytes_below_threshold"
        assert body["lineage_queue"]["remediation_hint"].startswith("Free space on the lineage storage filesystem")
        assert body["lineage_queue"]["storage_total_bytes"] == 1000
        assert body["lineage_queue"]["storage_used_bytes"] == 850
        assert body["lineage_queue"]["storage_free_bytes"] == 150
        assert body["lineage_queue"]["storage_free_ratio"] == 0.15
        assert body["lineage_queue_policy"]["storage_min_free_bytes"] == 200
        assert body["lineage_queue_policy"]["storage_min_free_ratio"] == 0.2
    finally:
        settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES = original_bytes
        settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO = original_ratio


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
        assert len(body["runtime_degradation_details"]) == 1
        assert body["runtime_degradation_details"][0]["reason"] == "compute_pending_age_exceeded"
        assert body["runtime_degradation_details"][0]["threshold_value"] == 30.0
        assert body["runtime_degradation_details"][0]["observed_value"] >= 90.0
        assert body["compute_queue"]["status"] == "degraded"
        assert body["compute_queue"]["reason"] == "compute_pending_age_exceeded"
        assert body["compute_queue"]["degradation_reasons"] == ["compute_pending_age_exceeded"]
        assert body["compute_queue"]["degradation_details"] == body["runtime_degradation_details"]
    finally:
        settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS = original_threshold
        compute_job_store.clear_all_records()


def test_runtime_status_exposes_compute_failure_pressure_counts():
    compute_job_store.create_schema()
    compute_job_store.clear_all_records()
    pending_retry_id = uuid4()
    reclaimable_id = uuid4()
    failed_terminal_id = uuid4()

    compute_job_store.enqueue_job(
        calculation_id=pending_retry_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-RETRY"},
    )
    compute_job_store.enqueue_job(
        calculation_id=reclaimable_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-RECLAIM"},
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
        reclaimable_row = compute_job_store._get_model(session, reclaimable_id)
        reclaimable_row.job_status = "running"
        reclaimable_row.started_at_utc = datetime.now(timezone.utc) - timedelta(seconds=30)
        reclaimable_row.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=5)
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
        assert body["compute_queue"]["reclaimable_jobs"] == 1
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
    with lineage_metadata_store._session() as session:
        retry_payload = session.get(LineagePayloadModel, str(retry_id))
        assert retry_payload is not None
        retry_payload.leased_at_utc = datetime.now(timezone.utc) - timedelta(seconds=20)
        retry_payload.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=5)

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["lineage_queue"]["retry_backlog_payloads"] == 1
        assert body["lineage_queue"]["reclaimable_payloads"] == 1
        assert body["lineage_queue"]["terminal_failure_payloads"] == 1
    finally:
        lineage_metadata_store.clear_all_records()


def test_runtime_status_exposes_latest_recovered_inspection_anchors():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    compute_recovered_id = uuid4()
    lineage_recovered_id = uuid4()

    compute_job_store.enqueue_job(
        calculation_id=compute_recovered_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-RECOVERED"},
    )
    with compute_job_store._session() as session:
        row = compute_job_store._get_model(session, compute_recovered_id)
        row.attempt_count = 1
        row.last_error_at_utc = datetime.now(timezone.utc) - timedelta(seconds=3)

    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=lineage_recovered_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request.json": "{}"},
    )
    lineage_metadata_store.increment_attempt_count(lineage_recovered_id)
    lineage_metadata_store.mark_pending(lineage_recovered_id)

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["compute_queue"]["inspection_anchors"]["latest_recovered_calculation_id"] == str(
            compute_recovered_id
        )
        assert body["compute_queue"]["recent_recoveries"][0]["calculation_id"] == str(compute_recovered_id)
        assert body["lineage_queue"]["inspection_anchors"]["latest_recovered_calculation_id"] == str(
            lineage_recovered_id
        )
        assert body["lineage_queue"]["recent_recoveries"][0]["calculation_id"] == str(lineage_recovered_id)
    finally:
        compute_job_store.clear_all_records()
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
        assert body["runtime_degradation_details"] == [
            {
                "reason": "compute_retry_backlog_exceeded",
                "observed_value": 1.0,
                "threshold_value": 1.0,
            }
        ]
        assert body["compute_queue_policy"]["retry_backlog_count"] == 1
        assert body["compute_queue"]["status"] == "degraded"
        assert body["compute_queue"]["reason"] == "compute_retry_backlog_exceeded"
        assert body["compute_queue"]["degradation_reasons"] == ["compute_retry_backlog_exceeded"]
        assert body["compute_queue"]["degradation_details"] == body["runtime_degradation_details"]
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
        assert body["runtime_degradation_details"] == [
            {
                "reason": "lineage_terminal_failure_exceeded",
                "observed_value": 1.0,
                "threshold_value": 1.0,
            }
        ]
        assert body["lineage_queue_policy"]["terminal_failure_count"] == 1
        assert body["lineage_queue"]["status"] == "degraded"
        assert body["lineage_queue"]["reason"] == "lineage_terminal_failure_exceeded"
        assert body["lineage_queue"]["degradation_reasons"] == ["lineage_terminal_failure_exceeded"]
        assert body["lineage_queue"]["degradation_details"] == body["runtime_degradation_details"]
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
        assert body["compute_queue"]["degradation_details"][0] == {
            "reason": "compute_retry_backlog_exceeded",
            "observed_value": 1.0,
            "threshold_value": 1.0,
        }
        assert body["compute_queue"]["degradation_details"][1] == {
            "reason": "compute_terminal_failure_exceeded",
            "observed_value": 1.0,
            "threshold_value": 1.0,
        }
        assert body["compute_queue"]["degradation_details"][2]["reason"] == "compute_pending_age_exceeded"
        assert body["compute_queue"]["degradation_details"][2]["threshold_value"] == 1.0
        assert body["compute_queue"]["degradation_details"][2]["observed_value"] >= 120.0
        assert body["lineage_queue"]["degradation_reasons"] == [
            "lineage_terminal_failure_exceeded",
        ]
        assert body["lineage_queue"]["degradation_details"] == [
            {
                "reason": "lineage_terminal_failure_exceeded",
                "observed_value": 1.0,
                "threshold_value": 1.0,
            }
        ]
        assert body["runtime_degradation_reasons"] == [
            "compute_queue:compute_retry_backlog_exceeded",
            "compute_queue:compute_terminal_failure_exceeded",
            "compute_queue:compute_pending_age_exceeded",
            "lineage_queue:lineage_terminal_failure_exceeded",
        ]
        assert body["runtime_degradation_details"] == (
            body["compute_queue"]["degradation_details"] + body["lineage_queue"]["degradation_details"]
        )
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


def test_runtime_status_reports_recovery_drill_failure_and_age_policy(mocker):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_threshold = settings.RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS
    settings.RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS = 300.0

    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="drill-20260314T000000Z.json",
            retained_file_names=["drill-20260314T000000Z.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RecoveryDrillHistoryEntry(
                    evidence_file_name="drill-20260314T000000Z.json",
                    generated_at_utc="2026-03-13T00:00:00Z",
                    operator_id="ops-user",
                    backup_identifier="backup-123",
                    status="failed",
                )
            ],
            total_entries=1,
            matched_entries=1,
            returned_entries=1,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-status")

        assert response.status_code == 200
        body = response.json()
        assert body["runtime_status"] == "degraded"
        assert body["recovery_drill"]["status"] == "degraded"
        assert body["recovery_drill"]["reason"] == "recovery_drill_latest_not_passed"
        assert body["recovery_drill"]["latest_status"] == "failed"
        assert body["recovery_drill"]["latest_operator_id"] == "ops-user"
        assert body["recovery_drill"]["latest_backup_identifier"] == "backup-123"
        assert body["recovery_drill"]["latest_age_seconds"] >= 300.0
        assert body["recovery_drill"]["degradation_reasons"] == [
            "recovery_drill_latest_not_passed",
            "recovery_drill_age_exceeded",
        ]
        assert body["runtime_degradation_reasons"] == [
            "recovery_drill:recovery_drill_latest_not_passed",
            "recovery_drill:recovery_drill_age_exceeded",
        ]
        assert body["recovery_drill_policy"]["max_age_seconds"] == 300.0
    finally:
        settings.RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS = original_threshold
