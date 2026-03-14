import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineagePayloadModel, lineage_metadata_store
from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import RuntimeRetentionHistoryEntry, RuntimeRetentionHistorySnapshot
from main import app

settings = get_settings()


@pytest.fixture()
def client():
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    os.makedirs(settings.LINEAGE_STORAGE_PATH, exist_ok=True)

    with TestClient(app) as c:
        yield c

    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)


def test_integration_capabilities_default_contract():
    with TestClient(app) as client:
        response = client.get("/integration/capabilities?consumer_system=lotus-gateway&tenant_id=default")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["source_service"] == "lotus-performance"
    assert body["consumer_system"] == "lotus-gateway"
    assert body["tenant_id"] == "default"
    assert body["supported_input_modes"] == ["stateful", "stateless"]
    assert len(body["features"]) >= 4
    assert len(body["workflows"]) >= 3
    features = {item["key"] for item in body["features"]}
    assert "pa.execution.stateful" in features
    assert "pa.execution.stateless" in features
    assert response.headers.get("X-Correlation-Id")
    assert response.headers.get("X-Request-Id")
    assert response.headers.get("X-Trace-Id")


def test_integration_capabilities_env_override(monkeypatch):
    monkeypatch.setenv("PA_CAP_ATTRIBUTION_ENABLED", "false")
    monkeypatch.setenv("PLATFORM_INPUT_MODE_STATELESS_ENABLED", "false")
    monkeypatch.setenv("PA_POLICY_VERSION", "tenant-a-v4")
    with TestClient(app) as client:
        response = client.get("/integration/capabilities?consumer_system=lotus-manage&tenant_id=tenant-a")

    assert response.status_code == 200
    body = response.json()
    assert body["consumer_system"] == "lotus-manage"
    assert body["tenant_id"] == "tenant-a"
    assert body["policy_version"] == "tenant-a-v4"
    features = {item["key"]: item["enabled"] for item in body["features"]}
    assert features["pa.analytics.attribution"] is False
    assert body["supported_input_modes"] == ["stateful"]


def test_integration_capabilities_limit_guardrails():
    with TestClient(app) as client:
        response = client.get(
            "/integration/capabilities?consumer_system=lotus-gateway&tenant_id=default&feature_limit=2&workflow_limit=1"
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["features"]) == 2
    assert len(body["workflows"]) == 1


def test_health_and_metrics_endpoints_available(client):
    health = client.get("/health")
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    metrics = client.get("/metrics")

    assert health.status_code == 200
    assert live.status_code == 200
    assert ready.status_code == 200
    assert health.json() == {"status": "ok"}
    assert live.json() == {"status": "live"}
    assert ready.json() == {"status": "ready"}
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text or "http_request_duration" in metrics.text


def test_health_ready_returns_503_when_draining():
    with TestClient(app) as client:
        app.state.is_draining = True
        response = client.get("/health/ready")
    app.state.is_draining = False

    assert response.status_code == 503
    assert response.json() == {"status": "draining"}


