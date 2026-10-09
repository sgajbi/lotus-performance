from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, current_thread
from time import monotonic
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.adapters.durable_schema.guards import require_managed_guards
from app.observability import tenant_id_var
from app.services import submission_fencing_service
from app.services.async_result_store import AsyncResultStore, AsyncResultTenantConflictError
from app.services.composite_metadata_store import CompositeMetadataStore, composite_fact_guard_statements
from app.services.compute_job_store import ComputeJobRegistrationStatus, ComputeJobStore
from app.services.durable_database_engine import (
    DurableDatabaseEnginePolicy,
    create_durable_database_engine,
)
from app.services.durable_schema_creation import (
    DURABLE_SCHEMA_ADVISORY_LOCK_KEY,
    create_durable_schema,
)
from app.services.execution_registry import (
    ExecutionRegistrationStatus,
    ExecutionRegistry,
    ExecutionStageStatus,
    ExecutionStatus,
)
from app.services.execution_stage_names import EXECUTION_STAGE_SUBMISSION
from app.services.lineage_metadata_store import (
    LineageMetadataStore,
    LineagePayloadLeaseOwnershipError,
    LineagePayloadModel,
    LineageStatus,
)
from app.services.source_correction_store import (
    SourceCorrectionRegistrationStatus,
    SourceCorrectionStore,
)
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
from tests.durable_schema_startup_helpers import (
    ENTRYPOINTS,
    assert_read_only_restart,
    assert_startup_refusal,
    resolved_runtime_stores,
)

POSTGRES_CONCURRENCY_ROWS = 20
POSTGRES_CONCURRENCY_CLAIM_LIMIT = 10


def test_postgres_source_refusal_worker_restart_and_public_polling(tmp_path, monkeypatch, caplog):
    from tests.source_refusal_contract_helpers import assert_durable_source_refusal

    assert_durable_source_refusal(get_postgres_database_url(), monkeypatch, tmp_path, caplog)


@pytest.mark.parametrize("status", [422, 429, 503, "timeout"])
def test_postgres_source_refusal_retry_budget_survives_restart(tmp_path, monkeypatch, status, caplog):
    from tests.source_refusal_contract_helpers import assert_retryable_source_failure

    assert_retryable_source_failure(get_postgres_database_url(), monkeypatch, status, tmp_path, caplog)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("shape", ["empty", "missing_index"])
def test_postgres_startup_refuses_without_serving_polling_allocation_or_ddl(monkeypatch, entrypoint, shape):
    with resolved_runtime_stores(get_postgres_database_url(), monkeypatch) as stores:
        assert_startup_refusal(stores, monkeypatch, entrypoint, shape)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_postgres_owner_applied_startup_and_restart_are_read_only(monkeypatch, entrypoint):
    with resolved_runtime_stores(get_postgres_database_url(), monkeypatch) as stores:
        assert_read_only_restart(stores, entrypoint)


