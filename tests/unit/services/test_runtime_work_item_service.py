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
        return_value=[
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
    )

    snapshot = build_runtime_work_item_snapshot(status_filter="active", limit=5)

    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "RuntimeError"
    assert snapshot.compute_items == []
    assert snapshot.lineage_queue.status == "available"
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

    snapshot = build_runtime_work_item_snapshot(status_filter="failed", limit=10)

    assert snapshot.durable_metadata_store.status == "unavailable"
    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.compute_items == []
    assert snapshot.lineage_items == []
