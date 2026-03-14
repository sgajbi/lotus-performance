from datetime import UTC, datetime

from app.models.runtime_work_items import build_runtime_work_items_response
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.runtime_work_item_service import RuntimeWorkItemQueueState, RuntimeWorkItemSnapshot


def test_build_runtime_work_items_response_serializes_operator_navigation_links():
    snapshot = RuntimeWorkItemSnapshot(
        generated_at=datetime(2026, 3, 14, 0, 0, tzinfo=UTC),
        queue_filter="both",
        status_filter="active",
        limit=5,
        offset=0,
        min_age_seconds=0.0,
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
        calculation_id_contains="calc",
        durable_metadata_store=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        compute_queue=RuntimeWorkItemQueueState(status="available", reason=None, total_count=1, returned_count=1),
        lineage_queue=RuntimeWorkItemQueueState(status="available", reason=None, total_count=1, returned_count=1),
        compute_items=[
            type(
                "ComputeWorkItem",
                (),
                {
                    "calculation_id": "calc-1",
                    "analytics_type": "ReturnsSeries",
                    "status": "pending",
                    "active_since_utc": "2026-03-14T00:00:00Z",
                    "age_seconds": 60.0,
                    "attempt_count": 1,
                    "max_attempts": 3,
                    "error_type": None,
                    "error_message": None,
                },
            )()
        ],
        lineage_items=[
            type(
                "LineageWorkItem",
                (),
                {
                    "calculation_id": "lineage-1",
                    "calculation_type": "TWR",
                    "status": "pending",
                    "active_since_utc": "2026-03-14T00:00:01Z",
                    "age_seconds": 30.0,
                    "attempt_count": 2,
                    "error_message": None,
                },
            )()
        ],
    )

    response = build_runtime_work_items_response(snapshot)

    assert response.compute_items[0].execution_path == "/performance/executions/calc-1"
    assert response.compute_items[0].lineage_path == "/performance/lineage/calc-1"
    assert response.lineage_items[0].execution_path == "/performance/executions/lineage-1"
    assert response.lineage_items[0].lineage_path == "/performance/lineage/lineage-1"
