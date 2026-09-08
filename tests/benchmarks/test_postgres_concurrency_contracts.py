from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, MetaData, String, Table, inspect, text

from app.services.async_result_store import AsyncResultStore, AsyncResultTenantConflictError
from app.services.compute_job_store import ComputeJobRegistrationStatus, ComputeJobStore
from app.services.durable_database_engine import (
    DurableDatabaseEnginePolicy,
    create_durable_database_engine,
)
from app.services.durable_schema_creation import (
    DURABLE_SCHEMA_ADVISORY_LOCK_KEY,
    create_durable_schema,
)
from app.services.execution_registry import ExecutionRegistrationStatus, ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url

POSTGRES_CONCURRENCY_ROWS = 20
POSTGRES_CONCURRENCY_CLAIM_LIMIT = 10


def test_postgres_schema_creator_waits_past_configured_lock_timeout():
    """A healthy slow bootstrap must make the next starter wait, not crash."""
    postgres_database_url = get_postgres_database_url()
    policy = DurableDatabaseEnginePolicy(
        connect_timeout_seconds=3,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        pool_recycle_seconds=300,
        statement_timeout_ms=5_000,
        lock_timeout_ms=100,
        sqlite_busy_timeout_ms=5_000,
    )
    lock_holder_engine = create_durable_database_engine(postgres_database_url, policy=policy)
    schema_creator_engine = create_durable_database_engine(postgres_database_url, policy=policy)
    holder_ready = Event()
    upgrade_lock_states: list[bool] = []
    metadata = MetaData()
    Table("schema_lock_timeout_probe", metadata, Column("probe_id", String(16), primary_key=True))

    def _hold_schema_lock() -> None:
        with lock_holder_engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": DURABLE_SCHEMA_ADVISORY_LOCK_KEY},
            )
            holder_ready.set()
            connection.execute(text("SELECT pg_sleep(0.3)"))

    def _prove_upgrade_keeps_lock(_connection) -> None:  # type: ignore[no-untyped-def]
        with lock_holder_engine.connect() as observer:
            acquired = observer.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": DURABLE_SCHEMA_ADVISORY_LOCK_KEY},
            ).scalar_one()
            upgrade_lock_states.append(bool(acquired))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            holder = executor.submit(_hold_schema_lock)
            assert holder_ready.wait(timeout=3), "lock holder did not acquire the schema advisory lock"
            started_at = monotonic()
            creator = executor.submit(
                create_durable_schema,
                schema_creator_engine,
                metadata,
                schema_upgrades=(_prove_upgrade_keeps_lock,),
            )
            creator.result(timeout=5)
            waited_seconds = monotonic() - started_at
            holder.result(timeout=5)

        assert waited_seconds >= 0.2
        assert upgrade_lock_states == [False], "store-specific DDL ran after the shared lock was released"
        assert inspect(schema_creator_engine).has_table("schema_lock_timeout_probe")
    finally:
        lock_holder_engine.dispose()
        schema_creator_engine.dispose()


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
            tenant_id="tenant-test",
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


def test_postgres_tenant_identity_survives_contention_and_store_restart():
    postgres_database_url = get_postgres_database_url()
    job_store = ComputeJobStore(postgres_database_url)
    execution_store = ExecutionRegistry(postgres_database_url)
    result_store = AsyncResultStore(postgres_database_url)
    job_store.create_schema()
    execution_store.create_schema()
    result_store.create_schema()
    result_store.clear_all_records()
    job_store.clear_all_records()
    execution_store.clear_all_records()
    calculation_id = uuid4()

    def _register(tenant_id: str):
        return job_store.register_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            tenant_id=tenant_id,
            request_payload={"portfolio_id": "SHARED"},
            max_attempts=2,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        registrations = {
            tenant_id: future.result(timeout=5)
            for tenant_id, future in {
                tenant_id: executor.submit(_register, tenant_id) for tenant_id in ("tenant-a", "tenant-b")
            }.items()
        }

    owners = [
        tenant_id
        for tenant_id, result in registrations.items()
        if result.status == ComputeJobRegistrationStatus.CREATED
    ]
    conflicts = [
        tenant_id
        for tenant_id, result in registrations.items()
        if result.status == ComputeJobRegistrationStatus.CONFLICT
    ]
    assert len(owners) == 1
    assert len(conflicts) == 1
    owner, other = owners[0], conflicts[0]

    execution_registration = execution_store.register_execution(
        calculation_id=calculation_id,
        tenant_id=owner,
        analytics_type="ReturnsSeries",
        portfolio_id="SHARED",
        execution_mode="async",
    )
    assert execution_registration.status == ExecutionRegistrationStatus.CREATED
    assert (
        execution_store.register_execution(
            calculation_id=calculation_id,
            tenant_id=other,
            analytics_type="ReturnsSeries",
            portfolio_id="SHARED",
            execution_mode="async",
        ).status
        == ExecutionRegistrationStatus.CONFLICT
    )
    result_store.record_success(
        calculation_id=calculation_id,
        tenant_id=owner,
        analytics_type="ReturnsSeries",
        response_payload={"owner": owner},
    )
    with pytest.raises(AsyncResultTenantConflictError):
        result_store.record_failure(
            calculation_id=calculation_id,
            tenant_id=other,
            analytics_type="ReturnsSeries",
            error_message="must not overwrite",
        )

    restarted_jobs = ComputeJobStore(postgres_database_url)
    restarted_results = AsyncResultStore(postgres_database_url)
    assert restarted_jobs.get_job_for_tenant(calculation_id, tenant_id=owner) is not None
    assert restarted_jobs.get_job_for_tenant(calculation_id, tenant_id=other) is None
    assert restarted_results.get_result_for_tenant(calculation_id, tenant_id=owner).response_payload == {"owner": owner}
    assert restarted_results.get_result_for_tenant(calculation_id, tenant_id=other) is None


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
