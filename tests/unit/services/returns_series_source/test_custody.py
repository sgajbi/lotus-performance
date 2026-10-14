import json
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from app.services.compute_job_store import ComputeJobLeaseOwnershipError, ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore, LineagePayloadLeaseOwnershipError
from app.services.returns_series_source.custody import (
    SourceCustodyClaim,
    SourceCustodyConflict,
    SourceMaterializationPayload,
)


@pytest.fixture
def stores(tmp_path):
    url = f"sqlite:///{tmp_path / 'custody.db'}"
    execution, jobs, lineage = ExecutionRegistry(url), ComputeJobStore(url), LineageMetadataStore(url)
    for store in (execution, jobs, lineage):
        store.create_schema()
    return execution, jobs, lineage


def register(execution, *, mode="sync"):
    calculation_id = uuid4()
    execution.register_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        tenant_id="tenant-a",
        portfolio_id="portfolio-a",
        execution_mode=mode,
        requested_window={},
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )
    return SourceCustodyClaim(calculation_id, "tenant-a", "inline-attempt", 0)


def stranded_source(stores, *, compute=False):
    execution, jobs, _ = stores
    claim = running_claim(stores) if compute else register(execution)
    owner = jobs if compute else execution
    owner.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    execution.mark_complete(claim.calculation_id)
    if compute:
        with jobs._engine.begin() as connection:
            connection.execute(text("UPDATE analytics_compute_job SET job_status='complete'"))
    return claim


@pytest.mark.parametrize("compute", [False, True])
def test_stranded_source_terminalization_preserves_identity_and_arithmetic(stores, compute):
    execution, _, lineage = stores
    claim = stranded_source(stores, compute=compute)
    arithmetic = execution.get_execution(claim.calculation_id)
    before = lineage.get_record(claim.calculation_id)
    assert lineage.reconcile_stranded_source_custody(limit=1) == 1
    after = lineage.get_record(claim.calculation_id)
    assert after.status.value == after.source_custody_state == "failed"
    assert after.source_root_digest == before.source_root_digest
    assert after.source_attempt_id == before.source_attempt_id
    assert after.source_attempt_number == before.source_attempt_number
    assert after.source_tenant_id == before.source_tenant_id
    assert after.source_manifest_digest is None
    assert execution.get_execution(claim.calculation_id) == arithmetic
    assert lineage.reconcile_stranded_source_custody(limit=1) == 0
    assert lineage.get_record(claim.calculation_id) == after


@pytest.mark.parametrize("after_scan", [False, True])
@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE analytics_execution SET tenant_id='foreign'",
        "UPDATE analytics_execution SET analytics_type='TWR'",
        "UPDATE analytics_execution SET status='running'",
        "DELETE FROM analytics_execution",
        "UPDATE analytics_compute_job SET tenant_id='foreign'",
        "UPDATE analytics_compute_job SET analytics_type='TWR'",
        "UPDATE analytics_compute_job SET job_status='pending'",
        "UPDATE analytics_compute_job SET job_status='leased'",
        "UPDATE analytics_compute_job SET job_status='running', lease_expires_at_utc='2000-01-01'",
        "UPDATE lineage_records SET source_custody_state='complete', status='complete'",
        "UPDATE lineage_records SET source_custody_state='failed', status='failed'",
        "UPDATE lineage_records SET source_custody_state=NULL",
        "UPDATE lineage_records SET source_attempt_id=NULL",
        "UPDATE lineage_records SET source_manifest_digest='selected-manifest'",
    ],
)
def test_stranded_source_refuses_lost_authority_before_and_after_scan(stores, monkeypatch, mutation, after_scan):
    _, _, lineage = stores
    claim = stranded_source(stores, compute=True)
    original = lineage._session
    scans = 0

    def change():
        with lineage._engine.begin() as connection:
            connection.execute(text(mutation))

    @contextmanager
    def changed_session():
        nonlocal scans
        scans += 1
        if scans == 2:
            change()
        with original() as session:
            yield session

    if after_scan:
        monkeypatch.setattr(lineage, "_session", changed_session)
    else:
        change()
    assert lineage.reconcile_stranded_source_custody(limit=1) == 0
    assert lineage.get_record(claim.calculation_id).error_message is None


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE lineage_records SET source_root_digest='replacement-root'",
        "UPDATE lineage_records SET source_attempt_id='replacement-attempt'",
        "UPDATE lineage_records SET source_attempt_number=2",
    ],
)
def test_stranded_source_snapshot_cannot_terminalize_replaced_identity(stores, monkeypatch, mutation):
    _, _, lineage = stores
    stranded_source(stores)
    original = lineage._session
    calls = 0

    @contextmanager
    def replaced():
        nonlocal calls
        calls += 1
        if calls == 2:
            with lineage._engine.begin() as connection:
                connection.execute(text(mutation))
        with original() as session:
            yield session

    monkeypatch.setattr(lineage, "_session", replaced)
    assert lineage.reconcile_stranded_source_custody(limit=1) == 0