def test_postgres_current_managed_guards_verify_without_mutation():
    from app.adapters.composite_materialization_records import MaterializationBase
    from app.adapters.durable_schema.catalog import require_metadata_schema
    from app.services.async_result_store import Base as ResultBase
    from app.services.composite_metadata_store import Base as CompositeBase
    from app.services.composite_pooled_mwr.schema import immutable_guards
    from app.services.composite_pooled_mwr.schema import metadata as pooled_metadata
    from app.services.compute_job_store import Base as ComputeBase
    from app.services.execution_registry import Base as ExecutionBase
    from app.services.lineage_metadata_store import Base as LineageBase
    from app.services.source_correction_store import Base as CorrectionBase
    from scripts.durable_schema_apply import apply_durable_schema

    database_url = get_postgres_database_url()
    # Race complete owner invocations, not ordinary workload starters. Each
    # owner must finish every named store check against the initially empty schema.
    start = Barrier(4)
    with ThreadPoolExecutor(max_workers=4) as owners:
        evidence = list(
            owners.map(
                lambda _: (start.wait(timeout=10), apply_durable_schema(database_url=database_url))[1],
                range(4),
                timeout=60,
            )
        )
    assert all(item.status == "passed" for item in evidence)
    expected_stores = {
        "ExecutionRegistry",
        "ComputeJobStore",
        "AsyncResultStore",
        "LineageMetadataStore",
        "CompositeMetadataStore",
        "SourceCorrectionStore",
        "CompositePooledMWRInputStore",
    }
    for item in evidence:
        checks = item.schema_verification_checks
        assert len(checks) == len(expected_stores)
        assert {check.store_name for check in checks} == expected_stores
        assert all(check.status == "passed" and not check.issues for check in checks)
    lineage = LineageMetadataStore(database_url)
    try:
        calculation_id = uuid4()
        lineage.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
        lineage.mark_complete(calculation_id=calculation_id, artifact_names=["retained-response.json"])
        retained = lineage.get_record(calculation_id)
        assert retained is not None and retained.status == LineageStatus.COMPLETE
        assert apply_durable_schema(database_url=database_url).status == "passed"
        assert lineage.get_record(calculation_id) == retained
    finally:
        lineage._engine.dispose()
    store = CompositeMetadataStore(database_url)
    try:
        statements: list[str] = []
        event.listen(store._engine, "before_cursor_execute", lambda _, __, sql, *args: statements.append(sql))
        with store._engine.connect() as connection:
            for base in (
                ExecutionBase,
                ComputeBase,
                ResultBase,
                LineageBase,
                CompositeBase,
                CorrectionBase,
                MaterializationBase,
            ):
                require_metadata_schema(connection, base.metadata)
            require_metadata_schema(connection, pooled_metadata)
            require_managed_guards(connection, composite_fact_guard_statements(connection.dialect))
            require_managed_guards(connection, immutable_guards(connection.dialect.name))
        assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    finally:
        store.close()


@pytest.mark.parametrize("tamper", ["disabled", "function", "event"])
def test_postgres_same_named_weak_guard_refuses_without_repair(tamper):
    store = CompositeMetadataStore(get_postgres_database_url())
    try:
        store.create_schema()
        with store._engine.begin() as connection:
            if tamper == "disabled":
                connection.exec_driver_sql(
                    "ALTER TABLE composite_member_return_facts DISABLE TRIGGER trg_composite_member_return_facts_immutable_update"
                )
            elif tamper == "function":
                connection.exec_driver_sql(
                    "CREATE OR REPLACE FUNCTION reject_composite_member_return_fact_mutation() "
                    "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"
                )
            else:
                connection.exec_driver_sql(
                    "DROP TRIGGER trg_composite_member_return_facts_immutable_update ON composite_member_return_facts"
                )
                connection.exec_driver_sql(
                    "CREATE TRIGGER trg_composite_member_return_facts_immutable_update "
                    "BEFORE INSERT ON composite_member_return_facts FOR EACH ROW "
                    "EXECUTE FUNCTION reject_composite_member_return_fact_mutation()"
                )
            statements: list[str] = []
            event.listen(connection, "before_cursor_execute", lambda _, __, sql, *args: statements.append(sql))
            with pytest.raises(DurableSchemaMigrationRequiredError) as error:
                require_managed_guards(connection, composite_fact_guard_statements(connection.dialect))
            prefix = "function:" if tamper == "function" else "trigger:"
            assert any(issue.startswith(prefix) for issue in error.value.issues)
            assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    finally:
        store.close()


