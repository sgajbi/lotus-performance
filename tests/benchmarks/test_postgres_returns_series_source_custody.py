"""Real PostgreSQL source custody contracts; no filesystem durability claims."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.services.compute_job_store import ComputeJobLeaseOwnershipError, ComputeJobStatus, ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore, LineagePayloadLeaseOwnershipError
from app.services.returns_series_source.custody import (
    SourceCustodyClaim,
    SourceCustodyConflict,
    SourceMaterializationPayload,
)
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url


@pytest.fixture
def stores():
    database_url = get_postgres_database_url()
    with ExitStack() as owners:
        result = []
        for kind in (ExecutionRegistry, ComputeJobStore, LineageMetadataStore):
            store = kind(database_url)
            owners.callback(store._engine.dispose)
            store.create_schema()
            result.append(store)
        yield tuple(result)


def frozen(stores, *, compute=False):
    execution, jobs, _ = stores
    identifier = uuid4()
    execution.register_execution(
        calculation_id=identifier,
        analytics_type="ReturnsSeries",
        tenant_id="tenant-source",
        portfolio_id="portfolio",
        execution_mode="async" if compute else "sync",
        requested_window={},
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )
    claim = SourceCustodyClaim(identifier, "tenant-source", "inline-one", 0)
    if compute:
        jobs.register_job(
            calculation_id=identifier,
            tenant_id=claim.tenant_id,
            analytics_type="ReturnsSeries",
            request_payload={},
            max_attempts=3,
        )
        jobs.lease_pending_jobs(worker_id="queue", limit=1, lease_seconds=120)
        jobs.mark_running_acquired(
            identifier, current_worker_id="queue", acquisition_worker_id="compute-one", lease_seconds=120
        )
        claim = SourceCustodyClaim(identifier, claim.tenant_id, "compute-one", 1)
    (jobs if compute else execution).select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    return claim


def queue_source(owner, claim):
    owner.select_returns_series_source_root(
        claim=claim, root_digest=None, materialization=SourceMaterializationPayload("{}", '{"return":"0.09"}')
    )


def complete_manifest(lineage, claim, payload, *, digest="b" * 64):
    lineage.mark_complete(
        claim.calculation_id,
        ["source-manifest.json"],
        worker_id=payload.worker_id,
        expected_attempt_count=payload.attempt_count,
        source_root_digest="a" * 64,
        source_manifest_digest=digest,
        source_tenant_id=claim.tenant_id,
    )


def test_postgres_frozen_inline_and_compute_attempt_authority(stores):
    execution, jobs, lineage = stores
    inline = frozen(stores)
    other = SourceCustodyClaim(inline.calculation_id, inline.tenant_id, "inline-two", 0)
    with pytest.raises(SourceCustodyConflict):
        queue_source(execution, other)
    with pytest.raises(SourceCustodyConflict):
        execution.select_returns_series_source_root(claim=other, root_digest=None, failure="must not replace owner")
    queue_source(execution, inline)
    compute = frozen(stores, compute=True)
    original = lineage.get_record(compute.calculation_id)
    assert (
        original.source_custody_state,
        original.source_root_digest,
        original.source_tenant_id,
        original.source_attempt_id,
        original.source_attempt_number,
    ) == ("frozen", "a" * 64, compute.tenant_id, "compute-one", 1)
    with jobs._engine.begin() as connection:
        connection.execute(
            text("UPDATE analytics_compute_job SET lease_expires_at_utc=clock_timestamp()-interval '1 second'")
        )
    with pytest.raises(ComputeJobLeaseOwnershipError):
        queue_source(jobs, compute)

    for mutation in (
        "UPDATE analytics_execution SET tenant_id='foreign' WHERE calculation_id=:id",
        "DELETE FROM analytics_execution WHERE calculation_id=:id",
    ):
        invalid = frozen(stores)
        with execution._engine.begin() as connection:
            connection.execute(text(mutation), {"id": str(invalid.calculation_id)})
        with pytest.raises(SourceCustodyConflict):
            queue_source(execution, invalid)
        assert lineage.get_record(invalid.calculation_id).source_custody_state == "frozen"
    assert jobs.get_job(compute.calculation_id).job_status == ComputeJobStatus.RUNNING
    assert jobs.lease_pending_jobs(worker_id="retry-queue", limit=1, lease_seconds=120) == []
    reconciled = jobs.reconcile_stale_jobs()
    assert [
        (job.calculation_id, job.previous_status, job.reconciled_status, job.attempt_count) for job in reconciled
    ] == [(compute.calculation_id, ComputeJobStatus.RUNNING, ComputeJobStatus.PENDING, 1)]
    assert jobs.get_job(compute.calculation_id).job_status == ComputeJobStatus.PENDING
    assert lineage.get_record(compute.calculation_id) == original
    leased = jobs.lease_pending_jobs(worker_id="retry-queue", limit=1, lease_seconds=120)
    assert [(job.calculation_id, job.job_status) for job in leased] == [
        (compute.calculation_id, ComputeJobStatus.LEASED)
    ]
    jobs.mark_running_acquired(
        compute.calculation_id, current_worker_id="retry-queue", acquisition_worker_id="compute-two", lease_seconds=120
    )
    retry = SourceCustodyClaim(compute.calculation_id, compute.tenant_id, "compute-two", 2)
    queue_source(jobs, retry)
    selected = lineage.get_record(compute.calculation_id)
    assert (
        selected.source_root_digest,
        selected.source_tenant_id,
        selected.source_attempt_id,
        selected.source_attempt_number,
    ) == (
        original.source_root_digest,
        original.source_tenant_id,
        original.source_attempt_id,
        original.source_attempt_number,
    )
    with pytest.raises(ComputeJobLeaseOwnershipError):
        queue_source(jobs, compute)


@pytest.mark.parametrize("table", ["analytics_execution", "analytics_compute_job", "lineage_records"])
def test_postgres_reconciliation_skips_each_locked_owner_and_then_terminalizes_once(stores, table):
    execution, jobs, lineage = stores
    claim = frozen(stores, compute=True)
    execution.mark_complete(claim.calculation_id)
    assert lineage.reconcile_stranded_source_custody(limit=1) == 0  # running compute retains authority
    jobs.mark_complete(claim.calculation_id, response_payload={"return": "0.09"}, worker_id=claim.attempt_id)
    arithmetic = execution.get_execution(claim.calculation_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with jobs._engine.begin() as owner:
            owner.execute(
                text(f"SELECT calculation_id FROM {table} WHERE calculation_id=:id FOR UPDATE"),
                {"id": str(claim.calculation_id)},
            )
            assert pool.submit(lineage.reconcile_stranded_source_custody, limit=1).result(timeout=10) == 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lineage.reconcile_stranded_source_custody, limit=1)
        second = pool.submit(lineage.reconcile_stranded_source_custody, limit=1)
        assert first.result(timeout=10) + second.result(timeout=10) == 1
    assert lineage.get_record(claim.calculation_id).source_custody_state == "failed"
    assert execution.get_execution(claim.calculation_id) == arithmetic


@pytest.mark.parametrize("winner", ["queue", "terminalization"])
def test_postgres_queue_and_terminalization_winner_is_preserved(stores, winner):
    execution, _, lineage = stores
    claim = frozen(stores)
    if winner == "terminalization":
        execution.mark_complete(claim.calculation_id)
        assert lineage.reconcile_stranded_source_custody(limit=1) == 1
        with pytest.raises(SourceCustodyConflict):
            queue_source(execution, claim)
        assert lineage.get_payload(claim.calculation_id) is None
        return
    published, release = Event(), Event()

    def hold_publication(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO lineage_payloads"):
            published.set()
            assert release.wait(10), "publication release timed out"

    event.listen(execution._engine, "after_cursor_execute", hold_publication)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(queue_source, execution, claim)
            try:
                assert published.wait(10), "queue did not reach its durable transaction"
                assert lineage.reconcile_stranded_source_custody(limit=1) == 0
            finally:
                release.set()
            future.result(timeout=10)
    finally:
        event.remove(execution._engine, "after_cursor_execute", hold_publication)
    execution.mark_complete(claim.calculation_id)
    assert lineage.reconcile_stranded_source_custody(limit=1) == 0
    assert lineage.get_payload(claim.calculation_id) is not None
    assert lineage.get_record(claim.calculation_id).source_custody_state == "pending_materialization"


def test_postgres_manifest_statement_time_lease_guard_then_current_owner_wins(stores):
    execution, _, lineage = stores
    claim = frozen(stores)
    queue_source(execution, claim)
    execution.mark_complete(claim.calculation_id)
    payload = lineage.lease_pending_payload(
        calculation_id=claim.calculation_id, worker_id="writer-one", lease_seconds=120
    )
    read, release = Event(), Event()

    def hold_after_payload_read(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT lineage_payloads."):
            read.set()
            assert release.wait(10), "lease update release timed out"

    event.listen(lineage._engine, "after_cursor_execute", hold_after_payload_read)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(complete_manifest, lineage, claim, payload)
            try:
                assert read.wait(10), "completion did not read the leased payload"
                with execution._engine.begin() as connection:
                    connection.execute(
                        text("UPDATE lineage_payloads SET lease_expires_at_utc=clock_timestamp()-interval '1 second'")
                    )
            finally:
                release.set()
            with pytest.raises(LineagePayloadLeaseOwnershipError):
                future.result(timeout=10)
    finally:
        event.remove(lineage._engine, "after_cursor_execute", hold_after_payload_read)
    assert lineage.get_record(claim.calculation_id).source_manifest_digest is None
    current = lineage.lease_pending_payload(
        calculation_id=claim.calculation_id, worker_id="writer-two", lease_seconds=120
    )
    complete_manifest(lineage, claim, current)
    with pytest.raises(LineagePayloadLeaseOwnershipError):
        complete_manifest(lineage, claim, payload, digest="c" * 64)
    assert lineage.get_record(claim.calculation_id).source_manifest_digest == "b" * 64


@pytest.mark.parametrize("winner", ["cancel", "manifest"])
def test_postgres_cancel_and_manifest_preserve_winning_custody(stores, winner):
    execution, jobs, lineage = stores
    claim = frozen(stores)
    queue_source(execution, claim)
    jobs.register_job(
        calculation_id=claim.calculation_id,
        tenant_id=claim.tenant_id,
        analytics_type="ReturnsSeries",
        request_payload={},
    )
    payload = lineage.lease_pending_payload(calculation_id=claim.calculation_id, worker_id="writer", lease_seconds=120)
    selected, release, contender = Event(), Event(), Event()
    winner_engine = lineage._engine if winner == "manifest" else jobs._engine
    loser_engine = jobs._engine if winner == "manifest" else lineage._engine

    def hold_terminal_write(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE lineage_records"):
            selected.set()
            assert release.wait(10), "terminal write release timed out"

    def observe_contender(connection, cursor, statement, parameters, context, executemany):
        contender.set()

    def cancel():
        return jobs.cancel_pending_job(claim.calculation_id, tenant_id=claim.tenant_id, reason="fixture cancellation")

    def manifest():
        complete_manifest(lineage, claim, payload)

    event.listen(winner_engine, "after_cursor_execute", hold_terminal_write)
    event.listen(loser_engine, "before_cursor_execute", observe_contender)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(manifest if winner == "manifest" else cancel)
            try:
                assert selected.wait(10), "winner did not select custody in its transaction"
                second = pool.submit(cancel if winner == "manifest" else manifest)
                assert contender.wait(10), "contender did not start its database operation"
            finally:
                release.set()
            first.result(timeout=10)
            if winner == "cancel":
                with pytest.raises(LineagePayloadLeaseOwnershipError):
                    second.result(timeout=10)
            else:
                assert second.result(timeout=10)
    finally:
        event.remove(winner_engine, "after_cursor_execute", hold_terminal_write)
        event.remove(loser_engine, "before_cursor_execute", observe_contender)
    selected = lineage.get_record(claim.calculation_id)
    assert selected.source_custody_state == ("complete" if winner == "manifest" else "failed")
    assert selected.source_root_digest == "a" * 64
