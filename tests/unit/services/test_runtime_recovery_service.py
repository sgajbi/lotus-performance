from datetime import UTC, datetime

from app.services.compute_job_store import ComputeRecoveryEvent, ComputeRecoveryEventPage
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageRecoveryEventPage
from app.services.runtime_recovery_service import _queue_state_from_recovery_page, build_runtime_recovery_snapshot


def test_queue_state_from_recovery_page_projects_cursor_metadata():
    page = ComputeRecoveryEventPage(
        total_count=7,
        next_offset=5,
        next_cursor_recovered_before="2026-03-14T11:00:00Z",
        next_cursor_calculation_id_before="calc-5",
        items=[
            ComputeRecoveryEvent(
                calculation_id="calc-1",
                analytics_type="ReturnsSeries",
                recovery_kind="retry",
                recovered_at_utc="2026-03-14T10:00:00Z",
                attempt_count=2,
                error_type="TimeoutError",
            ),
            ComputeRecoveryEvent(
                calculation_id="calc-2",
                analytics_type="TWR",
                recovery_kind="retry",
                recovered_at_utc="2026-03-14T10:30:00Z",
                attempt_count=3,
                error_type="RuntimeError",
            ),
        ],
    )

    state = _queue_state_from_recovery_page(page)

    assert state.status == "available"
    assert state.total_count == 7
    assert state.returned_count == 2
    assert state.next_offset == 5
    assert state.next_cursor_recovered_before == "2026-03-14T11:00:00Z"
    assert state.next_cursor_calculation_id_before == "calc-5"


def test_runtime_recovery_snapshot_reports_partial_queue_failure(mocker):
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        side_effect=RuntimeError("compute unavailable"),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(
            total_count=0,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="both",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
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
        "app.services.runtime_recovery_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        return_value=ComputeRecoveryEventPage(
            total_count=0,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(
            total_count=0,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="lineage",
        limit=5,
        offset=2,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
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
        "app.services.runtime_recovery_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        return_value=ComputeRecoveryEventPage(
            total_count=3,
            next_offset=2,
            next_cursor_recovered_before="2026-03-14T11:00:00Z",
            next_cursor_calculation_id_before="calc-2",
            items=[],
        ),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(
            total_count=1,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="both",
        limit=2,
        offset=0,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
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
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
    )
    assert snapshot.recovered_after == recovered_after
    assert snapshot.recovered_before == recovered_before
    assert snapshot.compute_queue.next_offset == 2
    assert snapshot.compute_queue.next_cursor_recovered_before == "2026-03-14T11:00:00Z"
    assert snapshot.compute_queue.next_cursor_calculation_id_before == "calc-2"
    assert snapshot.lineage_queue.next_offset is None


def test_runtime_recovery_snapshot_passes_seek_cursor(mocker):
    cursor_recovered_before = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        return_value=ComputeRecoveryEventPage(
            total_count=1,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(
            total_count=0,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="compute",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before="calc-9",
        calculation_id_contains=None,
        compute_analytics_type=None,
        lineage_calculation_type=None,
    )

    compute_list.assert_called_once_with(
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before="calc-9",
        analytics_type=None,
        calculation_id_contains=None,
    )
    assert snapshot.cursor_recovered_before == cursor_recovered_before
    assert snapshot.cursor_calculation_id_before == "calc-9"


def test_runtime_recovery_snapshot_ignores_lineage_storage_outage_when_metadata_is_ready(mocker):
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        return_value=ComputeRecoveryEventPage(
            total_count=1,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=LineageRecoveryEventPage(
            total_count=0,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="compute",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
        calculation_id_contains=None,
        compute_analytics_type=None,
        lineage_calculation_type=None,
    )

    assert snapshot.durable_metadata_store.status == "ready"
    assert snapshot.compute_queue.status == "available"
    assert snapshot.compute_queue.total_count == 1
    compute_list.assert_called_once()


def test_runtime_recovery_snapshot_reports_unavailable_when_metadata_store_is_down(mocker):
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        ),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="both",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
        calculation_id_contains=None,
        compute_analytics_type=None,
        lineage_calculation_type=None,
    )

    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.compute_recoveries == []
    assert snapshot.lineage_recoveries == []


def test_runtime_recovery_snapshot_reports_lineage_queue_failure(mocker):
    mocker.patch(
        "app.services.runtime_recovery_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        return_value=ComputeRecoveryEventPage(
            total_count=0,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
            items=[],
        ),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        side_effect=RuntimeError("lineage unavailable"),
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter="both",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
        calculation_id_contains=None,
        compute_analytics_type=None,
        lineage_calculation_type=None,
    )

    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.lineage_queue.reason == "RuntimeError"
