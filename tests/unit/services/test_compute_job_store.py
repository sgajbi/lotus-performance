from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

import app.services.compute_job_store as compute_job_store_module
from app.services.compute_job_store import (
    INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE,
    INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_MESSAGE,
    INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_ERROR_TYPE,
    INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_MESSAGE,
    ComputeJobLeaseOwnershipError,
    ComputeJobModel,
    ComputeJobRegistrationStatus,
    ComputeJobStatus,
    ComputeJobStore,
    _aggregate_row_count,
    _compute_job_has_conflicting_worker_lease,
    _compute_job_inspection_active_since,
    _compute_job_payload_failure,
    _compute_job_record_payload_state,
    _compute_job_registration_result_for_integrity_conflict,
    _compute_job_request_identity_json,
    _compute_job_request_identity_json_from_json,
    _compute_queue_stats_columns,
    _compute_recovery_query_filters,
    _ensure_compute_job_can_mark_running,
    _matches_existing_compute_job_registration,
    _queue_stats_from_aggregate_row,
    _recovery_seek_cursor_filter,
    _stale_job_reconciliation_outcome,
    get_compute_job_store,
)
from app.services.durable_store_inspection import build_inspection_query_context


def _compute_job_model_for_inspection(
    *,
    job_status: ComputeJobStatus,
    created_at_utc: datetime,
    leased_at_utc: datetime | None = None,
    started_at_utc: datetime | None = None,
    completed_at_utc: datetime | None = None,
) -> ComputeJobModel:
    return ComputeJobModel(
        calculation_id=str(uuid4()),
        analytics_type="ReturnsSeries",
        job_status=job_status.value,
        request_json="{}",
        response_json=None,
        attempt_count=0,
        max_attempts=1,
        created_at_utc=created_at_utc,
        leased_at_utc=leased_at_utc,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
    )


def test_compute_job_inspection_active_since_uses_leased_timestamp_before_created():
    created_at = datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc)
    leased_at = datetime(2026, 3, 14, 9, 5, tzinfo=timezone.utc)
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.LEASED,
        created_at_utc=created_at,
        leased_at_utc=leased_at,
    )

    assert _compute_job_inspection_active_since(row) == leased_at


def test_compute_job_inspection_active_since_uses_running_timestamp_precedence():
    created_at = datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc)
    leased_at = datetime(2026, 3, 14, 9, 5, tzinfo=timezone.utc)
    started_at = datetime(2026, 3, 14, 9, 7, tzinfo=timezone.utc)
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.RUNNING,
        created_at_utc=created_at,
        leased_at_utc=leased_at,
        started_at_utc=started_at,
    )

    assert _compute_job_inspection_active_since(row) == started_at


def test_compute_job_inspection_active_since_uses_failed_completion_before_created():
    created_at = datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc)
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.FAILED,
        created_at_utc=created_at,
        completed_at_utc=completed_at,
    )

    assert _compute_job_inspection_active_since(row) == completed_at


def test_compute_job_inspection_active_since_defaults_to_created_timestamp():
    created_at = datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc)
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.COMPLETE,
        created_at_utc=created_at,
    )

    assert _compute_job_inspection_active_since(row) == created_at


def test_compute_job_inspection_item_handles_missing_active_timestamp(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.LEASED,
        created_at_utc=datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc),
    )
    row.created_at_utc = None

    item = store._to_inspection_item(row, now=datetime(2026, 3, 14, 9, 5, tzinfo=timezone.utc))

    assert item.active_since_utc is None
    assert item.age_seconds is None


def test_compute_job_payload_failure_fails_closed_on_missing_request_payload():
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.COMPLETE,
        created_at_utc=datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc),
    )

    failure = _compute_job_payload_failure(row, request_payload=None, response_payload={"ok": True})

    assert failure is not None
    assert failure.request_payload == {}
    assert failure.error_message == INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_MESSAGE
    assert failure.error_type == INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE


def test_compute_job_payload_failure_preserves_existing_response_error_details():
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.COMPLETE,
        created_at_utc=datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc),
    )
    row.response_json = "{not-json"
    row.error_message = "stored error"
    row.error_type = "StoredError"
    request_payload = {"portfolio_id": "P1"}

    failure = _compute_job_payload_failure(row, request_payload=request_payload, response_payload=None)

    assert failure is not None
    assert failure.request_payload is request_payload
    assert failure.error_message == "stored error"
    assert failure.error_type == "StoredError"


def test_compute_job_record_payload_state_raises_when_request_payload_remains_unresolved(monkeypatch):
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.COMPLETE,
        created_at_utc=datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(compute_job_store_module, "_compute_job_payload_failure", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="Compute job request payload resolution failed"):
        _compute_job_record_payload_state(row, request_payload=None, response_payload=None)


def test_compute_job_store_lifecycle(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )
    pending = store.get_job(calculation_id)
    assert pending is not None
    assert pending.job_status == ComputeJobStatus.PENDING

    leased = store.lease_pending_jobs(worker_id="worker-a", limit=10, lease_seconds=30)
    assert len(leased) == 1
    assert leased[0].job_status == ComputeJobStatus.LEASED

    store.mark_running(calculation_id, worker_id="worker-a")
    running = store.get_job(calculation_id)
    assert running is not None
    assert running.job_status == ComputeJobStatus.RUNNING
    assert running.attempt_count == 1
    assert running.worker_id == "worker-a"

    store.mark_complete(
        calculation_id,
        response_payload={"calculation_id": str(calculation_id)},
        worker_id="worker-a",
    )
    complete = store.get_job(calculation_id)
    assert complete is not None
    assert complete.job_status == ComputeJobStatus.COMPLETE
    assert complete.response_payload == {"calculation_id": str(calculation_id)}


def test_compute_job_store_fails_closed_on_invalid_response_json(tmp_path, caplog):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )
    with store._session() as session:
        row = session.get(ComputeJobModel, str(calculation_id))
        assert row is not None
        row.job_status = ComputeJobStatus.COMPLETE.value
        row.response_json = "{not-json"
        row.completed_at_utc = now

    with caplog.at_level("WARNING", logger="app.services.compute_job_store"):
        record = store.get_job(calculation_id)

    assert record is not None
    assert record.job_status == ComputeJobStatus.FAILED
    assert record.response_payload is None
    assert record.error_message == INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_MESSAGE
    assert record.error_type == INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_ERROR_TYPE
    assert f"calculation_id={calculation_id}" in caplog.text


