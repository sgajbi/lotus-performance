from statistics import median
from time import perf_counter
from uuid import uuid4

from app.services.async_result_store import AsyncResultStore
from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry

EXECUTION_POLLING_SNAPSHOT_COUNT = 100
EXECUTION_POLLING_MEDIAN_MS_BUDGET = 20.0


def test_execution_polling_characterization_contract(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution-registry.db'}")
    compute_store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute-job.db'}")
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'async-result.db'}")
    registry.create_schema()
    compute_store.create_schema()
    result_store.create_schema()

    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PF-CHAR",
        execution_mode="async",
        requested_window={"mode": "EXPLICIT"},
    )
    for stage_name in ("submission", "retrieval", "normalization", "execution", "lineage_materialization"):
        registry.start_stage(calculation_id, stage_name)
        registry.complete_stage(calculation_id, stage_name, details={"stage_name": stage_name})
    for snapshot_index in range(EXECUTION_POLLING_SNAPSHOT_COUNT):
        registry.record_upstream_snapshot(
            calculation_id=calculation_id,
            snapshot_id=f"snapshot-{snapshot_index}",
            upstream_endpoint="portfolio_timeseries",
            source_identifier="PF-CHAR",
            as_of_date="2026-02-25",
            request_fingerprint=f"request-{snapshot_index}",
            response_fingerprint=f"response-{snapshot_index}",
            retrieval_status="complete",
            paging_metadata={"page": snapshot_index},
        )
    compute_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-CHAR"},
    )
    compute_store.mark_complete(calculation_id, response_payload={"status": "complete"})
    result_store.record_success(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        response_payload={"status": "complete"},
    )

    timings = []
    for _ in range(20):
        start = perf_counter()
        registry.get_execution(calculation_id)
        compute_store.get_job(calculation_id)
        result_store.get_result(calculation_id)
        timings.append((perf_counter() - start) * 1000)

    median_ms = median(timings)
    assert median_ms <= EXECUTION_POLLING_MEDIAN_MS_BUDGET, (
        f"Execution polling median {median_ms:.2f}ms exceeded "
        f"budget {EXECUTION_POLLING_MEDIAN_MS_BUDGET:.2f}ms "
        f"with {EXECUTION_POLLING_SNAPSHOT_COUNT} upstream snapshots."
    )
