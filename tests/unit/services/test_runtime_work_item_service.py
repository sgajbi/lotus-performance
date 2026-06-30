import logging
from datetime import UTC, datetime

from app.services.compute_job_store import ComputeQueueInspectionItem, ComputeQueueInspectionPage
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageQueueInspectionItem
from app.services.runtime_operator_diagnostics import COMPUTE_WORK_ITEM_READ_FAILED, LINEAGE_WORK_ITEM_READ_FAILED
from app.services.runtime_work_item_service import (
    _available_runtime_work_item_snapshot,
    _unavailable_runtime_work_item_snapshot,
    build_runtime_work_item_snapshot,
)


def test_runtime_work_item_snapshot_reports_partial_queue_failure(mocker, caplog):
    caplog.set_level(logging.WARNING, logger="app.services.runtime_work_item_service")
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        side_effect=RuntimeError("compute unavailable"),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        return_value=type(
            "LineagePage",
            (),
            {
                "total_count": 1,
                "next_offset": None,
                "items": [
                    LineageQueueInspectionItem(
                        calculation_id="calc-1",
                        calculation_type="TWR",
                        status="pending",
                        active_since_utc="2026-03-14T00:00:00Z",
                        age_seconds=30.0,
                        attempt_count=0,
                        error_message=None,
                    )
                ],
            },
        )(),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="both",
        status_filter="active",
        limit=5,
        offset=0,
        min_age_seconds=0.0,
        compute_analytics_type=None,
        lineage_calculation_type=None,
        calculation_id_contains="calc-sensitive-fragment",
    )

    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == COMPUTE_WORK_ITEM_READ_FAILED
    assert snapshot.compute_queue.total_count == 0
    assert snapshot.compute_items == []
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.lineage_queue.total_count == 1
    assert snapshot.lineage_queue.returned_count == 1
    assert len(snapshot.lineage_items) == 1
    warning = next(record for record in caplog.records if record.message == "Runtime operator read degraded.")
    extra_fields = warning.extra_fields
    assert extra_fields["event_name"] == "runtime_operator_read_degraded"
    assert extra_fields["source"] == "compute"
    assert extra_fields["operation"] == "work_item"
    assert extra_fields["reason"] == COMPUTE_WORK_ITEM_READ_FAILED
    assert extra_fields["exception_class"] == "RuntimeError"
    assert extra_fields["calculation_id_filter_present"] is True
    assert "calc-sensitive-fragment" not in extra_fields.values()


def test_runtime_work_item_snapshot_reports_unavailable_when_durable_store_is_down(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        ),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="both",
        status_filter="failed",
        limit=10,
        offset=0,
        min_age_seconds=0.0,
        compute_analytics_type=None,
        lineage_calculation_type=None,
        calculation_id_contains=None,
    )

    assert snapshot.durable_metadata_store.status == "unavailable"
    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.compute_items == []
    assert snapshot.lineage_items == []


def test_unavailable_runtime_work_item_snapshot_preserves_filters_and_store_reason():
    generated_at = datetime(2026, 3, 14, tzinfo=UTC)
    durability_status = DurabilityHealthStatus(
        is_ready=False,
        status="schema_incomplete",
        reason="missing_tables: compute_jobs",
    )

    snapshot = _unavailable_runtime_work_item_snapshot(
        generated_at=generated_at,
        queue_filter="compute",
        status_filter="reclaimable",
        limit=17,
        offset=4,
        min_age_seconds=120.0,
        compute_analytics_type="Attribution",
        lineage_calculation_type="TWR",
        calculation_id_contains="calc-",
        durable_metadata_store=durability_status,
    )

    assert snapshot.generated_at == generated_at
    assert snapshot.queue_filter == "compute"
    assert snapshot.status_filter == "reclaimable"
    assert snapshot.limit == 17
    assert snapshot.offset == 4
    assert snapshot.min_age_seconds == 120.0
    assert snapshot.compute_analytics_type == "Attribution"
    assert snapshot.lineage_calculation_type == "TWR"
    assert snapshot.calculation_id_contains == "calc-"
    assert snapshot.durable_metadata_store == durability_status
    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "missing_tables: compute_jobs"
    assert snapshot.lineage_queue.reason == "missing_tables: compute_jobs"
    assert snapshot.compute_items == []
    assert snapshot.lineage_items == []