@pytest.mark.parametrize("leased", [False, True])
def test_stranded_source_never_takes_queued_payload(stores, leased):
    execution, _, lineage = stores
    claim = register(execution)
    execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    execution.select_returns_series_source_root(
        claim=claim, root_digest=None, materialization=SourceMaterializationPayload("{}", "{}")
    )
    if leased:
        lineage.lease_pending_payload(calculation_id=claim.calculation_id, worker_id="materializer", lease_seconds=120)
    execution.mark_complete(claim.calculation_id)
    # Even inconsistent frozen state cannot bypass the payload-absence predicate.
    with lineage._engine.begin() as connection:
        connection.execute(text("UPDATE lineage_records SET source_custody_state='frozen'"))
    before = lineage.get_payload(claim.calculation_id)
    assert lineage.reconcile_stranded_source_custody(limit=1) == 0
    assert lineage.get_payload(claim.calculation_id) == before


def test_stranded_source_transaction_failure_rolls_back_and_next_pass_recovers(stores, monkeypatch):
    import app.services.lineage_metadata_store as module

    _, _, lineage = stores
    claim = stranded_source(stores)
    original = module._terminalize_stranded_source

    def interrupted(session, identity):
        assert original(session, identity) == 1
        raise OSError("fixture interruption before commit")

    with monkeypatch.context() as failure:
        failure.setattr(module, "_terminalize_stranded_source", interrupted)
        with pytest.raises(OSError, match="before commit"):
            lineage.reconcile_stranded_source_custody(limit=1)
    assert lineage.get_record(claim.calculation_id).source_custody_state == "frozen"
    assert lineage.reconcile_stranded_source_custody(limit=1) == 1


def test_stranded_source_batch_bound_and_invalid_limit(stores):
    _, _, lineage = stores
    for _ in range(3):
        stranded_source(stores)
    with pytest.raises(ValueError, match="positive"):
        lineage.reconcile_stranded_source_custody(limit=0)
    assert lineage.reconcile_stranded_source_custody(limit=2) == 2
    assert lineage.reconcile_stranded_source_custody(limit=2) == 1


def test_inline_root_is_immutable_and_requires_existing_matching_execution(stores):
    execution, _, lineage = stores
    claim = register(execution)
    selected = execution.select_returns_series_source_root(claim=claim, root_digest=None)
    assert selected.state == "capturing"
    frozen = execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    assert frozen.state == "frozen"
    assert execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64) == frozen
    with pytest.raises(SourceCustodyConflict):
        execution.select_returns_series_source_root(claim=claim, root_digest="b" * 64)
    with lineage._engine.connect() as connection:
        assert connection.execute(text("SELECT source_root_digest FROM lineage_records")).scalar_one() == "a" * 64


@pytest.mark.parametrize(
    "tenant,mode,attempt", [("foreign", "sync", 0), ("tenant-a", "async", 0), ("tenant-a", "sync", 1)]
)
def test_inline_refuses_foreign_tenant_async_owner_and_worker_attempt(stores, tenant, mode, attempt):
    execution, _, _ = stores
    claim = register(execution, mode=mode)
    wrong = SourceCustodyClaim(claim.calculation_id, tenant, claim.attempt_id, attempt)
    with pytest.raises(SourceCustodyConflict):
        execution.select_returns_series_source_root(claim=wrong, root_digest=None)


