from __future__ import annotations

from main import app


def test_runtime_status_openapi_documents_operator_control_plane_purpose() -> None:
    spec = app.openapi()
    operation = spec["paths"]["/integration/runtime-status"]["get"]

    assert "operator control-plane snapshot" in operation["description"]
    assert "compute and lineage queue pressure" in operation["description"]
    assert "runtime-retention assurance" in operation["description"]
    assert "runtime-work-item" in operation["description"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RuntimeStatusResponse"
    )


def test_runtime_status_response_schema_documents_status_families() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    response_schema = schemas["RuntimeStatusResponse"]
    compute_schema = schemas["ComputeQueueStatusDetailsResponse"]
    lineage_schema = schemas["LineageQueueStatusDetailsResponse"]
    recovery_schema = schemas["RecoveryDrillStatusResponse"]
    retention_schema = schemas["RuntimeRetentionStatusResponse"]

    for field_name in [
        "contract_version",
        "source_service",
        "generated_at",
        "runtime_status",
        "runtime_degradation_reasons",
        "runtime_degradation_details",
        "draining",
        "durable_metadata_store",
        "compute_queue",
        "lineage_queue",
        "recovery_drill",
        "runtime_retention",
        "compute_queue_policy",
        "lineage_queue_policy",
        "recovery_drill_policy",
        "runtime_retention_policy",
    ]:
        assert response_schema["properties"][field_name]["description"]
        assert response_schema["properties"][field_name].get("example") is not None

    for field_name in [
        "status",
        "pending_jobs",
        "retry_backlog_jobs",
        "lease_expired_jobs",
        "reclaimable_jobs",
        "terminal_failure_jobs",
        "inspection_anchors",
        "recent_recoveries",
    ]:
        assert compute_schema["properties"][field_name]["description"]

    for field_name in [
        "status",
        "remediation_hint",
        "pending_payloads",
        "retry_backlog_payloads",
        "terminal_failure_payloads",
        "storage_total_bytes",
        "storage_free_ratio",
        "inspection_anchors",
        "recent_recoveries",
    ]:
        assert lineage_schema["properties"][field_name]["description"]

    for field_name in ["status", "active_run_status", "recent_reclaimed_runs", "latest_status"]:
        assert recovery_schema["properties"][field_name]["description"]

    for field_name in [
        "status",
        "active_run_status",
        "preview_status",
        "current_prunable_execution_count",
        "current_prunable_lineage_artifact_count",
    ]:
        assert retention_schema["properties"][field_name]["description"]