@pytest.mark.parametrize("tamper", ["weakened", "not_valid", "default"])
def test_postgres_changed_check_or_default_refuses_without_repair(tamper):
    from app.adapters.composite_materialization_records import MaterializationBase
    from app.adapters.durable_schema.catalog import require_metadata_schema

    store = CompositeMetadataStore(get_postgres_database_url())
    try:
        store.create_schema()
        with store._engine.begin() as connection:
            if tamper == "default":
                connection.exec_driver_sql(
                    "ALTER TABLE composite_member_return_facts ALTER COLUMN restatement_sequence SET DEFAULT 2"
                )
                from app.services.composite_metadata_store import Base

                metadata = Base.metadata
            else:
                connection.exec_driver_sql(
                    "ALTER TABLE composite_materializations DROP CONSTRAINT ck_composite_materialization_sequence"
                )
                predicate = "restatement_sequence >= 0" if tamper == "weakened" else "restatement_sequence >= 1"
                suffix = " NOT VALID" if tamper == "not_valid" else ""
                connection.exec_driver_sql(
                    "ALTER TABLE composite_materializations ADD CONSTRAINT ck_composite_materialization_sequence "
                    f"CHECK ({predicate}){suffix}"
                )
                metadata = MaterializationBase.metadata
            with pytest.raises(DurableSchemaMigrationRequiredError) as error:
                require_metadata_schema(connection, metadata)
            prefix = {"weakened": "check:", "not_valid": "unvalidated_constraint:", "default": "default:"}[tamper]
            assert any(issue.startswith(prefix) for issue in error.value.issues)
    finally:
        store.close()


def test_postgres_failed_concurrent_unique_index_is_not_readiness():
    from app.adapters.durable_schema.catalog import require_metadata_schema

    metadata = MetaData()
    table = Table("indexed_identity", metadata, Column("identity", Integer, nullable=False))
    Index("uq_indexed_identity", table.c.identity, unique=True)
    database = create_engine(get_postgres_database_url())
    try:
        with database.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("CREATE TABLE indexed_identity (identity INTEGER NOT NULL)")
            connection.exec_driver_sql("INSERT INTO indexed_identity (identity) VALUES (1), (1)")
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX CONCURRENTLY uq_indexed_identity ON indexed_identity (identity)"
                )
            assert inspect(connection).get_indexes(table.name)[0]["unique"]
            with pytest.raises(DurableSchemaMigrationRequiredError) as error:
                require_metadata_schema(connection, metadata)
            assert "invalid_index:indexed_identity.uq_indexed_identity" in error.value.issues
            assert connection.execute(table.select()).scalars().all() == [1, 1]
    finally:
        database.dispose()


def test_postgres_legacy_lineage_lease_upgrade_preserves_pending_recovery():
    from app.adapters.durable_schema.catalog import require_metadata_schema
    from app.services.lineage_metadata_store import Base

    database_url = get_postgres_database_url()
    store = LineageMetadataStore(database_url)
    calculation_id = uuid4()
    restarted = None
    try:
        with store._engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE lineage_records (calculation_id VARCHAR(36) PRIMARY KEY, "
                "calculation_type VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, "
                "timestamp_utc TIMESTAMP WITH TIME ZONE NOT NULL, artifact_names TEXT NOT NULL, error_message TEXT)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE lineage_payloads (calculation_id VARCHAR(36) PRIMARY KEY, "
                "calculation_type VARCHAR(64) NOT NULL, request_json TEXT NOT NULL, response_json TEXT NOT NULL, "
                "details_json TEXT NOT NULL, created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL, attempt_count INTEGER NOT NULL)"
            )
            connection.execute(
                text("INSERT INTO lineage_records VALUES (:id, 'TWR', 'pending', CURRENT_TIMESTAMP, '', NULL)"),
                {"id": str(calculation_id)},
            )
            connection.execute(
                text("INSERT INTO lineage_payloads VALUES (:id, 'TWR', '{}', '{}', '{}', CURRENT_TIMESTAMP, 3)"),
                {"id": str(calculation_id)},
            )
        store.create_schema()
        with store._engine.connect() as connection:
            require_metadata_schema(connection, Base.metadata)
        store._engine.dispose()
        restarted = LineageMetadataStore(database_url)
        payload = restarted.get_payload(calculation_id)
        assert payload is not None and payload.attempt_count == 3 and payload.worker_id is None
        record = restarted.get_record(calculation_id)
        assert record is not None and record.status == LineageStatus.PENDING
        claimed = restarted.lease_pending_payload(
            calculation_id=calculation_id, worker_id="restored-lineage", lease_seconds=60
        )
        assert claimed is not None and claimed.worker_id == "restored-lineage"
        restarted.mark_complete(calculation_id, ["response.json"], worker_id="restored-lineage")
        assert restarted.get_record(calculation_id).status == LineageStatus.COMPLETE
    finally:
        store._engine.dispose()
        if restarted is not None:
            restarted._engine.dispose()


