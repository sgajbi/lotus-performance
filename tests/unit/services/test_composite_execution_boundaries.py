"""Correction, lease and lineage boundaries using controlled durable-store ports."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.services import compute_job_store as jobs
from app.services import execution_registry as executions
from app.services import source_correction_service as corrections
from app.workers import lineage_worker as lineage
from core.errors import APIError


@pytest.mark.parametrize(
    "status,owner,expiry,message",
    [
        ("PENDING", "worker", "future", "active lease"),
        ("RUNNING", "other", "future", "owner mismatch"),
        ("RUNNING", "worker", None, "lease expiry"),
        ("RUNNING", "worker", "past", "after lease expiry"),
    ],
)
def test_immutable_input_requires_current_active_lease(status, owner, expiry, message):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    row = SimpleNamespace(
        job_status=jobs.ComputeJobStatus[status].value,
        lease_owner_id=owner,
        worker_id="worker",
        lease_expires_at_utc=None if expiry is None else now + timedelta(seconds=1 if expiry == "future" else -1),
    )
    with pytest.raises(jobs.ComputeJobLeaseOwnershipError, match=message):
        jobs._ensure_compute_job_active_lease_owner(
            row, calculation_id=uuid4(), worker_id="worker", transition="bind input", now=now
        )
    row.job_status, row.lease_owner_id, row.lease_expires_at_utc = (
        jobs.ComputeJobStatus.RUNNING.value,
        "worker",
        now + timedelta(seconds=1),
    )
    jobs._ensure_compute_job_active_lease_owner(
        row, calculation_id=uuid4(), worker_id="worker", transition="bind input", now=now
    )


@pytest.mark.parametrize("created", [False, True])
def test_correction_job_conflict_deletes_only_execution_created_by_this_attempt(monkeypatch, created):
    registry, queue = Mock(), Mock()
    queue.register_job.return_value = SimpleNamespace(status=jobs.ComputeJobRegistrationStatus.CONFLICT)
    monkeypatch.setattr(corrections, "execution_registry", registry)
    monkeypatch.setattr(corrections, "compute_job_store", queue)
    identity = uuid4()
    with pytest.raises(APIError) as error:
        corrections._register_recalculation_job(
            execution=SimpleNamespace(analytics_type="TWR"),
            replacement_id=identity,
            replacement_payload={"calculation_id": str(identity)},
            tenant_id="tenant",
            created=created,
        )
    assert error.value.error_code == "SOURCE_CORRECTION_RECALCULATION_CONFLICT"
    if created:
        registry.delete_execution.assert_called_once_with(identity)
    else:
        registry.delete_execution.assert_not_called()


def test_correction_execution_conflict_never_creates_or_starts_job(monkeypatch):
    registry, queue = Mock(), Mock()
    registry.register_execution.return_value = SimpleNamespace(status=executions.ExecutionRegistrationStatus.CONFLICT)
    monkeypatch.setattr(corrections, "execution_registry", registry)
    monkeypatch.setattr(corrections, "compute_job_store", queue)
    execution = SimpleNamespace(
        calculation_id=uuid4(), request_payload={}, analytics_type="TWR", portfolio_id="member", requested_window={}
    )
    with pytest.raises(APIError) as error:
        corrections._schedule_recalculation(
            execution=execution, request=SimpleNamespace(correction_id="correction"), tenant_id="tenant"
        )
    assert error.value.error_code == "SOURCE_CORRECTION_RECALCULATION_CONFLICT"
    queue.register_job.assert_not_called()
    registry.start_stage.assert_not_called()


@pytest.mark.parametrize("job_status", [None, "RUNNING", "COMPLETE"])
def test_correction_coalescing_does_not_absorb_started_or_missing_jobs(monkeypatch, job_status):
    queue = Mock()
    queue.get_job_for_tenant.return_value = None if job_status is None else SimpleNamespace(job_status=job_status)
    monkeypatch.setattr(corrections, "compute_job_store", queue)
    identity = uuid4()
    latest = SimpleNamespace(
        correction_id="older",
        state="recalculation_pending",
        request_payload=dict(coalesced_effective_start_date="2026-01-01", coalesced_effective_end_date="2026-01-31"),
        impacts=[dict(corrected_calculation_id=str(identity))],
    )
    request = SimpleNamespace(
        correction_id="newer", effective_start_date=date(2026, 1, 15), effective_end_date=date(2026, 2, 1)
    )
    assert corrections._coalescing_context(latest=latest, request=request, tenant_id="tenant") == (
        [],
        request.effective_start_date,
        request.effective_end_date,
    )
    queue.get_job_for_tenant.assert_called_once_with(identity, tenant_id="tenant")


def test_disjoint_correction_windows_never_query_or_coalesce_jobs(monkeypatch):
    queue = Mock()
    monkeypatch.setattr(corrections, "compute_job_store", queue)
    latest = SimpleNamespace(
        correction_id="older",
        state="recalculation_pending",
        request_payload=dict(coalesced_effective_start_date="2026-01-01", coalesced_effective_end_date="2026-01-31"),
    )
    request = SimpleNamespace(
        correction_id="newer", effective_start_date=date(2026, 3, 1), effective_end_date=date(2026, 3, 2)
    )
    assert corrections._coalescing_context(latest=latest, request=request, tenant_id="tenant")[0] == []
    queue.get_job_for_tenant.assert_not_called()


def test_unknown_correction_and_unobserved_economic_outputs_stay_absent():
    with pytest.raises(APIError) as error:
        corrections._response_for_record(None, replayed=False)
    assert error.value.error_code == "SOURCE_CORRECTION_NOT_FOUND"
    assert corrections._economic_response_fingerprint(None) is None
    assert corrections._fingerprints_changed(None, "fingerprint") is None
    assert corrections._fingerprints_changed("fingerprint", "fingerprint") is False
    assert corrections._fingerprints_changed("fingerprint", "different") is True
    assert corrections._record_observed_at(SimpleNamespace(observed_at_utc="2026-01-01T00:00:00Z")) == datetime(
        2026, 1, 1, tzinfo=UTC
    )
    assert not corrections._is_impacted(SimpleNamespace(analytics_type="UNSUPPORTED", request_payload={}), None)


@pytest.mark.parametrize(
    "record_status,stage_status,expected",
    [
        (None, None, False),
        ("FAILED", None, False),
        ("PENDING", None, None),
        ("COMPLETE", "FAILED", False),
        ("COMPLETE", "COMPLETE", True),
    ],
)
def test_lineage_completion_requires_both_retained_record_and_terminal_execution_stage(
    record_status, stage_status, expected
):
    store, registry = Mock(), Mock()
    store.get_record.return_value = (
        None
        if record_status is None
        else SimpleNamespace(status=lineage.LineageStatus[record_status], calculation_type="TWR")
    )
    registry.stage_status.return_value = None if stage_status is None else executions.ExecutionStageStatus[stage_status]
    result = lineage._lineage_terminal_status(lineage_store=store, execution_store=registry, calculation_id=uuid4())
    assert result is expected
    if record_status in {None, "FAILED", "PENDING"}:
        registry.stage_status.assert_not_called()


@pytest.mark.parametrize("terminal", [False, True])
def test_materialized_lineage_payload_is_retained_until_terminal_stage_and_lease_owned(monkeypatch, terminal):
    store, service, registry = Mock(), Mock(), Mock()
    service.materialize_payload.return_value = True
    monkeypatch.setattr(lineage, "_lineage_terminal_status", lambda **kwargs: terminal)
    store.delete_payload.side_effect = lineage.LineagePayloadLeaseOwnershipError("stale worker")
    payload = SimpleNamespace(
        calculation_id=uuid4(),
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={},
        worker_id="worker",
        attempt_count=1,
    )
    assert not lineage._materialize_leased_payload(
        payload=payload,
        lineage_store=store,
        lineage_service_=service,
        execution_store=registry,
        max_attempts=3,
        require_terminal_stage=True,
    )
    if terminal:
        store.delete_payload.assert_called_once_with(payload.calculation_id, worker_id="worker")
    else:
        store.delete_payload.assert_not_called()


def test_concurrent_snapshot_insert_conflict_preserves_known_identity():
    session = MagicMock()
    session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    snapshot = dict(
        snapshot_id="snapshot",
        upstream_endpoint="/source",
        source_identifier="member",
        as_of_date="2026-01-01",
        request_fingerprint="request",
        response_fingerprint="response",
        retrieval_status="complete",
    )
    known = set()
    assert not executions._record_missing_upstream_snapshot(
        session, calculation_id=uuid4(), snapshot=snapshot, created_at=datetime.now(UTC), existing_snapshot_ids=known
    )
    assert known == {"snapshot"}
    assert not executions._record_missing_upstream_snapshot(
        session, calculation_id=uuid4(), snapshot=snapshot, created_at=datetime.now(UTC), existing_snapshot_ids=known
    )
    assert session.add.call_count == 1


@pytest.mark.parametrize("duplicate", [False, True])
def test_additive_compute_migration_tolerates_only_matching_duplicate_column(monkeypatch, duplicate):
    connection, inspector = Mock(), Mock()
    connection.dialect.name = "postgresql"
    inspector.get_table_names.return_value = ["analytics_compute_job"]
    inspector.get_columns.return_value = []
    monkeypatch.setattr(jobs, "inspect", lambda connection: inspector)
    message = "duplicate column tenant_id" if duplicate else "permission denied tenant_id"
    error = OperationalError("ALTER", {}, Exception(message))
    connection.execute.side_effect = error
    store = object.__new__(jobs.ComputeJobStore)
    if duplicate:
        store._ensure_tenant_id_column(connection)
    else:
        with pytest.raises(OperationalError) as failure:
            store._ensure_tenant_id_column(connection)
        assert failure.value is error
    assert not jobs._is_duplicate_column_error(
        OperationalError("ALTER", {}, Exception("duplicate column different")), "tenant_id"
    )


def test_execution_bootstrap_preserves_existing_columns_and_adds_missing_custody_columns(monkeypatch):
    connection, inspector = Mock(), Mock()
    inspector.get_table_names.return_value = ["analytics_execution"]
    inspector.get_columns.return_value = []
    monkeypatch.setattr(executions, "inspect", lambda connection: inspector)
    store = object.__new__(executions.ExecutionRegistry)
    store._ensure_tenant_id_column(connection)
    store._ensure_retained_payload_columns(connection)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert len(statements) == 3
    assert all("ADD COLUMN" in statement and "DROP" not in statement for statement in statements)
    connection.reset_mock()
    inspector.get_table_names.return_value = []
    for method in (
        store._ensure_tenant_id_column,
        store._ensure_retained_payload_columns,
        store._ensure_submission_idempotency_columns,
        store._ensure_failure_json_column,
    ):
        method(connection)
    connection.execute.assert_not_called()
