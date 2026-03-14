from app.models.recovery_drill_history import build_recovery_drill_history_response
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
        returned_entries=1,
        applied_filters={"limit": 1, "status": "passed"},
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="2026-03-14t00-00-00.json",
                generated_at_utc="2026-03-14T00:00:00Z",
                operator_id="ops-user",
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
    assert response.returned_entries == 1
    assert response.applied_filters == {"limit": 1, "status": "passed"}
    assert response.entries[0].backup_identifier == "backup-123"