def test_inline_refuses_missing_execution(stores):
    execution, _, _ = stores
    with pytest.raises(SourceCustodyConflict):
        execution.select_returns_series_source_root(
            claim=SourceCustodyClaim(uuid4(), "tenant-a", "attempt", 0), root_digest=None
        )


@pytest.mark.parametrize("mutation", ["root", "tenant", "terminal", "failure", "enqueue", "complete_failure"])
def test_invalid_or_terminal_custody_cannot_select_or_enqueue(stores, mutation):
    execution, _, lineage = stores
    claim = register(execution)
    execution.select_returns_series_source_root(claim=claim, root_digest=None)
    arguments = dict(claim=claim, root_digest=None)
    if mutation == "root":
        arguments["root_digest"] = "../invalid"
    elif mutation == "enqueue":
        arguments["materialization"] = SourceMaterializationPayload("{}", "{}")
    else:
        update = {
            "complete_failure": "status='complete', source_custody_state='complete', source_root_digest='"
            + "a" * 64
            + "'",
            "tenant": "source_tenant_id='foreign'",
            "terminal": "status='complete'",
            "failure": "status='failed', source_custody_state='failed'",
        }[mutation]
        with lineage._engine.begin() as connection:
            connection.execute(text("UPDATE lineage_records SET " + update))
        if mutation == "failure":
            selected = execution.select_returns_series_source_root(**arguments)
            assert selected.state == "failed"
            arguments["root_digest"] = "a" * 64
        if mutation == "complete_failure":
            arguments["failure"] = "late failure"
    with pytest.raises(SourceCustodyConflict):
        execution.select_returns_series_source_root(**arguments)


@pytest.mark.parametrize("mutation", ["identity", "manifest", "tenant", "execution", "retry"])
def test_completion_refuses_malformed_or_lost_authority(stores, mutation):
    execution, _, lineage = stores
    claim = register(execution)
    execution.select_returns_series_source_root(
        claim=claim, root_digest="a" * 64, materialization=SourceMaterializationPayload("{}", "{}")
    )
    payload = lineage.lease_pending_payload(calculation_id=claim.calculation_id, worker_id="worker", lease_seconds=120)
    arguments = dict(
        worker_id="worker",
        source_root_digest="a" * 64,
        source_manifest_digest="b" * 64,
        source_tenant_id="tenant-a",
        expected_attempt_count=payload.attempt_count,
    )
    if mutation == "identity":
        arguments["source_root_digest"] = None
    elif mutation == "manifest":
        arguments["source_manifest_digest"] = "bad"
    elif mutation == "tenant":
        arguments["source_tenant_id"] = "foreign"
    elif mutation == "execution":
        execution.delete_execution(claim.calculation_id)
    else:
        with lineage._engine.begin() as connection:
            connection.execute(text("UPDATE lineage_records SET status='failed'"))
        with pytest.raises(LineagePayloadLeaseOwnershipError):
            lineage.retry_source_materialization(
                claim.calculation_id, worker_id="worker", expected_attempt_count=payload.attempt_count, max_attempts=3
            )
        return
    with pytest.raises(LineagePayloadLeaseOwnershipError):
        lineage.mark_complete(claim.calculation_id, [], **arguments)


def running_claim(stores):
    execution, jobs, _ = stores
    inline = register(execution, mode="async")
    jobs.register_job(
        calculation_id=inline.calculation_id,
        tenant_id=inline.tenant_id,
        analytics_type="ReturnsSeries",
        request_payload={},
    )
    jobs.lease_pending_jobs(worker_id="queue", limit=1, lease_seconds=120)
    jobs.mark_running_acquired(
        inline.calculation_id, current_worker_id="queue", acquisition_worker_id="attempt-one", lease_seconds=120
    )
    return SourceCustodyClaim(inline.calculation_id, inline.tenant_id, "attempt-one", 1)