def test_compute_job_store_preserves_existing_error_details_on_invalid_response_json(tmp_path, caplog):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )
    with store._session() as session:
        row = session.get(ComputeJobModel, str(calculation_id))
        assert row is not None
        row.job_status = ComputeJobStatus.COMPLETE.value
        row.response_json = "{not-json"
        row.error_message = "upstream stored error"
        row.error_type = "UpstreamStoredError"
        row.completed_at_utc = now

    with caplog.at_level("WARNING", logger="app.services.compute_job_store"):
        record = store.get_job(calculation_id)

    assert record is not None
    assert record.job_status == ComputeJobStatus.FAILED
    assert record.response_payload is None
    assert record.error_message == "upstream stored error"
    assert record.error_type == "UpstreamStoredError"
    assert f"calculation_id={calculation_id}" in caplog.text


def test_compute_job_store_fails_closed_on_invalid_request_json(tmp_path, caplog):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )
    with store._session() as session:
        row = session.get(ComputeJobModel, str(calculation_id))
        assert row is not None
        row.request_json = "{not-json"

    with caplog.at_level("WARNING", logger="app.services.compute_job_store"):
        record = store.get_job(calculation_id)

    assert record is not None
    assert record.job_status == ComputeJobStatus.FAILED
    assert record.request_payload == {}
    assert record.error_message == INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_MESSAGE
    assert record.error_type == INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE
    assert f"calculation_id={calculation_id}" in caplog.text


def test_compute_job_store_fails_closed_on_non_object_request_json(tmp_path, caplog):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )
    with store._session() as session:
        row = session.get(ComputeJobModel, str(calculation_id))
        assert row is not None
        row.request_json = "[1, 2, 3]"

    with caplog.at_level("WARNING", logger="app.services.compute_job_store"):
        record = store.get_job(calculation_id)

    assert record is not None
    assert record.job_status == ComputeJobStatus.FAILED
    assert record.request_payload == {}
    assert record.error_type == INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE
    assert f"calculation_id={calculation_id}" in caplog.text


def test_compute_job_store_marks_invalid_request_payload_failed_during_lease(tmp_path, caplog):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )
    with store._session() as session:
        row = session.get(ComputeJobModel, str(calculation_id))
        assert row is not None
        row.request_json = "{not-json"

    with caplog.at_level("WARNING", logger="app.services.compute_job_store"):
        leased = store.lease_pending_jobs(worker_id="worker-a", limit=10, lease_seconds=30)

    assert leased == []
    failed = store.get_job(calculation_id)
    assert failed is not None
    assert failed.job_status == ComputeJobStatus.FAILED
    assert failed.worker_id is None
    assert failed.error_message == INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_MESSAGE
    assert failed.error_type == INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE
    assert failed.completed_at_utc is not None
    assert f"calculation_id={calculation_id}" in caplog.text


def test_compute_job_store_fails_closed_on_non_object_response_json(tmp_path, caplog):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )
    with store._session() as session:
        row = session.get(ComputeJobModel, str(calculation_id))
        assert row is not None
        row.job_status = ComputeJobStatus.COMPLETE.value
        row.response_json = "[1, 2, 3]"
        row.completed_at_utc = now

    with caplog.at_level("WARNING", logger="app.services.compute_job_store"):
        record = store.get_job(calculation_id)

    assert record is not None
    assert record.job_status == ComputeJobStatus.FAILED
    assert record.response_payload is None
    assert record.error_type == INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_ERROR_TYPE
    assert f"calculation_id={calculation_id}" in caplog.text


