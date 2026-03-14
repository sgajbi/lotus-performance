from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from app.services.compute_job_store import ComputeJobStore
from app.services.lineage_metadata_store import LineageMetadataStore
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url

POSTGRES_CONCURRENCY_ROWS = 20
POSTGRES_CONCURRENCY_CLAIM_LIMIT = 10


def _calculation_id_set(records) -> set[UUID]:
    return {record.calculation_id for record in records}


def test_postgres_compute_queue_claims_are_disjoint_across_workers():
    postgres_database_url = get_postgres_database_url()
    store = ComputeJobStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()

    for row_index in range(POSTGRES_CONCURRENCY_ROWS):
        store.enqueue_job(
            calculation_id=uuid4(),
            analytics_type="ReturnsSeries",
            request_payload={"row_index": row_index},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker_a = executor.submit(
            store.lease_pending_jobs,
            worker_id="postgres-worker-a",
            limit=POSTGRES_CONCURRENCY_CLAIM_LIMIT,
            lease_seconds=60,
        )
        worker_b = executor.submit(
            store.lease_pending_jobs,
            worker_id="postgres-worker-b",
            limit=POSTGRES_CONCURRENCY_CLAIM_LIMIT,
            lease_seconds=60,
        )
        claimed_by_a = worker_a.result()
        claimed_by_b = worker_b.result()

    claim_ids_a = _calculation_id_set(claimed_by_a)
    claim_ids_b = _calculation_id_set(claimed_by_b)

    assert len(claimed_by_a) == POSTGRES_CONCURRENCY_CLAIM_LIMIT
    assert len(claimed_by_b) == POSTGRES_CONCURRENCY_CLAIM_LIMIT
    assert claim_ids_a.isdisjoint(claim_ids_b)
    assert store.lease_pending_jobs(worker_id="postgres-worker-c", limit=1, lease_seconds=60) == []


def test_postgres_lineage_claims_are_disjoint_across_workers():
    postgres_database_url = get_postgres_database_url()
    store = LineageMetadataStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()

    for row_index in range(POSTGRES_CONCURRENCY_ROWS):
        store.enqueue_lineage_payload(
            calculation_id=uuid4(),
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"row_index": str(row_index)},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker_a = executor.submit(
            store.lease_pending_payloads,
            worker_id="postgres-lineage-a",
            limit=POSTGRES_CONCURRENCY_CLAIM_LIMIT,
            lease_seconds=60,
        )
        worker_b = executor.submit(
            store.lease_pending_payloads,
            worker_id="postgres-lineage-b",
            limit=POSTGRES_CONCURRENCY_CLAIM_LIMIT,
            lease_seconds=60,
        )
        claimed_by_a = worker_a.result()
        claimed_by_b = worker_b.result()

    claim_ids_a = _calculation_id_set(claimed_by_a)
    claim_ids_b = _calculation_id_set(claimed_by_b)

    assert len(claimed_by_a) == POSTGRES_CONCURRENCY_CLAIM_LIMIT
    assert len(claimed_by_b) == POSTGRES_CONCURRENCY_CLAIM_LIMIT
    assert claim_ids_a.isdisjoint(claim_ids_b)
    assert store.lease_pending_payloads(worker_id="postgres-lineage-c", limit=1, lease_seconds=60) == []