def test_health_ready_returns_503_when_durable_metadata_store_is_unavailable(mocker):
    mocker.patch(
        "app.api.endpoints.health.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "durable_metadata_store_unreachable"
    assert "database URL" in response.json()["remediation_hint"]


def test_health_ready_returns_503_when_lineage_storage_is_unavailable(mocker):
    mocker.patch(
        "app.api.endpoints.health.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="lineage_storage_path_missing",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "reason": "lineage_storage_path_missing",
        "remediation_hint": (
            "Create or remount the configured lineage storage directory, then confirm the service is "
            "pointing at the expected path."
        ),
    }


def test_health_ready_returns_hint_when_lineage_write_probe_fails(mocker):
    mocker.patch(
        "app.api.endpoints.health.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="lineage_storage_write_probe_failed",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "lineage_storage_write_probe_failed"
    assert "write/delete probe" in response.json()["remediation_hint"]


def test_metrics_include_durable_queue_pressure_signals():
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
        metrics = client.get("/metrics")

    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()

    assert metrics.status_code == 200
    assert 'lotus_performance_durable_queue_store_availability{store="compute"} 1.0' in metrics.text
    assert 'lotus_performance_durable_queue_store_availability{store="lineage"} 1.0' in metrics.text
    assert "lotus_performance_compute_queue_jobs" in metrics.text
    assert "lotus_performance_compute_queue_failure_pressure_jobs" in metrics.text
    assert 'lotus_performance_compute_queue_jobs{status="pending"} 1.0' in metrics.text, metrics.text
    assert "lotus_performance_compute_queue_oldest_leased_age_seconds" in metrics.text
    assert "lotus_performance_compute_queue_oldest_running_age_seconds" in metrics.text
    lineage_match = re.search(r"lotus_performance_lineage_queue_pending_payloads ([0-9]+(?:\.[0-9]+)?)", metrics.text)
    assert lineage_match is not None, metrics.text
    assert float(lineage_match.group(1)) >= 1.0
    assert "lotus_performance_lineage_queue_failure_pressure_payloads" in metrics.text


def test_metrics_include_lineage_storage_capacity_signals(mocker):
    mocker.patch(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        return_value=type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 700,
                "free_bytes": 300,
                "free_ratio": 0.3,
            },
        )(),
    )
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_bytes = settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES
    original_ratio = settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO
    settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES = 250
    settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO = 0.2

    try:
        with TestClient(app) as client:
            metrics = client.get("/metrics")

        assert metrics.status_code == 200
        assert "lotus_performance_lineage_storage_capacity_availability 1.0" in metrics.text
        assert 'lotus_performance_lineage_storage_capacity_bytes{segment="total"} 1000.0' in metrics.text
        assert 'lotus_performance_lineage_storage_capacity_bytes{segment="used"} 700.0' in metrics.text
        assert 'lotus_performance_lineage_storage_capacity_bytes{segment="free"} 300.0' in metrics.text
        assert "lotus_performance_lineage_storage_free_ratio 0.3" in metrics.text
        assert (
            'lotus_performance_lineage_storage_pressure_breach{reason="lineage_storage_free_bytes_below_threshold"} 0.0'
            in metrics.text
        )
        assert (
            'lotus_performance_lineage_storage_pressure_breach{reason="lineage_storage_free_ratio_below_threshold"} 0.0'
            in metrics.text
        )
        assert 'lotus_performance_lineage_storage_pressure_threshold{threshold="min_free_bytes"} 250.0' in metrics.text
        assert 'lotus_performance_lineage_storage_pressure_threshold{threshold="min_free_ratio"} 0.2' in metrics.text
    finally:
        settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES = original_bytes
        settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO = original_ratio


def test_metrics_expose_store_unavailability_without_false_zero_queue_samples(mocker):
    mocker.patch(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        side_effect=RuntimeError("compute unavailable"),
    )
    mocker.patch(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        side_effect=RuntimeError("lineage unavailable"),
    )
    mocker.patch(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        side_effect=RuntimeError("storage unavailable"),
    )

    with TestClient(app) as client:
        metrics = client.get("/metrics")

    assert metrics.status_code == 200
    assert 'lotus_performance_durable_queue_store_availability{store="compute"} 0.0' in metrics.text
    assert 'lotus_performance_durable_queue_store_availability{store="lineage"} 0.0' in metrics.text
    assert "lotus_performance_lineage_storage_capacity_availability 0.0" in metrics.text
    assert "lotus_performance_compute_queue_jobs" not in metrics.text
    assert "lotus_performance_lineage_queue_pending_payloads" not in metrics.text
    assert "lotus_performance_lineage_storage_capacity_bytes" not in metrics.text
    assert "lotus_performance_lineage_storage_pressure_breach" not in metrics.text


def test_metrics_include_lineage_storage_pressure_breach_signals(mocker):
    mocker.patch(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        return_value=type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 925,
                "free_bytes": 75,
                "free_ratio": 0.075,
            },
        )(),
    )
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_bytes = settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES
    original_ratio = settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO
    settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES = 150
    settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO = 0.1

    try:
        with TestClient(app) as client:
            metrics = client.get("/metrics")

        assert metrics.status_code == 200
        assert (
            'lotus_performance_lineage_storage_pressure_breach{reason="lineage_storage_free_bytes_below_threshold"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_lineage_storage_pressure_breach{reason="lineage_storage_free_ratio_below_threshold"} 1.0'
            in metrics.text
        )
    finally:
        settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES = original_bytes
        settings.RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO = original_ratio