def test_available_runtime_work_item_snapshot_preserves_filters_and_queue_results(mocker):
    generated_at = datetime(2026, 3, 14, tzinfo=UTC)
    durability_status = DurabilityHealthStatus(is_ready=True, status="ready", reason=None)
    compute_item = ComputeQueueInspectionItem(
        calculation_id="calc-2",
        analytics_type="Contribution",
        status="failed",
        active_since_utc="2026-03-14T00:00:00Z",
        age_seconds=90.0,
        attempt_count=2,
        max_attempts=3,
        error_type="RuntimeError",
        error_message="boom",
    )
    lineage_item = LineageQueueInspectionItem(
        calculation_id="calc-1",
        calculation_type="TWR",
        status="pending",
        active_since_utc="2026-03-14T00:00:00Z",
        age_seconds=30.0,
        attempt_count=0,
        error_message=None,
    )
    mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(total_count=2, next_offset=8, items=[compute_item]),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        return_value=type("LineagePage", (), {"total_count": 1, "next_offset": None, "items": [lineage_item]})(),
    )

    snapshot = _available_runtime_work_item_snapshot(
        generated_at=generated_at,
        queue_filter="both",
        status_filter="failed",
        limit=5,
        offset=3,
        min_age_seconds=60.0,
        compute_analytics_type="Contribution",
        lineage_calculation_type="TWR",
        calculation_id_contains="calc",
        durable_metadata_store=durability_status,
    )

    assert snapshot.generated_at == generated_at
    assert snapshot.queue_filter == "both"
    assert snapshot.status_filter == "failed"
    assert snapshot.limit == 5
    assert snapshot.offset == 3
    assert snapshot.min_age_seconds == 60.0
    assert snapshot.compute_analytics_type == "Contribution"
    assert snapshot.lineage_calculation_type == "TWR"
    assert snapshot.calculation_id_contains == "calc"
    assert snapshot.durable_metadata_store == durability_status
    assert snapshot.compute_queue.status == "available"
    assert snapshot.compute_queue.total_count == 2
    assert snapshot.compute_queue.returned_count == 1
    assert snapshot.compute_queue.next_offset == 8
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.lineage_queue.total_count == 1
    assert snapshot.compute_items == [compute_item]
    assert snapshot.lineage_items == [lineage_item]


def test_runtime_work_item_snapshot_excludes_unselected_queue(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(
            total_count=1,
            next_offset=None,
            items=[
                ComputeQueueInspectionItem(
                    calculation_id="calc-2",
                    analytics_type="Contribution",
                    status="failed",
                    active_since_utc="2026-03-14T00:00:00Z",
                    age_seconds=90.0,
                    attempt_count=2,
                    max_attempts=3,
                    error_type="RuntimeError",
                    error_message="boom",
                )
            ],
        ),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="lineage",
        status_filter="failed",
        limit=5,
        offset=3,
        min_age_seconds=60.0,
        compute_analytics_type="Contribution",
        lineage_calculation_type="TWR",
        calculation_id_contains="calc",
    )

    compute_list.assert_not_called()
    assert snapshot.queue_filter == "lineage"
    assert snapshot.offset == 3
    assert snapshot.min_age_seconds == 60.0
    assert snapshot.compute_analytics_type == "Contribution"
    assert snapshot.lineage_calculation_type == "TWR"
    assert snapshot.calculation_id_contains == "calc"
    assert snapshot.compute_queue.status == "excluded"
    assert snapshot.compute_queue.total_count == 0


