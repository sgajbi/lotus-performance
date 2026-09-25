from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, current_thread
from time import monotonic
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, MetaData, String, Table, event, inspect, text

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
from app.services.execution_registry import ExecutionRegistrationStatus, ExecutionRegistry, ExecutionStatus
from app.services.lineage_metadata_store import (
    LineageMetadataStore,
    LineagePayloadLeaseOwnershipError,
    LineagePayloadModel,
    LineageStatus,
)
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


def test_postgres_execution_cancellation_commits_before_late_lineage_completion():
    postgres_database_url = get_postgres_database_url()
    store = ExecutionRegistry(postgres_database_url)
    store.create_schema()
    store.clear_all_records()
    calculation_id = uuid4()
    store.create_execution(
        calculation_id=calculation_id,
        analytics_type="WORKSPACE_SUMMARY",
        portfolio_id="PORT-CANCELLED",
    )
    store.mark_running(calculation_id)
    store.start_stage(calculation_id, "lineage_materialization")
    completion_write_reached = Event()
    release_completion = Event()

    def _pause_completion_before_conditional_update(_conn, _cursor, statement, *_args):
        if current_thread().name.startswith("execution-completer") and statement.lstrip().lower().startswith(
            "update analytics_execution set"
        ):
            completion_write_reached.set()
            assert release_completion.wait(timeout=5), "completion write was not released"

    event.listen(store._engine, "before_cursor_execute", _pause_completion_before_conditional_update)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="execution-completer") as completer:
            completion = completer.submit(
                store.complete_stage_and_execution,
                calculation_id,
                "lineage_materialization",
                {"artifact_names": ["response.json"]},
            )
            assert completion_write_reached.wait(timeout=5), "completion did not reach its conditional update"
            store.mark_failed(calculation_id, "Workspace summary calculation cancelled.")
            cancelled = store.get_execution(calculation_id)
            assert cancelled is not None
            assert cancelled.status == ExecutionStatus.FAILED
            release_completion.set()
            assert completion.result(timeout=5) is False
    finally:
        release_completion.set()
        event.remove(store._engine, "before_cursor_execute", _pause_completion_before_conditional_update)

    record = store.get_execution(calculation_id)
    assert record is not None
    assert record.status == ExecutionStatus.FAILED
    assert record.error_message == "Workspace summary calculation cancelled."


def test_postgres_lineage_cancellation_fences_waiting_completion():
    postgres_database_url = get_postgres_database_url()
    store = LineageMetadataStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()
    calculation_id = uuid4()
    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="WORKSPACE_SUMMARY",
        request_json="{}",
        response_json="{}",
        details={"response.json": "{}"},
    )
    assert (
        store.lease_pending_payload(
            calculation_id=calculation_id,
            worker_id="late-lineage-worker",
            lease_seconds=60,
        )
        is not None
    )
    cancellation_write_finished = Event()
    release_cancellation = Event()
    completion_lock_attempted = Event()

    def _pause_cancellation_after_record_update(_conn, _cursor, statement, *_args):
        if current_thread().name.startswith("lineage-canceller") and statement.lstrip().lower().startswith(
            "update lineage_records set"
        ):
            cancellation_write_finished.set()
            assert release_cancellation.wait(timeout=5), "lineage cancellation transaction was not released"

    def _notice_completion_record_lock(_conn, _cursor, statement, *_args):
        normalized_statement = " ".join(statement.lstrip().lower().split())
        if (
            current_thread().name.startswith("lineage-completer")
            and normalized_statement.startswith("select lineage_records")
            and "for update" in normalized_statement
        ):
            completion_lock_attempted.set()

    event.listen(store._engine, "after_cursor_execute", _pause_cancellation_after_record_update)
    event.listen(store._engine, "before_cursor_execute", _notice_completion_record_lock)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="lineage-canceller") as canceller,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="lineage-completer") as completer,
        ):
            cancellation = canceller.submit(
                store.mark_failed_if_present,
                calculation_id,
                "Workspace summary calculation cancelled.",
            )
            assert cancellation_write_finished.wait(timeout=5), "lineage cancellation did not update its record"
            completion = completer.submit(
                store.mark_complete,
                calculation_id,
                ["response.json"],
                worker_id="late-lineage-worker",
            )
            assert completion_lock_attempted.wait(timeout=5), "lineage completion did not attempt its record lock"
            release_cancellation.set()
            assert cancellation.result(timeout=5) is True
            with pytest.raises(LineagePayloadLeaseOwnershipError):
                completion.result(timeout=5)
    finally:
        release_cancellation.set()
        event.remove(store._engine, "after_cursor_execute", _pause_cancellation_after_record_update)
        event.remove(store._engine, "before_cursor_execute", _notice_completion_record_lock)

    record = store.get_record(calculation_id)
    assert record is not None
    assert record.status == LineageStatus.FAILED
    assert record.error_message == "Workspace summary calculation cancelled."
    payload = store.get_payload(calculation_id)
    assert payload is not None
    assert payload.worker_id is None


