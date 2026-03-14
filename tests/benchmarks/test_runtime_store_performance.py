from statistics import median
from time import perf_counter
from uuid import uuid4

from app.services.compute_job_store import ComputeJobStore
from app.services.lineage_metadata_store import LineageMetadataStore

COMPUTE_QUEUE_CHARACTERIZATION_ROWS = 5_000
LINEAGE_QUEUE_CHARACTERIZATION_ROWS = 1_000
COMPUTE_QUEUE_STATS_MEDIAN_MS_BUDGET = 15.0
LINEAGE_QUEUE_STATS_MEDIAN_MS_BUDGET = 10.0


def test_compute_queue_stats_characterization_contract(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute-queue.db'}")
    store.create_schema()

    for row_index in range(COMPUTE_QUEUE_CHARACTERIZATION_ROWS):
        store.enqueue_job(
            calculation_id=uuid4(),
            analytics_type="ReturnsSeries",
            request_payload={"row_index": row_index},
        )

    timings = []
    for _ in range(10):
        start = perf_counter()
        store.get_queue_stats()
        timings.append((perf_counter() - start) * 1000)

    median_ms = median(timings)
    assert median_ms <= COMPUTE_QUEUE_STATS_MEDIAN_MS_BUDGET, (
        f"Compute queue stats median {median_ms:.2f}ms exceeded "
        f"budget {COMPUTE_QUEUE_STATS_MEDIAN_MS_BUDGET:.2f}ms "
        f"for {COMPUTE_QUEUE_CHARACTERIZATION_ROWS} jobs."
    )


def test_lineage_queue_stats_characterization_contract(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage-queue.db'}")
    store.create_schema()

    for row_index in range(LINEAGE_QUEUE_CHARACTERIZATION_ROWS):
        store.enqueue_lineage_payload(
            calculation_id=uuid4(),
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"request.json": f'{{"row_index": {row_index}}}'},
        )

    timings = []
    for _ in range(10):
        start = perf_counter()
        store.get_pending_payload_stats()
        timings.append((perf_counter() - start) * 1000)

    median_ms = median(timings)
    assert median_ms <= LINEAGE_QUEUE_STATS_MEDIAN_MS_BUDGET, (
        f"Lineage queue stats median {median_ms:.2f}ms exceeded "
        f"budget {LINEAGE_QUEUE_STATS_MEDIAN_MS_BUDGET:.2f}ms "
        f"for {LINEAGE_QUEUE_CHARACTERIZATION_ROWS} payloads."
    )