def test_runtime_work_item_snapshot_passes_reclaimable_status_filter(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(total_count=0, next_offset=None, items=[]),
    )
    lineage_list = mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        return_value=type("LineagePage", (), {"total_count": 0, "next_offset": None, "items": []})(),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="both",
        status_filter="reclaimable",
        limit=7,
        offset=2,
        min_age_seconds=30.0,
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
        calculation_id_contains="abc",
    )

    assert snapshot.status_filter == "reclaimable"
    assert compute_list.call_args.kwargs["status_filter"] == "reclaimable"
    assert lineage_list.call_args.kwargs["status_filter"] == "reclaimable"


def test_runtime_work_item_snapshot_forwards_queue_specific_filters(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(total_count=0, next_offset=None, items=[]),
    )
    lineage_list = mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        return_value=type("LineagePage", (), {"total_count": 0, "next_offset": None, "items": []})(),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="both",
        status_filter="failed",
        limit=11,
        offset=4,
        min_age_seconds=45.0,
        compute_analytics_type="Contribution",
        lineage_calculation_type="TWR",
        calculation_id_contains="calc-",
    )

    assert snapshot.compute_queue.status == "available"
    assert snapshot.lineage_queue.status == "available"
    assert compute_list.call_args.kwargs == {
        "status_filter": "failed",
        "limit": 11,
        "offset": 4,
        "min_age_seconds": 45.0,
        "analytics_type": "Contribution",
        "calculation_id_contains": "calc-",
        "now": snapshot.generated_at,
    }
    assert lineage_list.call_args.kwargs == {
        "status_filter": "failed",
        "limit": 11,
        "offset": 4,
        "min_age_seconds": 45.0,
        "calculation_type": "TWR",
        "calculation_id_contains": "calc-",
        "now": snapshot.generated_at,
    }


def test_runtime_work_item_snapshot_reports_next_offset(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(total_count=3, next_offset=2, items=[]),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        return_value=type("LineagePage", (), {"total_count": 1, "next_offset": None, "items": []})(),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="both",
        status_filter="active",
        limit=2,
        offset=0,
        min_age_seconds=0.0,
        compute_analytics_type=None,
        lineage_calculation_type=None,
        calculation_id_contains=None,
    )

    assert snapshot.compute_queue.next_offset == 2
    assert snapshot.lineage_queue.next_offset is None


def test_runtime_work_item_snapshot_ignores_lineage_storage_outage_when_metadata_is_ready(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(total_count=1, next_offset=None, items=[]),
    )
    lineage_list = mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        return_value=type("LineagePage", (), {"total_count": 0, "next_offset": None, "items": []})(),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="both",
        status_filter="active",
        limit=5,
        offset=0,
        min_age_seconds=0.0,
        compute_analytics_type=None,
        lineage_calculation_type=None,
        calculation_id_contains=None,
    )

    assert snapshot.durable_metadata_store.status == "ready"
    assert snapshot.compute_queue.status == "available"
    assert snapshot.compute_queue.total_count == 1
    assert snapshot.lineage_queue.status == "available"
    lineage_list.assert_called_once()


def test_runtime_work_item_snapshot_reports_lineage_queue_failure(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_schema_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(total_count=0, next_offset=None, items=[]),
    )
    mocker.patch(
        "app.services.runtime_work_item_service.lineage_metadata_store.list_inspection_items",
        side_effect=RuntimeError("lineage unavailable"),
    )

    snapshot = build_runtime_work_item_snapshot(
        queue_filter="both",
        status_filter="active",
        limit=5,
        offset=0,
        min_age_seconds=0.0,
        compute_analytics_type=None,
        lineage_calculation_type=None,
        calculation_id_contains=None,
    )

    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.lineage_queue.reason == LINEAGE_WORK_ITEM_READ_FAILED
