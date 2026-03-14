from datetime import UTC, datetime

from app.services.compute_job_store import ComputeRecoveryEventPage
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageRecoveryEventPage
from app.services.runtime_recovery_service import build_runtime_recovery_snapshot


def test_runtime_recovery_snapshot_reports_partial_queue_failure(mocker):
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        side_effect=RuntimeError("compute unavailable"),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(total_count=0, next_offset=None, items=[]),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="both",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        calculation_id_contains=None,
        compute_analytics_type=None,
        lineage_calculation_type=None,
    )

    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "RuntimeError"
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.compute_recoveries == []
    assert snapshot.lineage_recoveries == []


def test_runtime_recovery_snapshot_excludes_unselected_queue(mocker):
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        return_value=ComputeRecoveryEventPage(total_count=0, next_offset=None, items=[]),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(total_count=0, next_offset=None, items=[]),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="lineage",
        limit=5,
        offset=2,
        recovered_after=None,
        recovered_before=None,
        calculation_id_contains="calc",
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
    )

    compute_list.assert_not_called()
    assert snapshot.compute_queue.status == "excluded"
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.offset == 2
    assert snapshot.calculation_id_contains == "calc"


def test_runtime_recovery_snapshot_passes_time_filters_and_next_offset(mocker):
    recovered_after = datetime(2026, 3, 14, 0, 0, tzinfo=UTC)
    recovered_before = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        return_value=ComputeRecoveryEventPage(total_count=3, next_offset=2, items=[]),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(total_count=1, next_offset=None, items=[]),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="both",
        limit=2,
        offset=0,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        calculation_id_contains=None,
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
    )

    compute_list.assert_called_once_with(
        limit=2,
        offset=0,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        analytics_type="ReturnsSeries",
        calculation_id_contains=None,
    )
    assert snapshot.recovered_after == recovered_after
    assert snapshot.recovered_before == recovered_before
    assert snapshot.compute_queue.next_offset == 2
    assert snapshot.lineage_queue.next_offset is None