def test_compute_selects_frozen_root_and_retry_reuses_original_identity(stores):
    _, jobs, _ = stores
    claim = running_claim(stores)
    jobs.select_returns_series_source_root(claim=claim, root_digest=None)
    selected = jobs.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    with jobs._engine.begin() as connection:
        connection.execute(text("UPDATE analytics_compute_job SET attempt_count=2, lease_owner_id='attempt-two'"))
    retry = SourceCustodyClaim(claim.calculation_id, claim.tenant_id, "attempt-two", 2)
    assert jobs.select_returns_series_source_root(claim=retry, root_digest=None) == selected
    with pytest.raises(ComputeJobLeaseOwnershipError):
        jobs.select_returns_series_source_root(claim=claim, root_digest="a" * 64)


def completed_publication(stores):
    execution, jobs, _ = stores
    claim = running_claim(stores)
    jobs.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    response = {
        "calculation_id": str(claim.calculation_id),
        "portfolio_id": "portfolio-a",
        "metadata": {"generated_at": "original"},
    }
    jobs.select_returns_series_source_root(
        claim=claim, root_digest="a" * 64, materialization=SourceMaterializationPayload("{}", json.dumps(response))
    )
    execution.retain_response_payload(claim.calculation_id, response_payload=response)
    execution.mark_complete(claim.calculation_id)
    return claim, response


def test_completed_publication_is_read_only_and_active_execution_has_no_resume(stores):
    execution, jobs, lineage = stores
    claim = running_claim(stores)
    assert jobs.load_completed_returns_series_publication(claim=claim) is None
    assert lineage.get_record(claim.calculation_id) is None
    jobs.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    response = {"calculation_id": str(claim.calculation_id), "portfolio_id": "portfolio-a"}
    jobs.select_returns_series_source_root(
        claim=claim, root_digest="a" * 64, materialization=SourceMaterializationPayload("{}", json.dumps(response))
    )
    execution.retain_response_payload(claim.calculation_id, response_payload=response)
    execution.mark_complete(claim.calculation_id)
    before = execution.get_execution(claim.calculation_id), lineage.get_record(claim.calculation_id)
    assert jobs.load_completed_returns_series_publication(claim=claim) == response
    assert before == (execution.get_execution(claim.calculation_id), lineage.get_record(claim.calculation_id))


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM lineage_records",
        "DELETE FROM lineage_payloads",
        "UPDATE lineage_records SET source_root_digest=NULL",
        "UPDATE lineage_records SET source_root_digest='bad'",
        "UPDATE lineage_records SET source_custody_state='capturing'",
        "UPDATE lineage_records SET status='failed',source_custody_state='failed'",
        "UPDATE lineage_records SET source_tenant_id='foreign'",
        "UPDATE lineage_records SET calculation_type='TWR'",
        "UPDATE lineage_records SET source_attempt_id=NULL",
        "UPDATE lineage_records SET source_attempt_number=NULL",
        "UPDATE analytics_execution SET execution_mode='sync'",
        "UPDATE analytics_execution SET tenant_id='foreign'",
        "UPDATE analytics_execution SET analytics_type='TWR'",
        "UPDATE analytics_execution SET status='failed'",
        "UPDATE analytics_execution SET response_json=NULL",
        "UPDATE analytics_execution SET response_json='{}'",
        "replace_response",
        "DELETE FROM analytics_execution",
        "UPDATE analytics_compute_job SET lease_owner_id='stale'",
        "UPDATE analytics_compute_job SET attempt_count=2",
        "UPDATE analytics_compute_job SET lease_expires_at_utc='2000-01-01'",
        "UPDATE analytics_compute_job SET tenant_id='foreign'",
        "UPDATE analytics_compute_job SET analytics_type='TWR'",
        "UPDATE analytics_compute_job SET job_status='complete'",
    ],
)
def test_completed_publication_refuses_unqualified_authority_without_mutation(stores, mutation):
    execution, jobs, lineage = stores
    claim, response = completed_publication(stores)
    with jobs._engine.begin() as connection:
        if mutation == "replace_response":
            connection.execute(
                text("UPDATE analytics_execution SET response_json=:response"),
                {"response": json.dumps({**response, "metadata": {"generated_at": "replaced"}})},
            )
        else:
            connection.execute(text(mutation))
    before = (
        execution.get_execution(claim.calculation_id),
        lineage.get_record(claim.calculation_id),
        jobs.get_job(claim.calculation_id),
    )
    with pytest.raises((SourceCustodyConflict, ComputeJobLeaseOwnershipError)):
        jobs.load_completed_returns_series_publication(claim=claim)
    assert before == (
        execution.get_execution(claim.calculation_id),
        lineage.get_record(claim.calculation_id),
        jobs.get_job(claim.calculation_id),
    )


