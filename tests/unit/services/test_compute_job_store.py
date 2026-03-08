from uuid import uuid4

import pytest

from app.services.compute_job_store import ComputeJobStatus, ComputeJobStore


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

    store.mark_running(calculation_id)
    running = store.get_job(calculation_id)
    assert running is not None
    assert running.job_status == ComputeJobStatus.RUNNING
    assert running.attempt_count == 1

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

    pending = store.list_pending_jobs(analytics_type="ReturnsSeries", limit=1)
    assert len(pending) == 1
    assert pending[0].calculation_id == calc_one

    store.mark_failed(calc_one, error_message="boom")
    failed = store.get_job(calc_one)
    assert failed is not None
    assert failed.job_status == ComputeJobStatus.FAILED
    assert failed.error_message == "boom"

    store.clear_all_records()
    assert store.get_job(calc_one) is None
    with pytest.raises(KeyError):
        store.mark_running(calc_one)
