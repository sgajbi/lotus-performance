from app.models.recovery_drill_history import (
    build_recovery_drill_history_response,
    build_recovery_drill_run_response,
)
from app.services.recovery_drill_history_service import (
    RecoveryDrillHistoryEntry,
    RecoveryDrillHistorySnapshot,
)


def test_build_recovery_drill_history_response_serializes_snapshot():
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory="artifacts/durable-recovery-drill",
        latest_file_name="2026-03-14t00-00-00.json",
        retained_file_names=["2026-03-14t00-00-00.json"],
        retention_limit=30,
        retention_max_age_days=90,
        total_entries=2,
        matched_entries=1,
        returned_entries=1,
        next_offset=1,
        applied_filters={"limit": 1, "status": "passed"},
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="2026-03-14t00-00-00.json",
                generated_at_utc="2026-03-14T00:00:00Z",
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                backup_identifier="backup-123",
                status="passed",
            )
        ],
        reason=None,
    )

    response = build_recovery_drill_history_response(snapshot)

    assert response.contract_version == "v1"
    assert response.source_service == "lotus-performance"
    assert response.status == "available"
    assert response.retention_max_age_days == 90
    assert response.total_entries == 2
    assert response.matched_entries == 1
    assert response.returned_entries == 1
    assert response.next_offset == 1
    assert response.applied_filters == {"limit": 1, "status": "passed"}
    assert response.entries[0].backup_identifier == "backup-123"
    assert response.entries[0].tenant_id == "tenant-a"
    assert response.entries[0].correlation_id == "corr-1"


def test_build_recovery_drill_run_response_serializes_enterprise_context():
    response = build_recovery_drill_run_response(
        drill_name="durable_metadata_restore_recovery",
        generated_at_utc="2026-03-14T00:00:00Z",
        evidence_file_name="2026-03-14t00-00-00.json",
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        backup_identifier="backup-123",
        status="passed",
        database_path="tmp/recovery.db",
        restored_schema_mode="legacy_lineage_schema_upgraded_in_place",
        owned_tables_present=["analytics_execution"],
        compute_job_processed_count=1,
        compute_async_result_status="complete",
        compute_execution_status="complete",
        processed_payload_count=1,
        materialized_artifact_path="tmp/details.csv",
        materialized_artifact_exists=True,
    )

    assert response.operator_id == "ops-user"
    assert response.tenant_id == "tenant-a"
    assert response.correlation_id == "corr-1"
    assert response.backup_identifier == "backup-123"
