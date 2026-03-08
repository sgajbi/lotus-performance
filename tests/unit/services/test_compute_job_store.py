from uuid import uuid4

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