def test_completed_publication_rechecks_statement_time_after_frozen_read(stores, monkeypatch):
    import app.services.compute_job_store as module

    _, jobs, _ = stores
    claim, _ = completed_publication(stores)
    original = module.require_existing_frozen_source

    def expire(session, **kwargs):
        selected = original(session, **kwargs)
        session.execute(text("UPDATE analytics_compute_job SET lease_expires_at_utc='2000-01-01'"))
        return selected

    monkeypatch.setattr(module, "require_existing_frozen_source", expire)
    with pytest.raises(SourceCustodyConflict, match="expired during"):
        jobs.load_completed_returns_series_publication(claim=claim)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE analytics_compute_job SET tenant_id='foreign'",
        "UPDATE analytics_compute_job SET analytics_type='TWR'",
        "UPDATE analytics_compute_job SET lease_owner_id='other'",
        "UPDATE analytics_compute_job SET attempt_count=2",
        "UPDATE analytics_compute_job SET job_status='complete'",
        "UPDATE analytics_compute_job SET lease_expires_at_utc='2000-01-01'",
        "UPDATE analytics_execution SET status='failed'",
        "DELETE FROM analytics_execution",
    ],
)
def test_compute_refuses_stale_or_foreign_claim_before_custody_write(stores, mutation):
    _, jobs, lineage = stores
    claim = running_claim(stores)
    with jobs._engine.begin() as connection:
        connection.execute(text(mutation))
    with pytest.raises((SourceCustodyConflict, ComputeJobLeaseOwnershipError)):
        jobs.select_returns_series_source_root(claim=claim, root_digest=None)
    assert lineage.get_record(claim.calculation_id) is None


@pytest.mark.parametrize("status", ["pending", "failed", "complete"])
def test_populated_legacy_schema_verify_is_read_only_and_explicit_apply_preserves_null_history(tmp_path, status):
    lineage = LineageMetadataStore(f"sqlite:///{tmp_path / 'legacy.db'}")
    calculation_id = uuid4()
    with lineage._engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE lineage_records (calculation_id VARCHAR(36) NOT NULL PRIMARY KEY, "
                "calculation_type VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, "
                "timestamp_utc DATETIME NOT NULL, artifact_names TEXT NOT NULL, error_message TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO lineage_records VALUES (:id, 'ReturnsSeries', :status, "
                "'2026-01-01 00:00:00', 'request.json', NULL)"
            ),
            {"id": str(calculation_id), "status": status},
        )
    before = [
        (column["name"], str(column["type"]), column["nullable"])
        for column in inspect(lineage._engine).get_columns("lineage_records")
    ]
    with pytest.raises(Exception, match="DURABLE_SCHEMA_MIGRATION_REQUIRED"):
        lineage.verify_schema()
    assert [
        (column["name"], str(column["type"]), column["nullable"])
        for column in inspect(lineage._engine).get_columns("lineage_records")
    ] == before
    lineage.create_schema()
    lineage.verify_schema()
    record = lineage.get_record(calculation_id)
    assert record.status.value == status and record.artifact_names == ["request.json"]
    assert record.source_custody_state is None and record.source_root_digest is None
    lineage.create_schema()
    assert lineage.get_record(calculation_id) == record


def test_inline_capture_cannot_be_replaced_or_failed_by_another_inline_attempt(stores):
    execution, _, lineage = stores
    claim = register(execution)
    execution.select_returns_series_source_root(claim=claim, root_digest=None)
    other = SourceCustodyClaim(claim.calculation_id, claim.tenant_id, "other-inline-attempt", 0)
    for arguments in ({"root_digest": None}, {"root_digest": "a" * 64}, {"root_digest": None, "failure": "stale"}):
        with pytest.raises(SourceCustodyConflict):
            execution.select_returns_series_source_root(claim=other, **arguments)
    assert lineage.get_record(claim.calculation_id).source_attempt_id == claim.attempt_id