def test_compute_job_store_failure_and_filters(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calc_one = uuid4()
    calc_two = uuid4()

    store.enqueue_job(calculation_id=calc_one, analytics_type="ReturnsSeries", request_payload={"a": 1})
    store.enqueue_job(calculation_id=calc_two, analytics_type="OtherAnalytics", request_payload={"b": 2})

    leased = store.lease_pending_jobs(worker_id="worker-a", analytics_type="ReturnsSeries", limit=1, lease_seconds=30)
    assert len(leased) == 1
    assert leased[0].calculation_id == calc_one

    store.mark_failed(calc_one, error_message="boom", error_type="RuntimeError")
    failed = store.get_job(calc_one)
    assert failed is not None
    assert failed.job_status == ComputeJobStatus.FAILED
    assert failed.error_message == "boom"
    assert failed.error_type == "RuntimeError"

    store.clear_all_records()
    assert store.get_job(calc_one) is None
    with pytest.raises(KeyError):
        store.mark_running(calc_one, worker_id="worker-a")


def test_compute_job_store_lists_pending_jobs_without_analytics_filter(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    first_id = uuid4()
    second_id = uuid4()

    store.enqueue_job(calculation_id=first_id, analytics_type="ReturnsSeries", request_payload={"p": "1"})
    store.enqueue_job(calculation_id=second_id, analytics_type="Attribution", request_payload={"p": "2"})

    pending = store.list_pending_jobs(limit=10)

    assert [job.calculation_id for job in pending] == [first_id, second_id]


def test_compute_job_store_lists_pending_jobs_with_analytics_filter(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    first_id = uuid4()
    second_id = uuid4()

    store.enqueue_job(calculation_id=first_id, analytics_type="ReturnsSeries", request_payload={"p": "1"})
    store.enqueue_job(calculation_id=second_id, analytics_type="Attribution", request_payload={"p": "2"})

    pending = store.list_pending_jobs(analytics_type="Attribution", limit=10)

    assert [job.calculation_id for job in pending] == [second_id]


def test_compute_job_store_retry_and_expired_lease_reclaim(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
        max_attempts=2,
    )

    leased = store.lease_pending_jobs(worker_id="worker-a", limit=10, lease_seconds=30)
    assert len(leased) == 1
    store.mark_running(calculation_id, worker_id="worker-a")

    will_retry = store.mark_retryable_failure(
        calculation_id,
        error_message="temporary boom",
        error_type="RuntimeError",
        worker_id="worker-a",
    )
    assert will_retry is True
    pending_again = store.get_job(calculation_id)
    assert pending_again is not None
    assert pending_again.job_status == ComputeJobStatus.PENDING
    assert pending_again.attempt_count == 1
    assert pending_again.completed_at_utc is None

    leased_again = store.lease_pending_jobs(worker_id="worker-b", limit=10, lease_seconds=30)
    assert len(leased_again) == 1
    assert leased_again[0].worker_id == "worker-b"

    store.mark_running(calculation_id, worker_id="worker-b")
    will_retry = store.mark_retryable_failure(
        calculation_id,
        error_message="still broken",
        error_type="RuntimeError",
        worker_id="worker-b",
    )
    assert will_retry is False
    failed = store.get_job(calculation_id)
    assert failed is not None
    assert failed.job_status == ComputeJobStatus.FAILED
    assert failed.attempt_count == 2

    another_id = uuid4()
    store.enqueue_job(
        calculation_id=another_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P2"},
    )
    store.lease_pending_jobs(worker_id="worker-a", limit=10, lease_seconds=30)
    with store._session() as session:
        row = store._get_model(session, another_id)
        row.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
    reclaimed = store.lease_pending_jobs(worker_id="worker-c", limit=10, lease_seconds=30)
    assert len(reclaimed) == 1
    assert reclaimed[0].calculation_id == another_id


def test_compute_job_store_reconciles_stale_running_job(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
        max_attempts=2,
    )
    store.lease_pending_jobs(worker_id="worker-a", limit=10, lease_seconds=30)
    store.mark_running(calculation_id, worker_id="worker-a", lease_seconds=30)

    with store._session() as session:
        row = store._get_model(session, calculation_id)
        row.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)

    reconciled = store.reconcile_stale_jobs()
    assert len(reconciled) == 1
    assert reconciled[0].previous_status == ComputeJobStatus.RUNNING
    assert reconciled[0].reconciled_status == ComputeJobStatus.PENDING

    pending = store.get_job(calculation_id)
    assert pending is not None
    assert pending.job_status == ComputeJobStatus.PENDING
    assert pending.error_type == "LeaseExpired"
    assert pending.worker_id is None

    store.lease_pending_jobs(worker_id="worker-b", limit=10, lease_seconds=30)
    store.mark_running(calculation_id, worker_id="worker-b", lease_seconds=30)
    with store._session() as session:
        row = store._get_model(session, calculation_id)
        row.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)

    reconciled_again = store.reconcile_stale_jobs()
    assert len(reconciled_again) == 1
    assert reconciled_again[0].reconciled_status == ComputeJobStatus.FAILED

    failed = store.get_job(calculation_id)
    assert failed is not None
    assert failed.job_status == ComputeJobStatus.FAILED
    assert failed.error_message == "Compute job execution lease expired after exhausting retry budget."


def test_compute_job_store_rejects_finalization_from_stale_worker_after_reclaim(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
        max_attempts=3,
    )
    store.lease_pending_jobs(worker_id="worker-a", limit=10, lease_seconds=30)
    store.mark_running(calculation_id, worker_id="worker-a", lease_seconds=30)
    with store._session() as session:
        row = store._get_model(session, calculation_id)
        row.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)

    reconciled = store.reconcile_stale_jobs()
    assert len(reconciled) == 1
    store.lease_pending_jobs(worker_id="worker-b", limit=10, lease_seconds=30)
    store.mark_running(calculation_id, worker_id="worker-b", lease_seconds=30)

    with pytest.raises(ComputeJobLeaseOwnershipError, match="lease owner mismatch"):
        store.mark_complete(
            calculation_id,
            response_payload={"calculation_id": str(calculation_id), "stale": True},
            worker_id="worker-a",
        )
    with pytest.raises(ComputeJobLeaseOwnershipError, match="lease owner mismatch"):
        store.mark_failed(
            calculation_id,
            error_message="stale failure",
            error_type="RuntimeError",
            worker_id="worker-a",
        )
    with pytest.raises(ComputeJobLeaseOwnershipError, match="lease owner mismatch"):
        store.mark_retryable_failure(
            calculation_id,
            error_message="stale retry",
            error_type="RuntimeError",
            worker_id="worker-a",
        )

    running = store.get_job(calculation_id)
    assert running is not None
    assert running.job_status == ComputeJobStatus.RUNNING
    assert running.worker_id == "worker-b"
    assert running.response_payload is None
    assert running.error_message is None
    assert running.error_type is None


def test_stale_job_reconciliation_outcome_only_exhausts_running_jobs() -> None:
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)

    exhausted_running = _stale_job_reconciliation_outcome(
        previous_status=ComputeJobStatus.RUNNING,
        attempt_count=2,
        max_attempts=2,
        now=now,
    )
    exhausted_leased = _stale_job_reconciliation_outcome(
        previous_status=ComputeJobStatus.LEASED,
        attempt_count=2,
        max_attempts=2,
        now=now,
    )

    assert exhausted_running.job_status == ComputeJobStatus.FAILED
    assert exhausted_running.completed_at_utc == now
    assert exhausted_leased.job_status == ComputeJobStatus.PENDING
    assert exhausted_leased.completed_at_utc is None


def test_compute_job_store_reconciles_stale_leased_job_without_exhausting_retries(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()
    reconcile_now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="Attribution",
        request_payload={"portfolio_id": "P1"},
        max_attempts=3,
    )
    store.lease_pending_jobs(worker_id="worker-a", limit=10, lease_seconds=30)
    with store._session() as session:
        row = store._get_model(session, calculation_id)
        row.lease_expires_at_utc = reconcile_now - timedelta(seconds=1)

    reconciled = store.reconcile_stale_jobs(now=reconcile_now)

    assert len(reconciled) == 1
    assert reconciled[0].previous_status == ComputeJobStatus.LEASED
    assert reconciled[0].reconciled_status == ComputeJobStatus.PENDING
    assert reconciled[0].error_message == "Compute job reconciliation detected an expired worker lease."
    assert reconciled[0].error_type == "LeaseExpired"
    pending = store.get_job(calculation_id)
    assert pending is not None
    assert pending.job_status == ComputeJobStatus.PENDING
    assert pending.worker_id is None
    assert pending.leased_at_utc is None
    assert pending.lease_expires_at_utc is None
    assert pending.completed_at_utc is None