class _AcceptedSubmission(BaseModel):
    calculation_id: str
    poll_path: str


def _accepted_submission(calculation_id: UUID) -> _AcceptedSubmission:
    return _AcceptedSubmission(
        calculation_id=str(calculation_id),
        poll_path=f"/performance/executions/{calculation_id}",
    )


def _source_correction_payload(*, correction_id: str, source_revision: str) -> dict[str, str | dict[str, str]]:
    return {
        "correction_id": correction_id,
        "source_product": "portfolio_timeseries",
        "source_revision": source_revision,
        "supersedes_source_revision": "revision-1",
        "target_type": "portfolio",
        "target_id": f"PORT-{correction_id}",
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2026-01-02",
        "observed_at_utc": "2026-01-03T00:00:00+00:00",
        "correction_reason": "PostgreSQL contention contract.",
        "source_authorization": {"issuer": "lotus-core", "evidence_id": correction_id},
    }


def test_postgres_attribution_idempotency_contention_and_restart_return_one_handle(monkeypatch):
    database_url = get_postgres_database_url()
    execution_store = ExecutionRegistry(database_url)
    job_store = ComputeJobStore(database_url)
    execution_store.create_schema()
    job_store.create_schema()
    job_store.clear_all_records()
    execution_store.clear_all_records()
    monkeypatch.setattr(submission_fencing_service, "execution_registry", execution_store)
    monkeypatch.setattr(submission_fencing_service, "compute_job_store", job_store)

    calculation_ids = tuple(uuid4() for _ in range(8))
    start = Barrier(len(calculation_ids))
    request_payload = {"portfolio_id": "PORT-IDEMPOTENT", "report_end_date": "2026-09-30"}
    common = {
        "analytics_type": "Attribution",
        "portfolio_id": "PORT-IDEMPOTENT",
        "requested_window": {"report_end_date": "2026-09-30"},
        "input_fingerprint": "sha256:attribution-input",
        "calculation_hash": "sha256:attribution-calculation",
        "request_payload": request_payload,
        "offload_reason": "postgres_contention_contract",
        "accepted_response_factory": _accepted_submission,
        "requires_tenant_authority": True,
        "submission_idempotency_key_hash": "b" * 64,
        "submission_identity_fingerprint": "sha256:attribution-identity",
        "submission_contract_version": "attribution-submission-v1",
    }

    def _submit(calculation_id: UUID):
        tenant_token = tenant_id_var.set("tenant-idempotency")
        try:
            start.wait(timeout=10)
            return submission_fencing_service.register_async_submission_or_raise(
                calculation_id=calculation_id,
                **common,
            )
        finally:
            tenant_id_var.reset(tenant_token)

    with ThreadPoolExecutor(max_workers=len(calculation_ids)) as executor:
        responses = list(executor.map(_submit, calculation_ids, timeout=30))

    assert {response.status_code for response in responses} == {202}
    resolved_ids = {response.content["calculation_id"] for response in responses}
    assert len(resolved_ids) == 1
    resolved_id = UUID(resolved_ids.pop())
    execution = execution_store.get_execution(resolved_id)
    job = job_store.get_job(resolved_id)
    assert execution is not None
    assert job is not None
    assert [pending.calculation_id for pending in job_store.list_pending_jobs(limit=20)] == [resolved_id]
    assert [stage.stage_name for stage in execution.stages] == [EXECUTION_STAGE_SUBMISSION]
    assert execution.stages[0].status == ExecutionStageStatus.COMPLETE

    restarted_execution_store = ExecutionRegistry(database_url)
    restarted_job_store = ComputeJobStore(database_url)
    restarted_execution_store.create_schema()
    restarted_job_store.create_schema()
    monkeypatch.setattr(submission_fencing_service, "execution_registry", restarted_execution_store)
    monkeypatch.setattr(submission_fencing_service, "compute_job_store", restarted_job_store)
    tenant_token = tenant_id_var.set("tenant-idempotency")
    try:
        replay = submission_fencing_service.register_async_submission_or_raise(
            calculation_id=uuid4(),
            **common,
        )
    finally:
        tenant_id_var.reset(tenant_token)

    assert replay.status_code == 202
    assert replay.content["calculation_id"] == str(resolved_id)
    restarted_execution = restarted_execution_store.get_execution(resolved_id)
    assert restarted_execution is not None
    assert len(restarted_execution.stages) == 1
    assert restarted_execution.stages[0].status == ExecutionStageStatus.COMPLETE

    conflict = restarted_execution_store.register_execution(
        calculation_id=uuid4(),
        tenant_id="tenant-idempotency",
        analytics_type="Attribution",
        portfolio_id="PORT-CHANGED",
        execution_mode="async",
        requested_window={"report_end_date": "2026-09-30"},
        request_payload={"portfolio_id": "PORT-CHANGED"},
        submission_idempotency_key_hash="b" * 64,
        submission_identity_fingerprint="sha256:changed-identity",
        submission_contract_version="attribution-submission-v1",
    )
    assert conflict.status == ExecutionRegistrationStatus.CONFLICT
    assert conflict.calculation_id == resolved_id