def test_postgres_lineage_completion_rechecks_lease_expiry_before_update():
    postgres_database_url = get_postgres_database_url()
    store = LineageMetadataStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()
    calculation_id = uuid4()
    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="WORKSPACE_SUMMARY",
        request_json="{}",
        response_json="{}",
        details={"response.json": "{}"},
    )
    assert (
        store.lease_pending_payload(
            calculation_id=calculation_id,
            worker_id="expiring-lineage-worker",
            lease_seconds=60,
        )
        is not None
    )
    completion_write_reached = Event()
    release_completion = Event()

    def _pause_completion_before_conditional_update(_conn, _cursor, statement, *_args):
        if current_thread().name.startswith("expiring-lineage-completer") and statement.lstrip().lower().startswith(
            "update lineage_records set"
        ):
            completion_write_reached.set()
            assert release_completion.wait(timeout=5), "lineage completion write was not released"

    event.listen(store._engine, "before_cursor_execute", _pause_completion_before_conditional_update)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="expiring-lineage-completer") as completer:
            completion = completer.submit(
                store.mark_complete,
                calculation_id,
                ["response.json"],
                worker_id="expiring-lineage-worker",
            )
            assert completion_write_reached.wait(timeout=5), "lineage completion did not reach its update"
            with store._session() as session:
                payload = session.get(LineagePayloadModel, str(calculation_id))
                assert payload is not None
                payload.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
            release_completion.set()
            with pytest.raises(LineagePayloadLeaseOwnershipError, match="lease loss"):
                completion.result(timeout=5)
    finally:
        release_completion.set()
        event.remove(store._engine, "before_cursor_execute", _pause_completion_before_conditional_update)

    reclaimed = store.lease_pending_payload(
        calculation_id=calculation_id,
        worker_id="replacement-lineage-worker",
        lease_seconds=60,
    )
    assert reclaimed is not None
    assert reclaimed.worker_id == "replacement-lineage-worker"
    record = store.get_record(calculation_id)
    assert record is not None
    assert record.status == LineageStatus.PENDING


@pytest.mark.parametrize("reclaim_method", ["single", "batch"])
def test_postgres_lineage_completion_serializes_against_expired_reclaim(reclaim_method: str):
    postgres_database_url = get_postgres_database_url()
    store = LineageMetadataStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()
    calculation_id = uuid4()
    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="WORKSPACE_SUMMARY",
        request_json="{}",
        response_json="{}",
        details={"response.json": "{}"},
    )
    assert (
        store.lease_pending_payload(
            calculation_id=calculation_id,
            worker_id="completing-lineage-worker",
            lease_seconds=60,
        )
        is not None
    )
    completion_write_finished = Event()
    release_completion = Event()

    def _pause_completion_after_conditional_update(_conn, _cursor, statement, *_args):
        if current_thread().name.startswith("serialized-lineage-completer") and statement.lstrip().lower().startswith(
            "update lineage_records set"
        ):
            completion_write_finished.set()
            assert release_completion.wait(timeout=5), "lineage completion transaction was not released"

    event.listen(store._engine, "after_cursor_execute", _pause_completion_after_conditional_update)
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="serialized-lineage-completer") as completer:
            completion = completer.submit(
                store.mark_complete,
                calculation_id,
                ["response.json"],
                worker_id="completing-lineage-worker",
            )
            assert completion_write_finished.wait(timeout=5), "lineage completion did not finish its update"
            with store._session() as session:
                payload = session.get(LineagePayloadModel, str(calculation_id))
                assert payload is not None
                payload.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
            if reclaim_method == "single":
                overlapping_reclaim = completer.submit(
                    store.lease_pending_payload,
                    calculation_id=calculation_id,
                    worker_id="replacement-lineage-worker",
                    lease_seconds=60,
                )
                assert overlapping_reclaim.result(timeout=5) is None
            else:
                overlapping_reclaim = completer.submit(
                    store.lease_pending_payloads,
                    worker_id="replacement-lineage-worker",
                    limit=10,
                    lease_seconds=60,
                )
                assert overlapping_reclaim.result(timeout=5) == []
            release_completion.set()
            assert completion.result(timeout=5) is None
    finally:
        release_completion.set()
        event.remove(store._engine, "after_cursor_execute", _pause_completion_after_conditional_update)

    assert (
        store.lease_pending_payload(
            calculation_id=calculation_id,
            worker_id="replacement-lineage-worker",
            lease_seconds=60,
        )
        is None
    )
    record = store.get_record(calculation_id)
    assert record is not None
    assert record.status == LineageStatus.COMPLETE
    payload = store.get_payload(calculation_id)
    assert payload is not None
    assert payload.worker_id == "completing-lineage-worker"


