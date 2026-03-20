from datetime import UTC, datetime

from app.models.runtime_recoveries import build_runtime_recoveries_response
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.operator_navigation_service import build_operator_navigation_links
from app.services.runtime_recovery_service import RuntimeRecoveryQueueState, RuntimeRecoverySnapshot


def test_build_runtime_recoveries_response_serializes_snapshot():
    snapshot = RuntimeRecoverySnapshot(
        generated_at=datetime(2026, 3, 14, 0, 0, tzinfo=UTC),
        queue_filter="both",
        limit=5,
        offset=0,
        recovered_after=datetime(2026, 3, 13, 0, 0, tzinfo=UTC),
        recovered_before=datetime(2026, 3, 15, 0, 0, tzinfo=UTC),
        cursor_recovered_before=datetime(2026, 3, 14, 0, 0, tzinfo=UTC),
        cursor_calculation_id_before="calc-2",
        calculation_id_contains="calc",
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
        durable_metadata_store=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        compute_queue=RuntimeRecoveryQueueState(
            status="available",
            reason=None,
            total_count=1,
            returned_count=1,
            next_offset=1,
            next_cursor_recovered_before="2026-03-14T00:00:00Z",
            next_cursor_calculation_id_before="calc-2",
        ),
        lineage_queue=RuntimeRecoveryQueueState(
            status="available",
            reason=None,
            total_count=1,
            returned_count=1,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
        ),
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
    assert response.recovered_after == datetime(2026, 3, 13, 0, 0, tzinfo=UTC)
    assert response.recovered_before == datetime(2026, 3, 15, 0, 0, tzinfo=UTC)
    assert response.cursor_recovered_before == datetime(2026, 3, 14, 0, 0, tzinfo=UTC)
    assert response.cursor_calculation_id_before == "calc-2"
    assert response.compute_queue.total_count == 1
    assert response.compute_queue.next_offset == 1
    assert response.compute_queue.next_cursor_recovered_before == datetime(2026, 3, 14, 0, 0, tzinfo=UTC)
    assert response.compute_queue.next_cursor_calculation_id_before == "calc-2"
    assert response.compute_recoveries[0].calculation_id == "calc-1"
    assert response.compute_recoveries[0].execution_path == "/performance/executions/calc-1"
    assert response.compute_recoveries[0].lineage_path == "/performance/lineage/calc-1"
    assert response.compute_recoveries[0].result_path == "/integration/returns/series/results/calc-1"
    assert response.lineage_recoveries[0].calculation_id == "lineage-1"
    assert response.lineage_recoveries[0].execution_path == "/performance/executions/lineage-1"
    assert response.lineage_recoveries[0].lineage_path == "/performance/lineage/lineage-1"
    assert response.lineage_recoveries[0].result_path == "/performance/twr/results/lineage-1"


def test_operator_navigation_links_support_twr_and_benchmark_recovery_results():
    twr_links = build_operator_navigation_links("recovery-twr", workflow_type="TWR")
    benchmark_links = build_operator_navigation_links("recovery-bmk", workflow_type="BENCHMARK")

    assert twr_links.result_path == "/performance/twr/results/recovery-twr"
    assert benchmark_links.result_path == "/performance/benchmark/results/recovery-bmk"