def test_compute_job_store_pending_lease_statement_uses_skip_locked_on_postgresql(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")

    statement = store._build_lease_pending_jobs_statement(
        now=datetime.now(timezone.utc),
        limit=5,
        analytics_type="ReturnsSeries",
        dialect_name="postgresql",
    )
    compiled = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "FOR UPDATE SKIP LOCKED" in compiled
    assert "ORDER BY analytics_compute_job.created_at_utc ASC" in compiled
    assert "LIMIT 5" in compiled
    assert "analytics_compute_job.analytics_type = 'ReturnsSeries'" in compiled


def test_compute_job_store_stale_reconcile_statement_uses_skip_locked_on_postgresql(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")

    statement = store._build_reconcile_stale_jobs_statement(
        now=datetime.now(timezone.utc),
        dialect_name="postgresql",
    )
    compiled = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "FOR UPDATE SKIP LOCKED" in compiled
    assert "analytics_compute_job.job_status IN ('leased', 'running')" in compiled
    assert "analytics_compute_job.lease_expires_at_utc IS NOT NULL" in compiled


def test_compute_job_store_queue_stats(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)

    pending_id = uuid4()
    leased_id = uuid4()
    running_id = uuid4()
    failed_id = uuid4()
    complete_id = uuid4()

    for calculation_id in [pending_id, leased_id, running_id, failed_id, complete_id]:
        store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
            max_attempts=2,
        )

    with store._session() as session:
        leased_row = store._get_model(session, leased_id)
        leased_row.job_status = ComputeJobStatus.LEASED.value
        leased_row.worker_id = "worker-a"
        leased_row.leased_at_utc = now - timedelta(seconds=10)
        leased_row.lease_expires_at_utc = now + timedelta(seconds=20)

        running_row = store._get_model(session, running_id)
        running_row.job_status = ComputeJobStatus.RUNNING.value
        running_row.worker_id = "worker-b"
        running_row.started_at_utc = now - timedelta(seconds=15)
        running_row.leased_at_utc = now - timedelta(seconds=15)
        running_row.lease_expires_at_utc = now + timedelta(seconds=15)

        failed_row = store._get_model(session, failed_id)
        failed_row.job_status = ComputeJobStatus.FAILED.value
        failed_row.error_message = "boom"
        failed_row.error_type = "RuntimeError"
        failed_row.attempt_count = 2
        failed_row.completed_at_utc = now - timedelta(seconds=5)

        complete_row = store._get_model(session, complete_id)
        complete_row.job_status = ComputeJobStatus.COMPLETE.value
        complete_row.response_json = '{"ok": true}'
        complete_row.completed_at_utc = now - timedelta(seconds=1)

        store._get_model(session, pending_id).created_at_utc = now - timedelta(seconds=120)
        pending_row = store._get_model(session, pending_id)
        pending_row.attempt_count = 1
        pending_row.error_type = "LeaseExpired"

    stats = store.get_queue_stats(now=now)

    assert stats.pending_count == 1
    assert stats.leased_count == 1
    assert stats.running_count == 1
    assert stats.failed_count == 1
    assert stats.complete_count == 1
    assert stats.retry_backlog_count == 1
    assert stats.lease_expired_count == 1
    assert stats.terminal_failure_count == 1
    assert stats.oldest_pending_age_seconds == 120.0
    assert stats.oldest_leased_age_seconds == 10.0
    assert stats.oldest_running_age_seconds == 15.0


def test_compute_queue_stats_columns_preserve_operator_metric_contract():
    now = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)
    columns = _compute_queue_stats_columns(now=now)

    assert [column.name for column in columns] == [
        "pending_count",
        "leased_count",
        "running_count",
        "failed_count",
        "complete_count",
        "retry_backlog_count",
        "lease_expired_count",
        "reclaimable_count",
        "terminal_failure_count",
        "oldest_pending_created_at",
        "oldest_leased_at",
        "oldest_running_at",
    ]
    compiled = str(
        ComputeJobStore("sqlite://")
        ._build_queue_stats_statement(now=now)
        .compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "analytics_compute_job.job_status = 'pending'" in compiled
    assert "analytics_compute_job.attempt_count > 0" in compiled
    assert "analytics_compute_job.error_type = 'LeaseExpired'" in compiled
    assert "analytics_compute_job.job_status IN ('leased', 'running')" in compiled
    assert "analytics_compute_job.lease_expires_at_utc <" in compiled
    assert "analytics_compute_job.error_type != 'LeaseExpired'" in compiled


def test_queue_stats_from_aggregate_row_defaults_counts_and_projects_ages():
    now = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)
    aggregate_row = SimpleNamespace(
        pending_count=None,
        leased_count=2,
        running_count=3,
        failed_count=None,
        complete_count=4,
        retry_backlog_count=None,
        lease_expired_count=1,
        terminal_failure_count=None,
        oldest_pending_created_at=now - timedelta(seconds=30),
        oldest_leased_at=None,
        oldest_running_at=now - timedelta(seconds=45),
        reclaimable_count=5,
    )

    stats = _queue_stats_from_aggregate_row(aggregate_row=aggregate_row, stats_now=now)

    assert stats.pending_count == 0
    assert stats.leased_count == 2
    assert stats.running_count == 3
    assert stats.failed_count == 0
    assert stats.complete_count == 4
    assert stats.retry_backlog_count == 0
    assert stats.lease_expired_count == 1
    assert stats.terminal_failure_count == 0
    assert stats.oldest_pending_age_seconds == 30.0
    assert stats.oldest_leased_age_seconds == 0.0
    assert stats.oldest_running_age_seconds == 45.0
    assert stats.reclaimable_count == 5


def test_aggregate_row_count_defaults_nulls_and_preserves_numeric_values():
    aggregate_row = SimpleNamespace(pending_count=None, leased_count=2)

    assert _aggregate_row_count(aggregate_row, "pending_count") == 0
    assert _aggregate_row_count(aggregate_row, "leased_count") == 2


def test_compute_job_store_queue_inspection_anchors(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    pending_id = uuid4()
    leased_id = uuid4()
    running_id = uuid4()
    failed_id = uuid4()

    for calculation_id in [pending_id, leased_id, running_id, failed_id]:
        store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
            max_attempts=2,
        )

    with store._session() as session:
        pending_row = store._get_model(session, pending_id)
        pending_row.created_at_utc = now - timedelta(seconds=120)

        leased_row = store._get_model(session, leased_id)
        leased_row.job_status = ComputeJobStatus.LEASED.value
        leased_row.leased_at_utc = now - timedelta(seconds=90)

        running_row = store._get_model(session, running_id)
        running_row.job_status = ComputeJobStatus.RUNNING.value
        running_row.started_at_utc = now - timedelta(seconds=60)

        failed_row = store._get_model(session, failed_id)
        failed_row.job_status = ComputeJobStatus.FAILED.value
        failed_row.error_type = "RuntimeError"
        failed_row.completed_at_utc = now - timedelta(seconds=5)

    anchors = store.get_queue_inspection_anchors()

    assert anchors.oldest_pending_calculation_id == str(pending_id)
    assert anchors.oldest_leased_calculation_id == str(leased_id)
    assert anchors.oldest_running_calculation_id == str(running_id)
    assert anchors.latest_terminal_failure_calculation_id == str(failed_id)