def test_metrics_include_queue_policy_breach_signals():
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    originals = (
        settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
        settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
        settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
        settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
        settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT,
        settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
        settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS,
        settings.RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS,
        settings.RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT,
        settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT,
    )
    settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS = 30.0
    settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS = 10.0
    settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS = 5.0
    settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT = 1
    settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT = 1
    settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT = 1
    settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS = 20.0
    settings.RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS = 10.0
    settings.RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT = 1
    settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT = 1

    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    retry_id = uuid4()
    leased_id = uuid4()
    running_id = uuid4()
    failed_id = uuid4()
    lineage_id = uuid4()
    lineage_leased_id = uuid4()
    lineage_failed_id = uuid4()
    compute_job_store.enqueue_job(
        calculation_id=retry_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-RETRY"},
    )
    compute_job_store.enqueue_job(
        calculation_id=leased_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-LEASED"},
    )
    compute_job_store.enqueue_job(
        calculation_id=running_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-RUN"},
    )
    compute_job_store.enqueue_job(
        calculation_id=failed_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-FAIL"},
    )
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=lineage_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request.json": "{}"},
    )
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=lineage_leased_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request.json": "{}"},
    )
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=lineage_failed_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request.json": "{}"},
    )

    with compute_job_store._session() as session:
        retry_row = compute_job_store._get_model(session, retry_id)
        retry_row.attempt_count = 1
        retry_row.error_type = "LeaseExpired"
        retry_row.created_at_utc = datetime.now(timezone.utc) - timedelta(seconds=45)

        leased_row = compute_job_store._get_model(session, leased_id)
        leased_row.job_status = "leased"
        leased_row.leased_at_utc = datetime.now(timezone.utc) - timedelta(seconds=18)
        leased_row.lease_expires_at_utc = datetime.now(timezone.utc) + timedelta(seconds=30)

        running_row = compute_job_store._get_model(session, running_id)
        running_row.job_status = "running"
        running_row.started_at_utc = datetime.now(timezone.utc) - timedelta(seconds=12)
        running_row.leased_at_utc = datetime.now(timezone.utc) - timedelta(seconds=12)
        running_row.lease_expires_at_utc = datetime.now(timezone.utc) + timedelta(seconds=30)

        failed_row = compute_job_store._get_model(session, failed_id)
        failed_row.job_status = "failed"
        failed_row.error_type = "RuntimeError"

    lineage_metadata_store.increment_attempt_count(lineage_id)
    with lineage_metadata_store._session() as session:
        payload = session.get(LineagePayloadModel, str(lineage_id))
        assert payload is not None
        payload.created_at_utc = datetime.now(timezone.utc) - timedelta(seconds=30)
        payload.leased_at_utc = datetime.now(timezone.utc) - timedelta(seconds=15)
        payload.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=5)
        leased_payload = session.get(LineagePayloadModel, str(lineage_leased_id))
        assert leased_payload is not None
        leased_payload.leased_at_utc = datetime.now(timezone.utc) - timedelta(seconds=15)
        leased_payload.lease_expires_at_utc = datetime.now(timezone.utc) + timedelta(seconds=30)
    lineage_metadata_store.mark_failed(lineage_id, error_message="lineage failed")
    lineage_metadata_store.mark_pending(lineage_id)
    lineage_metadata_store.increment_attempt_count(lineage_failed_id)
    lineage_metadata_store.mark_failed(lineage_failed_id, error_message="lineage terminal failure")

    try:
        with TestClient(app) as client:
            metrics = client.get("/metrics")

        assert metrics.status_code == 200
        assert (
            'lotus_performance_compute_queue_degradation_breach{reason="compute_retry_backlog_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_compute_queue_degradation_breach{reason="compute_lease_expiry_pressure_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_compute_queue_degradation_breach{reason="compute_terminal_failure_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_compute_queue_degradation_breach{reason="compute_pending_age_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_compute_queue_degradation_breach{reason="compute_leased_age_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_compute_queue_degradation_breach{reason="compute_running_age_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_lineage_queue_degradation_breach{reason="lineage_retry_backlog_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_lineage_queue_degradation_breach{reason="lineage_terminal_failure_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_lineage_queue_degradation_breach{reason="lineage_pending_age_exceeded"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_lineage_queue_degradation_breach{reason="lineage_leased_age_exceeded"} 1.0'
            in metrics.text
        )
    finally:
        (
            settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
            settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
            settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
            settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
            settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT,
            settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
            settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS,
            settings.RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS,
            settings.RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT,
            settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT,
        ) = originals
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_metrics_include_recovery_drill_breach_signals(mocker):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    original_threshold = settings.RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS
    original_retention_threshold = settings.RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS
    settings.RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS = 300.0
    settings.RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS = 300.0
    mocker.patch(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RecoveryDrillHistoryEntry(
                    evidence_file_name="latest.json",
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
    mocker.patch(
        "app.services.queue_metrics_service.build_runtime_retention_history_snapshot",
        return_value=RuntimeRetentionHistorySnapshot(
            status="available",
            artifact_directory="artifacts/runtime-retention-cleanup",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RuntimeRetentionHistoryEntry(
                    evidence_file_name="latest.json",
                    generated_at_utc=(datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat().replace("+00:00", "Z"),
                    operator_id="ops-user",
                    cleanup_mode="dry_run",
                    status="planned",
                    retention_days=30,
                    prunable_execution_count=1,
                    prunable_compute_job_count=1,
                    prunable_async_result_count=1,
                    prunable_lineage_record_count=1,
                    prunable_lineage_artifact_count=1,
                )
            ],
            total_entries=1,
            matched_entries=1,
            returned_entries=1,
            next_offset=None,
            applied_filters={},
        ),
    )
    mocker.patch(
        "app.services.queue_metrics_service.run_runtime_retention_cleanup",
        return_value=type(
            "RuntimeRetentionPreview",
            (),
            {
                "prunable_execution_count": 4,
                "prunable_compute_job_count": 3,
                "prunable_async_result_count": 2,
                "prunable_lineage_record_count": 1,
                "prunable_lineage_artifact_count": 1,
            },
        )(),
    )

    try:
        with TestClient(app) as client:
            metrics = client.get("/metrics")

        assert metrics.status_code == 200
        assert "lotus_performance_recovery_drill_availability 1.0" in metrics.text
        assert "lotus_performance_recovery_drill_latest_age_seconds" in metrics.text
        assert 'lotus_performance_recovery_drill_policy_threshold{threshold="max_age_seconds"} 300.0' in metrics.text
        assert (
            'lotus_performance_recovery_drill_degradation_breach{reason="recovery_drill_latest_not_passed"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_recovery_drill_degradation_breach{reason="recovery_drill_age_exceeded"} 1.0'
            in metrics.text
        )
        assert "lotus_performance_runtime_retention_availability 1.0" in metrics.text
        assert "lotus_performance_runtime_retention_preview_availability 1.0" in metrics.text
        assert "lotus_performance_runtime_retention_latest_age_seconds" in metrics.text
        assert 'lotus_performance_runtime_retention_policy_threshold{threshold="max_age_seconds"} 300.0' in metrics.text
        assert (
            'lotus_performance_runtime_retention_degradation_breach{reason="runtime_retention_latest_not_applied"} 1.0'
            in metrics.text
        )
        assert (
            'lotus_performance_runtime_retention_degradation_breach{reason="runtime_retention_age_exceeded"} 1.0'
            in metrics.text
        )
        assert 'lotus_performance_runtime_retention_prunable_items{category="execution"} 4.0' in metrics.text
    finally:
        settings.RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS = original_threshold
        settings.RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS = original_retention_threshold