def test_postgres_attribution_retry_preserves_binding_after_ambiguous_job_commit(monkeypatch):
    database_url = get_postgres_database_url()
    execution_store = ExecutionRegistry(database_url)
    job_store = ComputeJobStore(database_url)
    execution_store.create_schema()
    job_store.create_schema()
    job_store.clear_all_records()
    execution_store.clear_all_records()

    class _CommitThenDisconnectJobStore:
        def register_job(self, **kwargs):
            job_store.register_job(**kwargs)
            raise RuntimeError("connection lost after commit")

    monkeypatch.setattr(submission_fencing_service, "execution_registry", execution_store)
    monkeypatch.setattr(submission_fencing_service, "compute_job_store", _CommitThenDisconnectJobStore())
    original_calculation_id = uuid4()
    common = {
        "analytics_type": "Attribution",
        "portfolio_id": "PORT-AMBIGUOUS-COMMIT",
        "requested_window": {"report_end_date": "2026-09-30"},
        "input_fingerprint": "sha256:ambiguous-input",
        "calculation_hash": "sha256:ambiguous-calculation",
        "request_payload": {"portfolio_id": "PORT-AMBIGUOUS-COMMIT", "report_end_date": "2026-09-30"},
        "offload_reason": "postgres_ambiguous_commit_contract",
        "accepted_response_factory": _accepted_submission,
        "requires_tenant_authority": True,
        "submission_idempotency_key_hash": "c" * 64,
        "submission_identity_fingerprint": "sha256:ambiguous-identity",
        "submission_contract_version": "attribution-submission-v1",
    }
    tenant_token = tenant_id_var.set("tenant-ambiguous-commit")
    try:
        with pytest.raises(RuntimeError, match="connection lost after commit"):
            submission_fencing_service.register_async_submission_or_raise(
                calculation_id=original_calculation_id,
                **common,
            )
    finally:
        tenant_id_var.reset(tenant_token)

    assert execution_store.get_execution(original_calculation_id) is not None
    assert job_store.get_job(original_calculation_id) is not None

    monkeypatch.setattr(submission_fencing_service, "compute_job_store", job_store)
    tenant_token = tenant_id_var.set("tenant-ambiguous-commit")
    try:
        replay = submission_fencing_service.register_async_submission_or_raise(
            calculation_id=uuid4(),
            **common,
        )
    finally:
        tenant_id_var.reset(tenant_token)

    assert replay.status_code == 202
    assert replay.content["calculation_id"] == str(original_calculation_id)
    assert [pending.calculation_id for pending in job_store.list_pending_jobs(limit=20)] == [original_calculation_id]
    execution = execution_store.get_execution(original_calculation_id)
    assert execution is not None
    assert len(execution.stages) == 1
    assert execution.stages[0].status == ExecutionStageStatus.COMPLETE