def test_compute_job_store_lists_active_and_failed_inspection_items(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    pending_id = uuid4()
    leased_id = uuid4()
    failed_id = uuid4()

    for calculation_id in [pending_id, leased_id, failed_id]:
        store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
            max_attempts=3,
        )

    with store._session() as session:
        pending_row = store._get_model(session, pending_id)
        pending_row.created_at_utc = now - timedelta(seconds=120)

        leased_row = store._get_model(session, leased_id)
        leased_row.job_status = ComputeJobStatus.LEASED.value
        leased_row.leased_at_utc = now - timedelta(seconds=90)

        failed_row = store._get_model(session, failed_id)
        failed_row.job_status = ComputeJobStatus.FAILED.value
        failed_row.completed_at_utc = now - timedelta(seconds=15)
        failed_row.error_type = "RuntimeError"
        failed_row.error_message = "boom"

    active_page = store.list_inspection_items(status_filter="active", limit=10, now=now)
    failed_page = store.list_inspection_items(status_filter="failed", limit=10, now=now)
    stale_page = store.list_inspection_items(status_filter="active", limit=10, min_age_seconds=100.0, now=now)

    assert active_page.total_count == 2
    assert [item.calculation_id for item in active_page.items] == [str(pending_id), str(leased_id)]
    assert active_page.items[0].status == ComputeJobStatus.PENDING.value
    assert active_page.items[0].age_seconds == 120.0
    assert active_page.items[1].status == ComputeJobStatus.LEASED.value
    assert active_page.items[1].age_seconds == 90.0
    assert failed_page.total_count == 1
    assert len(failed_page.items) == 1
    assert failed_page.items[0].calculation_id == str(failed_id)
    assert failed_page.items[0].status == ComputeJobStatus.FAILED.value
    assert failed_page.items[0].error_type == "RuntimeError"
    assert failed_page.items[0].error_message == "boom"
    assert failed_page.items[0].age_seconds == 15.0
    assert stale_page.total_count == 1
    assert [item.calculation_id for item in stale_page.items] == [str(pending_id)]


