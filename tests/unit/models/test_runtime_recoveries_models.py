from datetime import UTC, datetime

from app.models.runtime_recoveries import build_runtime_recoveries_response
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.runtime_recovery_service import RuntimeRecoveryQueueState, RuntimeRecoverySnapshot


def test_build_runtime_recoveries_response_serializes_snapshot():
    snapshot = RuntimeRecoverySnapshot(
        generated_at=datetime(2026, 3, 14, 0, 0, tzinfo=UTC),
        queue_filter="both",
        limit=5,
        offset=0,
        calculation_id_contains="calc",
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
        durable_metadata_store=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        compute_queue=RuntimeRecoveryQueueState(status="available", reason=None, total_count=1, returned_count=1),
        lineage_queue=RuntimeRecoveryQueueState(status="available", reason=None, total_count=1, returned_count=1),
        compute_recoveries=[
            type(
                "ComputeRecovery",
                (),
                {
                    "calculation_id": "calc-1",
                    "analytics_type": "ReturnsSeries",
                    "recovery_kind": "retryable_failure",
                    "recovered_at_utc": "2026-03-14T00:00:00Z",
                    "attempt_count": 1,
                    "error_type": "RuntimeError",
                },
            )()
        ],
        lineage_recoveries=[
            type(
                "LineageRecovery",
                (),
                {
                    "calculation_id": "lineage-1",
                    "calculation_type": "TWR",
                    "recovery_kind": "retryable_materialization_failure",
                    "recovered_at_utc": "2026-03-14T00:00:01Z",
                    "attempt_count": 2,
                },
            )()
        ],
    )

    response = build_runtime_recoveries_response(snapshot)

    assert response.queue_filter == "both"
    assert response.compute_queue.total_count == 1
    assert response.compute_recoveries[0].calculation_id == "calc-1"
    assert response.compute_recoveries[0].execution_path == "/performance/executions/calc-1"
    assert response.compute_recoveries[0].lineage_path == "/performance/lineage/calc-1"
    assert response.lineage_recoveries[0].calculation_id == "lineage-1"
    assert response.lineage_recoveries[0].execution_path == "/performance/executions/lineage-1"
    assert response.lineage_recoveries[0].lineage_path == "/performance/lineage/lineage-1"