def test_postgres_source_correction_registration_is_tenant_scoped_and_restart_durable():
    database_url = get_postgres_database_url()
    store = SourceCorrectionStore(database_url)
    store.create_schema()
    correction_id = f"pg-correction-{uuid4()}"
    payload = _source_correction_payload(correction_id=correction_id, source_revision="revision-2")

    def _register(tenant_id: str):
        worker_store = SourceCorrectionStore(database_url)
        return worker_store.register(
            tenant_id=tenant_id,
            correction_id=correction_id,
            request_fingerprint="sha256:stable",
            request_payload=payload,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        same_tenant = list(executor.map(lambda _: _register("bank-a"), range(8)))
    assert [item.status for item in same_tenant].count(SourceCorrectionRegistrationStatus.CREATED) == 1
    assert [item.status for item in same_tenant].count(SourceCorrectionRegistrationStatus.REPLAY) == 7

    foreign = _register("bank-b")
    assert foreign.status == SourceCorrectionRegistrationStatus.CREATED
    store.update(
        tenant_id="bank-a",
        correction_id=correction_id,
        state="complete",
        impacts=[{"original_calculation_id": str(uuid4()), "corrected_calculation_id": str(uuid4())}],
    )

    restarted = SourceCorrectionStore(database_url)
    bank_a = restarted.get(tenant_id="bank-a", correction_id=correction_id)
    bank_b = restarted.get(tenant_id="bank-b", correction_id=correction_id)
    assert bank_a is not None and bank_a.state == "complete" and len(bank_a.impacts) == 1
    assert bank_b is not None and bank_b.state == "recalculation_pending" and bank_b.impacts == []


def test_postgres_source_correction_conflicting_payload_loses_closed_under_contention():
    database_url = get_postgres_database_url()
    SourceCorrectionStore(database_url).create_schema()
    correction_id = f"pg-conflict-{uuid4()}"
    payload_a = _source_correction_payload(correction_id=correction_id, source_revision="revision-a")
    payload_b = _source_correction_payload(correction_id=correction_id, source_revision="revision-b")

    def _register(payload: dict[str, str | dict[str, str]], fingerprint: str):
        return SourceCorrectionStore(database_url).register(
            tenant_id="bank-contention",
            correction_id=correction_id,
            request_fingerprint=fingerprint,
            request_payload=payload,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_register, payload_a, "sha256:a"),
            executor.submit(_register, payload_b, "sha256:b"),
        ]
        results = [future.result(timeout=10) for future in futures]

    assert {result.status for result in results} == {
        SourceCorrectionRegistrationStatus.CREATED,
        SourceCorrectionRegistrationStatus.CONFLICT,
    }


def test_postgres_source_correction_revision_chain_has_one_successor_under_contention():
    database_url = get_postgres_database_url()
    store = SourceCorrectionStore(database_url)
    store.create_schema()
    target_id = f"PORT-chain-{uuid4()}"
    initial_id = f"pg-chain-initial-{uuid4()}"
    initial = _source_correction_payload(correction_id=initial_id, source_revision="revision-2")
    initial["target_id"] = target_id
    assert (
        store.register(
            tenant_id="bank-chain",
            correction_id=initial_id,
            request_fingerprint="sha256:initial",
            request_payload=initial,
        ).status
        == SourceCorrectionRegistrationStatus.CREATED
    )

    def _register_successor(label: str):
        correction_id = f"pg-chain-{label}-{uuid4()}"
        payload = _source_correction_payload(correction_id=correction_id, source_revision=f"revision-{label}")
        payload["target_id"] = target_id
        payload["observed_at_utc"] = "2026-01-04T00:00:00+00:00"
        payload["supersedes_source_revision"] = "revision-2"
        return SourceCorrectionStore(database_url).register(
            tenant_id="bank-chain",
            correction_id=correction_id,
            request_fingerprint=f"sha256:{label}",
            request_payload=payload,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(_register_successor, ("a", "b")))

    assert {result.status for result in results} == {
        SourceCorrectionRegistrationStatus.CREATED,
        SourceCorrectionRegistrationStatus.REVISION_CONFLICT,
    }


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
