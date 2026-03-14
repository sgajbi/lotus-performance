from app.services.compute_job_store import ComputeQueueInspectionItem, ComputeQueueInspectionPage
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageQueueInspectionItem
from app.services.runtime_work_item_service import build_runtime_work_item_snapshot


def test_runtime_work_item_snapshot_reports_partial_queue_failure(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_store_ready",
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
        calculation_id_contains=None,
    )

    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "RuntimeError"
    assert snapshot.compute_queue.total_count == 0
    assert snapshot.compute_items == []
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.lineage_queue.total_count == 1
    assert snapshot.lineage_queue.returned_count == 1
    assert len(snapshot.lineage_items) == 1


def test_runtime_work_item_snapshot_reports_unavailable_when_durable_store_is_down(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_store_ready",
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


def test_runtime_work_item_snapshot_excludes_unselected_queue(mocker):
    mocker.patch(
        "app.services.runtime_work_item_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    compute_list = mocker.patch(
        "app.services.runtime_work_item_service.compute_job_store.list_inspection_items",
        return_value=ComputeQueueInspectionPage(
            total_count=1,
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