def test_compute_job_store_filters_inspection_items_by_analytics_type_and_calculation_substring(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    ids = [uuid4() for _ in range(3)]

    store.enqueue_job(calculation_id=ids[0], analytics_type="ReturnsSeries", request_payload={"portfolio_id": "A"})
    store.enqueue_job(calculation_id=ids[1], analytics_type="Attribution", request_payload={"portfolio_id": "B"})
    store.enqueue_job(calculation_id=ids[2], analytics_type="ReturnsSeries", request_payload={"portfolio_id": "C"})

    filtered = store.list_inspection_items(
        status_filter="all",
        limit=10,
        analytics_type="ReturnsSeries",
        calculation_id_contains=str(ids[2])[:8],
    )

    assert filtered.total_count == 1
    assert [item.calculation_id for item in filtered.items] == [str(ids[2])]


def test_compute_job_store_lists_reclaimable_items_with_expired_leases(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime.now(timezone.utc)
    reclaimable_id = uuid4()
    active_id = uuid4()

    store.enqueue_job(calculation_id=reclaimable_id, analytics_type="ReturnsSeries", request_payload={"p": "1"})
    store.enqueue_job(calculation_id=active_id, analytics_type="ReturnsSeries", request_payload={"p": "2"})

    with store._session() as session:
        reclaimable_row = store._get_model(session, reclaimable_id)
        reclaimable_row.job_status = ComputeJobStatus.RUNNING.value
        reclaimable_row.started_at_utc = now - timedelta(seconds=120)
        reclaimable_row.lease_expires_at_utc = now - timedelta(seconds=20)

        active_row = store._get_model(session, active_id)
        active_row.job_status = ComputeJobStatus.LEASED.value
        active_row.leased_at_utc = now - timedelta(seconds=90)
        active_row.lease_expires_at_utc = now + timedelta(seconds=60)

    page = store.list_inspection_items(status_filter="reclaimable", limit=10, now=now)

    assert page.total_count == 1
    assert [item.calculation_id for item in page.items] == [str(reclaimable_id)]
    assert page.items[0].status == ComputeJobStatus.RUNNING.value


def test_compute_job_store_builds_reclaimable_inspection_statements_with_context(tmp_path, monkeypatch):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    inspection_now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    context = build_inspection_query_context(
        status_filter="reclaimable",
        min_age_seconds=30.0,
        now=inspection_now,
    )
    calls = []

    def count_builder(**kwargs):
        calls.append(("count", kwargs))
        return "count-statement"

    def items_builder(**kwargs):
        calls.append(("items", kwargs))
        return "items-statement"

    monkeypatch.setattr(store, "_build_reclaimable_inspection_count_statement", count_builder)
    monkeypatch.setattr(store, "_build_reclaimable_inspection_items_statement", items_builder)

    statements = store._build_inspection_statements(
        inspection_context=context,
        limit=25,
        offset=50,
        analytics_type="ReturnsSeries",
        calculation_id_contains="abc",
    )

    assert statements.count_statement == "count-statement"
    assert statements.items_statement == "items-statement"
    assert calls == [
        (
            "count",
            {
                "analytics_type": "ReturnsSeries",
                "calculation_id_contains": "abc",
                "min_age_threshold": inspection_now - timedelta(seconds=30),
                "now": inspection_now,
            },
        ),
        (
            "items",
            {
                "limit": 25,
                "offset": 50,
                "analytics_type": "ReturnsSeries",
                "calculation_id_contains": "abc",
                "min_age_threshold": inspection_now - timedelta(seconds=30),
                "now": inspection_now,
            },
        ),
    ]


def test_compute_job_store_builds_standard_inspection_statements_with_context(tmp_path, monkeypatch):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    inspection_now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    context = build_inspection_query_context(
        status_filter="active",
        min_age_seconds=45.0,
        now=inspection_now,
    )
    calls = []

    def count_builder(**kwargs):
        calls.append(("count", kwargs))
        return "count-statement"

    def items_builder(**kwargs):
        calls.append(("items", kwargs))
        return "items-statement"

    monkeypatch.setattr(store, "_build_active_inspection_count_statement", count_builder)
    monkeypatch.setattr(store, "_build_active_inspection_items_statement", items_builder)

    statements = store._build_inspection_statements(
        inspection_context=context,
        limit=15,
        offset=30,
        analytics_type="Attribution",
        calculation_id_contains="def",
    )

    assert statements.count_statement == "count-statement"
    assert statements.items_statement == "items-statement"
    assert calls == [
        (
            "count",
            {
                "analytics_type": "Attribution",
                "calculation_id_contains": "def",
                "min_age_threshold": inspection_now - timedelta(seconds=45),
            },
        ),
        (
            "items",
            {
                "limit": 15,
                "offset": 30,
                "analytics_type": "Attribution",
                "calculation_id_contains": "def",
                "min_age_threshold": inspection_now - timedelta(seconds=45),
            },
        ),
    ]


def test_compute_job_store_queue_stats_include_reclaimable_count(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime.now(timezone.utc)
    reclaimable_id = uuid4()

    store.enqueue_job(calculation_id=reclaimable_id, analytics_type="ReturnsSeries", request_payload={"p": "1"})

    with store._session() as session:
        reclaimable_row = store._get_model(session, reclaimable_id)
        reclaimable_row.job_status = ComputeJobStatus.LEASED.value
        reclaimable_row.leased_at_utc = now - timedelta(seconds=40)
        reclaimable_row.lease_expires_at_utc = now - timedelta(seconds=10)

    stats = store.get_queue_stats(now=now)

    assert stats.reclaimable_count == 1


def test_compute_job_store_queue_inspection_anchors_include_latest_recovered(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    recovered_id = uuid4()
    failed_id = uuid4()
    pending_id = uuid4()
    leased_id = uuid4()
    running_id = uuid4()

    for calculation_id in [recovered_id, failed_id, pending_id, leased_id, running_id]:
        store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
            max_attempts=3,
        )

    with store._session() as session:
        recovered_row = store._get_model(session, recovered_id)
        recovered_row.attempt_count = 1
        recovered_row.created_at_utc = now - timedelta(seconds=50)
        recovered_row.last_error_at_utc = now - timedelta(seconds=5)

        failed_row = store._get_model(session, failed_id)
        failed_row.job_status = ComputeJobStatus.FAILED.value
        failed_row.error_type = "RuntimeError"
        failed_row.completed_at_utc = now - timedelta(seconds=10)

        pending_row = store._get_model(session, pending_id)
        pending_row.created_at_utc = now - timedelta(seconds=100)

        leased_row = store._get_model(session, leased_id)
        leased_row.job_status = ComputeJobStatus.LEASED.value
        leased_row.leased_at_utc = now - timedelta(seconds=80)

        running_row = store._get_model(session, running_id)
        running_row.job_status = ComputeJobStatus.RUNNING.value
        running_row.started_at_utc = now - timedelta(seconds=60)

    anchors = store.get_queue_inspection_anchors()

    assert anchors.oldest_pending_calculation_id == str(pending_id)
    assert anchors.oldest_leased_calculation_id == str(leased_id)
    assert anchors.oldest_running_calculation_id == str(running_id)
    assert anchors.latest_terminal_failure_calculation_id == str(failed_id)
    assert anchors.latest_recovered_calculation_id == str(recovered_id)


def test_compute_job_store_lists_recent_recoveries_in_descending_order(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    first_id = uuid4()
    second_id = uuid4()

    for calculation_id in [first_id, second_id]:
        store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
            max_attempts=3,
        )

    with store._session() as session:
        first_row = store._get_model(session, first_id)
        first_row.attempt_count = 1
        first_row.last_error_at_utc = now - timedelta(seconds=10)
        first_row.error_type = "RuntimeError"

        second_row = store._get_model(session, second_id)
        second_row.attempt_count = 2
        second_row.last_error_at_utc = now - timedelta(seconds=5)
        second_row.error_type = "LeaseExpired"

    events = store.list_recent_recoveries(limit=5).items

    assert [event.calculation_id for event in events] == [str(second_id), str(first_id)]
    assert events[0].recovery_kind == "stale_lease_recovered"
    assert events[1].recovery_kind == "retryable_failure"


def test_compute_job_store_lists_recent_recoveries_with_filters_and_offset(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    ids = [uuid4() for _ in range(3)]

    store.enqueue_job(calculation_id=ids[0], analytics_type="ReturnsSeries", request_payload={"p": "1"})
    store.enqueue_job(calculation_id=ids[1], analytics_type="Attribution", request_payload={"p": "2"})
    store.enqueue_job(calculation_id=ids[2], analytics_type="ReturnsSeries", request_payload={"p": "3"})

    with store._session() as session:
        first = store._get_model(session, ids[0])
        first.attempt_count = 1
        first.last_error_at_utc = now - timedelta(seconds=20)
        second = store._get_model(session, ids[1])
        second.attempt_count = 1
        second.last_error_at_utc = now - timedelta(seconds=10)
        third = store._get_model(session, ids[2])
        third.attempt_count = 1
        third.last_error_at_utc = now - timedelta(seconds=5)

    page = store.list_recent_recoveries(
        limit=1,
        offset=1,
        analytics_type="ReturnsSeries",
        calculation_id_contains=str(ids[0])[:8],
    )

    assert page.total_count == 1
    assert page.next_offset is None
    assert page.items == []


def test_compute_job_store_lists_recent_recoveries_with_time_filters_and_next_offset(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    ids = [uuid4() for _ in range(3)]

    for calculation_id in ids:
        store.enqueue_job(calculation_id=calculation_id, analytics_type="ReturnsSeries", request_payload={"p": "1"})

    with store._session() as session:
        for seconds_ago, calculation_id in zip([30, 15, 5], ids, strict=True):
            row = store._get_model(session, calculation_id)
            row.attempt_count = 1
            row.last_error_at_utc = now - timedelta(seconds=seconds_ago)

    page = store.list_recent_recoveries(
        limit=1,
        offset=0,
        recovered_after=now - timedelta(seconds=20),
        recovered_before=now - timedelta(seconds=4),
    )

    assert page.total_count == 2
    assert page.next_offset == 1
    assert page.next_cursor_recovered_before == page.items[-1].recovered_at_utc
    assert page.next_cursor_calculation_id_before == str(ids[2])
    assert [item.calculation_id for item in page.items] == [str(ids[2])]


def test_compute_job_store_lists_recent_recoveries_with_seek_cursor(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    ids = [uuid4() for _ in range(3)]

    for calculation_id in ids:
        store.enqueue_job(calculation_id=calculation_id, analytics_type="ReturnsSeries", request_payload={"p": "1"})

    with store._session() as session:
        for seconds_ago, calculation_id in zip([30, 20, 10], ids, strict=True):
            row = store._get_model(session, calculation_id)
            row.attempt_count = 1
            row.last_error_at_utc = now - timedelta(seconds=seconds_ago)

    first_page = store.list_recent_recoveries(limit=1)
    second_page = store.list_recent_recoveries(
        limit=1,
        cursor_recovered_before=now - timedelta(seconds=10),
        cursor_calculation_id_before=str(ids[2]),
    )

    assert [item.calculation_id for item in first_page.items] == [str(ids[2])]
    assert [item.calculation_id for item in second_page.items] == [str(ids[1])]


def test_compute_job_store_formats_sqlite_recovery_timestamps_as_utc(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()
    recovery_time = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    store.enqueue_job(calculation_id=calculation_id, analytics_type="ReturnsSeries", request_payload={"p": "1"})
    with store._session() as session:
        row = store._get_model(session, calculation_id)
        row.attempt_count = 1
        row.last_error_at_utc = recovery_time

    page = store.list_recent_recoveries(limit=1)

    assert page.items[0].recovered_at_utc == "2026-03-14T12:00:00Z"


def test_compute_recovery_query_filters_normalize_sqlite_utc_and_preserve_operator_filters():
    filters = _compute_recovery_query_filters(
        dialect_name="sqlite",
        analytics_type="ReturnsSeries",
        calculation_id_contains="calc-",
        recovered_after=datetime(2026, 3, 14, 20, 0, tzinfo=timezone(timedelta(hours=8))),
        recovered_before=datetime(2026, 3, 14, 13, 0, tzinfo=timezone.utc),
        cursor_recovered_before=datetime(2026, 3, 14, 12, 30, tzinfo=timezone.utc),
        cursor_calculation_id_before="calc-b",
    )

    assert filters.analytics_type == "ReturnsSeries"
    assert filters.calculation_id_contains == "calc-"
    assert filters.recovered_after == datetime(2026, 3, 14, 12, 0)
    assert filters.recovered_before == datetime(2026, 3, 14, 13, 0)
    assert filters.cursor_recovered_before == datetime(2026, 3, 14, 12, 30)
    assert filters.cursor_calculation_id_before == "calc-b"


def test_recovery_events_from_rows_suppresses_rows_without_recovery_timestamp(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    incomplete = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.PENDING,
        created_at_utc=now,
    )
    recovered = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.PENDING,
        created_at_utc=now,
    )
    recovered.last_error_at_utc = now
    recovered.error_type = "LeaseExpired"

    events = store._recovery_events_from_rows([incomplete, recovered])

    assert len(events) == 1
    assert events[0].calculation_id == recovered.calculation_id
    assert events[0].recovery_kind == "stale_lease_recovered"
    assert events[0].recovered_at_utc == "2026-03-14T12:00:00Z"


def test_recovery_seek_cursor_filter_without_calculation_tiebreaker_uses_timestamp_only():
    cursor_time = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    compiled = str(
        _recovery_seek_cursor_filter(
            cursor_recovered_before=cursor_time,
            cursor_calculation_id_before=None,
        ).compile(dialect=postgresql.dialect())
    )

    assert "last_error_at_utc <" in compiled
    assert "calculation_id <" not in compiled


def test_recovery_seek_cursor_filter_with_calculation_tiebreaker_uses_stable_seek_order():
    cursor_time = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    compiled = str(
        _recovery_seek_cursor_filter(
            cursor_recovered_before=cursor_time,
            cursor_calculation_id_before="calc-b",
        ).compile(dialect=postgresql.dialect())
    )

    assert "last_error_at_utc <" in compiled
    assert "last_error_at_utc =" in compiled
    assert "calculation_id <" in compiled


def test_compute_job_store_prunes_terminal_jobs_older_than_cutoff(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    old_id = uuid4()
    recent_id = uuid4()

    for calculation_id in (old_id, recent_id):
        store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"calculation_id": str(calculation_id)},
        )
        store.mark_complete(calculation_id, response_payload={"ok": True})

    with store._session() as session:
        old_row = store._get_model(session, old_id)
        recent_row = store._get_model(session, recent_id)
        old_row.completed_at_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
        recent_row.completed_at_utc = datetime(2026, 3, 10, tzinfo=timezone.utc)

    cutoff = datetime(2026, 2, 1, tzinfo=timezone.utc)

    assert store.prune_terminal_jobs_older_than(cutoff, dry_run=True) == 1
    assert store.prune_terminal_jobs_older_than(cutoff, dry_run=False) == 1
    assert store.get_job(old_id) is None
    assert store.get_job(recent_id) is not None


def test_compute_job_store_declares_hot_path_indexes(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()

    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspect(store._engine).get_indexes("analytics_compute_job")
    }

    assert indexes["ix_compute_job_status_created_at"] == ("job_status", "created_at_utc")
    assert indexes["ix_compute_job_status_analytics_type_created_at"] == (
        "job_status",
        "analytics_type",
        "created_at_utc",
    )
    assert indexes["ix_compute_job_status_lease_expiry"] == ("job_status", "lease_expires_at_utc")


def test_compute_job_store_register_job_distinguishes_create_replay_and_conflict(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    created = store.register_job(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        request_payload={"portfolio_id": "P1"},
        max_attempts=2,
    )
    replay = store.register_job(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        request_payload={"portfolio_id": "P1"},
        max_attempts=2,
    )
    conflict = store.register_job(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        request_payload={"portfolio_id": "P2"},
        max_attempts=2,
    )

    assert created.status == ComputeJobRegistrationStatus.CREATED
    assert replay.status == ComputeJobRegistrationStatus.REPLAY
    assert replay.existing_status == ComputeJobStatus.PENDING
    assert conflict.status == ComputeJobRegistrationStatus.CONFLICT


def test_compute_job_store_register_job_ignores_transient_observability_context_for_replay(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()

    created = store.register_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={
            "portfolio_id": "P1",
            "observability_context": {"correlation_id": "corr-first"},
        },
        max_attempts=2,
    )
    replay = store.register_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={
            "portfolio_id": "P1",
            "observability_context": {"correlation_id": "corr-second"},
        },
        max_attempts=2,
    )

    assert created.status == ComputeJobRegistrationStatus.CREATED
    assert replay.status == ComputeJobRegistrationStatus.REPLAY
    stored_job = store.get_job(calculation_id)
    assert stored_job is not None
    assert stored_job.request_payload["observability_context"] == {"correlation_id": "corr-first"}


@pytest.mark.parametrize(
    "stored_request_json",
    [
        "{not-json",
        "[1, 2, 3]",
    ],
)
def test_compute_job_request_identity_falls_back_to_stored_json_when_payload_is_not_object(stored_request_json):
    assert _compute_job_request_identity_json_from_json(stored_request_json) == stored_request_json


def test_matches_existing_compute_job_registration_requires_same_request_and_attempt_policy():
    existing = ComputeJobModel(
        calculation_id=str(uuid4()),
        analytics_type="Contribution",
        job_status=ComputeJobStatus.PENDING.value,
        request_json='{"portfolio_id": "P1"}',
        response_json=None,
        attempt_count=0,
        max_attempts=2,
        created_at_utc=datetime.now(timezone.utc),
    )

    assert _matches_existing_compute_job_registration(
        existing,
        analytics_type="Contribution",
        request_identity_json=_compute_job_request_identity_json({"portfolio_id": "P1"}),
        max_attempts=2,
    )
    assert not _matches_existing_compute_job_registration(
        existing,
        analytics_type="Contribution",
        request_identity_json=_compute_job_request_identity_json({"portfolio_id": "P2"}),
        max_attempts=2,
    )
    assert not _matches_existing_compute_job_registration(
        existing,
        analytics_type="Contribution",
        request_identity_json=_compute_job_request_identity_json({"portfolio_id": "P1"}),
        max_attempts=3,
    )
    assert not _matches_existing_compute_job_registration(
        existing,
        analytics_type="Attribution",
        request_identity_json=_compute_job_request_identity_json({"portfolio_id": "P1"}),
        max_attempts=2,
    )


def test_compute_job_registration_result_for_integrity_conflict_replays_matching_job():
    existing = ComputeJobModel(
        calculation_id=str(uuid4()),
        analytics_type="Contribution",
        job_status=ComputeJobStatus.PENDING.value,
        request_json='{"portfolio_id": "P1"}',
        response_json=None,
        attempt_count=0,
        max_attempts=2,
        created_at_utc=datetime.now(timezone.utc),
    )

    result = _compute_job_registration_result_for_integrity_conflict(
        existing,
        integrity_error=IntegrityError("insert", {}, RuntimeError("duplicate")),
        analytics_type="Contribution",
        request_identity_json=_compute_job_request_identity_json({"portfolio_id": "P1"}),
        max_attempts=2,
    )

    assert result.status == ComputeJobRegistrationStatus.REPLAY
    assert result.existing_status == ComputeJobStatus.PENDING


def test_compute_job_registration_result_for_integrity_conflict_reports_conflicting_job():
    existing = ComputeJobModel(
        calculation_id=str(uuid4()),
        analytics_type="Contribution",
        job_status=ComputeJobStatus.RUNNING.value,
        request_json='{"portfolio_id": "P1"}',
        response_json=None,
        attempt_count=1,
        max_attempts=2,
        created_at_utc=datetime.now(timezone.utc),
    )

    result = _compute_job_registration_result_for_integrity_conflict(
        existing,
        integrity_error=IntegrityError("insert", {}, RuntimeError("duplicate")),
        analytics_type="Contribution",
        request_identity_json=_compute_job_request_identity_json({"portfolio_id": "P2"}),
        max_attempts=2,
    )

    assert result.status == ComputeJobRegistrationStatus.CONFLICT
    assert result.existing_status == ComputeJobStatus.RUNNING


def test_compute_job_registration_result_for_integrity_conflict_reraises_missing_row():
    original_error = IntegrityError("insert", {}, RuntimeError("duplicate"))

    with pytest.raises(IntegrityError) as exc_info:
        _compute_job_registration_result_for_integrity_conflict(
            None,
            integrity_error=original_error,
            analytics_type="Contribution",
            request_identity_json=_compute_job_request_identity_json({"portfolio_id": "P1"}),
            max_attempts=2,
        )

    assert exc_info.value is original_error


@pytest.mark.parametrize(
    ("job_status", "expected_message"),
    [
        (ComputeJobStatus.FAILED, "Cannot mark failed job as running"),
        (ComputeJobStatus.COMPLETE, "Cannot mark complete job as running"),
    ],
)
def test_ensure_compute_job_can_mark_running_rejects_terminal_jobs(job_status, expected_message):
    calculation_id = uuid4()
    row = _compute_job_model_for_inspection(
        job_status=job_status,
        created_at_utc=datetime.now(timezone.utc),
    )

    with pytest.raises(ValueError, match=expected_message):
        _ensure_compute_job_can_mark_running(row, calculation_id=calculation_id, worker_id=None)


def test_ensure_compute_job_can_mark_running_rejects_other_worker_lease():
    calculation_id = uuid4()
    row = _compute_job_model_for_inspection(
        job_status=ComputeJobStatus.LEASED,
        created_at_utc=datetime.now(timezone.utc),
    )
    row.worker_id = "worker-a"

    with pytest.raises(ValueError, match="Compute job leased by another worker"):
        _ensure_compute_job_can_mark_running(row, calculation_id=calculation_id, worker_id="worker-b")


@pytest.mark.parametrize(
    ("current_worker_id", "requested_worker_id", "expected"),
    [
        (None, None, False),
        (None, "worker-a", False),
        ("worker-a", "worker-a", False),
        ("worker-a", None, False),
        ("worker-a", "worker-b", True),
    ],
)
def test_compute_job_has_conflicting_worker_lease(current_worker_id, requested_worker_id, expected):
    assert (
        _compute_job_has_conflicting_worker_lease(
            current_worker_id=current_worker_id,
            requested_worker_id=requested_worker_id,
        )
        is expected
    )


def test_compute_job_store_get_queue_stats_uses_single_aggregate_query(tmp_path):
    store = ComputeJobStore(f"sqlite:///{tmp_path / 'compute.db'}")
    store.create_schema()
    calculation_id = uuid4()
    now = datetime.now(timezone.utc)

    store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "P1"},
    )

    statements: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(store._engine, "before_cursor_execute", _before_cursor_execute)
    try:
        stats = store.get_queue_stats(now=now)
    finally:
        event.remove(store._engine, "before_cursor_execute", _before_cursor_execute)

    assert stats.pending_count == 1
    select_statements = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
    assert len(select_statements) == 1


def test_get_compute_job_store_resolves_explicit_database_url(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'explicit-compute.db'}"

    store = get_compute_job_store(database_url=database_url)

    assert isinstance(store, ComputeJobStore)
    assert str(store._engine.url) == database_url