@pytest.mark.parametrize("state", ["frozen", "pending_materialization"])
@pytest.mark.parametrize("operation", ["fail", "enqueue"])
def test_frozen_inline_attempt_cannot_fail_or_enqueue_another_owner(stores, state, operation):
    execution, _, lineage = stores
    claim = register(execution)
    payload = SourceMaterializationPayload('{"request":1}', '{"response":1}')
    execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    if state == "pending_materialization":
        execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64, materialization=payload)
        lineage.lease_pending_payload(calculation_id=claim.calculation_id, worker_id="writer", lease_seconds=120)
    before = lineage.get_record(claim.calculation_id), lineage.get_payload(claim.calculation_id)
    other = SourceCustodyClaim(claim.calculation_id, claim.tenant_id, "other-inline-attempt", 0)
    arguments = {"failure": "stale"} if operation == "fail" else {"materialization": payload}
    with pytest.raises(SourceCustodyConflict, match="attempt"):
        execution.select_returns_series_source_root(claim=other, root_digest="a" * 64, **arguments)
    assert (lineage.get_record(claim.calculation_id), lineage.get_payload(claim.calculation_id)) == before
    # The original owner remains admitted, including idempotent enqueue under a lease.
    execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64, materialization=payload)
    if before[1] is not None:
        assert lineage.get_payload(claim.calculation_id) == before[1]


def test_db_time_expiry_during_root_selection_rolls_back_authority(stores):
    _, jobs, lineage = stores
    claim = running_claim(stores)
    with jobs._engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER expire_during_capture AFTER INSERT ON lineage_records BEGIN "
                "UPDATE analytics_compute_job SET lease_expires_at_utc='2000-01-01'; END"
            )
        )
    with pytest.raises(SourceCustodyConflict, match="expired during selection"):
        jobs.select_returns_series_source_root(claim=claim, root_digest=None)
    assert lineage.get_record(claim.calculation_id) is None


def test_enqueue_is_idempotent_preserves_worker_lease_and_refuses_conflicting_payload(stores):
    execution, _, lineage = stores
    claim = register(execution)
    execution.select_returns_series_source_root(claim=claim, root_digest=None)
    execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    payload = SourceMaterializationPayload('{"request":1}', '{"response":1}')
    execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64, materialization=payload)
    leased = lineage.lease_pending_payload(calculation_id=claim.calculation_id, worker_id="writer", lease_seconds=120)
    execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64, materialization=payload)
    assert lineage.get_payload(claim.calculation_id) == leased
    with pytest.raises(SourceCustodyConflict):
        execution.select_returns_series_source_root(
            claim=claim, root_digest="a" * 64, materialization=SourceMaterializationPayload("{}", "{}")
        )
    with pytest.raises(LineagePayloadLeaseOwnershipError):
        lineage.mark_complete(claim.calculation_id, [], worker_id="writer")


@pytest.mark.parametrize("operation", ["pending", "enqueue", "create"])
def test_generic_producers_cannot_reset_source_identity(stores, operation):
    execution, _, lineage = stores
    claim = register(execution)
    execution.select_returns_series_source_root(claim=claim, root_digest=None)
    execution.select_returns_series_source_root(claim=claim, root_digest="a" * 64)
    with pytest.raises(LineagePayloadLeaseOwnershipError):
        if operation == "pending":
            lineage.mark_pending(claim.calculation_id)
        elif operation == "create":
            lineage.create_pending_record(claim.calculation_id, "ReturnsSeries")
        else:
            lineage.enqueue_lineage_payload(
                calculation_id=claim.calculation_id,
                calculation_type="ReturnsSeries",
                request_json="{}",
                response_json="{}",
                details={},
            )
    assert lineage.get_record(claim.calculation_id).source_root_digest == "a" * 64