@pytest.mark.parametrize("reclaim_method", ["single", "batch"])
def test_postgres_expired_reclaim_fences_waiting_completion(reclaim_method: str):
    postgres_database_url = get_postgres_database_url()
    store = LineageMetadataStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()
    calculation_id = uuid4()
    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="WORKSPACE_SUMMARY",
        request_json="{}",
        response_json="{}",
        details={"response.json": "{}"},
    )
    assert (
        store.lease_pending_payload(
            calculation_id=calculation_id,
            worker_id="expired-lineage-worker",
            lease_seconds=60,
        )
        is not None
    )
    with store._session() as session:
        payload = session.get(LineagePayloadModel, str(calculation_id))
        assert payload is not None
        payload.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)

    reclaim_write_finished = Event()
    release_reclaim = Event()
    completion_lock_attempted = Event()

    def _pause_reclaim_after_fence(_conn, _cursor, statement, *_args):
        normalized_statement = " ".join(statement.lstrip().lower().split())
        is_single_reclaim = (
            reclaim_method == "single"
            and normalized_statement.startswith("select lineage_payloads")
            and "for update" in normalized_statement
        )
        is_batch_reclaim = reclaim_method == "batch" and normalized_statement.startswith(
            "update lineage_payloads as payload"
        )
        if current_thread().name.startswith("reclaim-first") and (is_single_reclaim or is_batch_reclaim):
            reclaim_write_finished.set()
            assert release_reclaim.wait(timeout=5), "lineage reclaim transaction was not released"

    def _notice_completion_record_lock(_conn, _cursor, statement, *_args):
        normalized_statement = " ".join(statement.lstrip().lower().split())
        if (
            current_thread().name.startswith("reclaim-fenced-completer")
            and normalized_statement.startswith("select lineage_records")
            and "for update" in normalized_statement
        ):
            completion_lock_attempted.set()

    event.listen(store._engine, "after_cursor_execute", _pause_reclaim_after_fence)
    event.listen(store._engine, "before_cursor_execute", _notice_completion_record_lock)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="reclaim-first") as reclaimer,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="reclaim-fenced-completer") as completer,
        ):
            if reclaim_method == "single":
                reclaim = reclaimer.submit(
                    store.lease_pending_payload,
                    calculation_id=calculation_id,
                    worker_id="replacement-lineage-worker",
                    lease_seconds=60,
                )
            else:
                reclaim = reclaimer.submit(
                    store.lease_pending_payloads,
                    worker_id="replacement-lineage-worker",
                    limit=10,
                    lease_seconds=60,
                )
            assert reclaim_write_finished.wait(timeout=5), "lineage reclaimer did not acquire its durable fence"
            completion = completer.submit(
                store.mark_complete,
                calculation_id,
                ["response.json"],
                worker_id="expired-lineage-worker",
            )
            assert completion_lock_attempted.wait(timeout=5), "lineage completion did not attempt its record lock"
            release_reclaim.set()
            reclaimed = reclaim.result(timeout=5)
            if reclaim_method == "single":
                assert reclaimed is not None
                assert reclaimed.worker_id == "replacement-lineage-worker"
            else:
                assert [payload.worker_id for payload in reclaimed] == ["replacement-lineage-worker"]
            with pytest.raises(LineagePayloadLeaseOwnershipError, match="owner mismatch"):
                completion.result(timeout=5)
    finally:
        release_reclaim.set()
        event.remove(store._engine, "after_cursor_execute", _pause_reclaim_after_fence)
        event.remove(store._engine, "before_cursor_execute", _notice_completion_record_lock)

    record = store.get_record(calculation_id)
    assert record is not None
    assert record.status == LineageStatus.PENDING
    payload = store.get_payload(calculation_id)
    assert payload is not None
    assert payload.worker_id == "replacement-lineage-worker"
