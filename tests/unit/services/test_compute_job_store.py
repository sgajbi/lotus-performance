from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from app.services.compute_job_store import (
    ComputeJobRegistrationStatus,
    ComputeJobStatus,
    ComputeJobStore,
)


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

    store.mark_complete(calculation_id, response_payload={"calculation_id": str(calculation_id)})
    complete = store.get_job(calculation_id)
    assert complete is not None
    assert complete.job_status == ComputeJobStatus.COMPLETE
    assert complete.response_payload == {"calculation_id": str(calculation_id)}


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
