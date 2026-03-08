from uuid import uuid4

from app.models.returns_series import ReturnsSeriesRequest
from app.services import returns_series_service
from app.services.compute_job_store import ComputeJobStatus, ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.workers import compute_executor_worker


def test_compute_executor_worker_processes_pending_returns_series_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(returns_series_service, "execution_registry", execution_store)

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    request = ReturnsSeriesRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.01"},
                    {"date": "2026-02-24", "return_value": "0.02"},
                    {"date": "2026-02-25", "return_value": "0.03"},
                ]
            },
        }
    )

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload=request.model_dump(mode="json"),
    )

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1

    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.COMPLETE
    assert job.response_payload is not None

    execution = execution_store.get_execution(calculation_id)
    assert execution is not None
    assert execution.status.value == "complete"
