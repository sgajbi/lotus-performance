from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.attribution_requests import AttributionRequest
from app.models.contribution_requests import ContributionRequest
from app.models.returns_series import ReturnsSeriesRequest
from app.services import attribution_service, contribution_service, returns_series_service
from app.services.async_result_store import AsyncResultStatus, AsyncResultStore
from app.services.compute_job_store import ComputeJobStatus, ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore
from app.services.lineage_service import LineageService
from app.workers import compute_executor_worker


def test_compute_executor_worker_processes_pending_returns_series_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(returns_series_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)

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
    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE


def test_compute_executor_worker_processes_pending_contribution_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(contribution_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        contribution_service,
        "lineage_service",
        LineageService(storage_path=str(tmp_path / "lineage"), metadata_store=lineage_store),
    )

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"day": 2, "perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {
                    "position_id": "Stock_A",
                    "valuation_points": [
                        {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                        {"day": 2, "perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                    ],
                }
            ],
        }
    )

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="Contribution",
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
    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE


def test_compute_executor_worker_processes_pending_attribution_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(attribution_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        attribution_service,
        "lineage_service",
        LineageService(storage_path=str(tmp_path / "lineage"), metadata_store=lineage_store),
    )

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    request = AttributionRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "portfolio_id": "P1",
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_groups_data": [
                {
                    "key": {"sector": "Tech"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "Tech"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
                }
            ],
        }
    )

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="Attribution",
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="Attribution",
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
    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE


def test_compute_executor_worker_marks_failed_and_handles_missing_execution(tmp_path, monkeypatch):
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(returns_series_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)

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
            "stateless_input": {"portfolio_returns": [{"date": "2026-02-23", "return_value": "0.01"}]},
        }
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        request_payload=request.model_dump(mode="json"),
        max_attempts=1,
    )

    async def _boom(_request):
        raise RuntimeError("explode")

    monkeypatch.setattr(compute_executor_worker, "calculate_returns_series", _boom)
    calls: list[str] = []
    monkeypatch.setattr(compute_executor_worker.logger, "exception", lambda *args, **kwargs: calls.append("logged"))

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1
    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.FAILED
    assert calls == ["logged"]
    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED


def test_compute_executor_worker_requeues_retryable_failure(tmp_path, monkeypatch):
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)

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
            "stateless_input": {"portfolio_returns": [{"date": "2026-02-23", "return_value": "0.01"}]},
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
        max_attempts=2,
    )

    async def _retryable(_request):
        raise HTTPException(status_code=503, detail="upstream unavailable")

    monkeypatch.setattr(compute_executor_worker, "calculate_returns_series", _retryable)

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1
    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.PENDING
    assert job.attempt_count == 1
    assert job.error_type == "HTTPException"
    assert result_store.get_result(calculation_id) is None


def test_compute_executor_worker_marks_failed_after_retry_budget_exhausted(tmp_path, monkeypatch):
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)

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
            "stateless_input": {"portfolio_returns": [{"date": "2026-02-23", "return_value": "0.01"}]},
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
        max_attempts=1,
    )

    async def _retryable(_request):
        raise HTTPException(status_code=503, detail="upstream unavailable")

    monkeypatch.setattr(compute_executor_worker, "calculate_returns_series", _retryable)

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1
    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.FAILED
    assert job.attempt_count == 1
    execution = execution_store.get_execution(calculation_id)
    assert execution is not None
    assert execution.status.value == "failed"
    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED


def test_compute_executor_worker_reconciles_stale_running_job(tmp_path, monkeypatch):
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)

    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)

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
            "stateless_input": {"portfolio_returns": [{"date": "2026-02-23", "return_value": "0.01"}]},
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
        max_attempts=1,
    )
    job_store.lease_pending_jobs(worker_id="worker-a", limit=1, lease_seconds=30)
    job_store.mark_running(calculation_id, worker_id="worker-a", lease_seconds=30)
    with job_store._session() as session:
        row = job_store._get_model(session, calculation_id)
        row.lease_expires_at_utc = row.started_at_utc

    assert compute_executor_worker.process_pending_jobs(limit=10) == 0

    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.FAILED
    execution = execution_store.get_execution(calculation_id)
    assert execution is not None
    assert execution.status.value == "failed"
    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.error_type == "LeaseExpired"


def test_compute_executor_worker_records_terminal_failure_when_execution_missing(tmp_path, monkeypatch):
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)

    calculation_id = uuid4()
    logged: list[str] = []
    monkeypatch.setattr(compute_executor_worker.logger, "exception", lambda *args, **kwargs: logged.append("logged"))

    compute_executor_worker._record_terminal_failure(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        error_message="boom",
        error_type="RuntimeError",
        missing_execution_log_message="Execution record missing for compute job %s",
    )

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.error_type == "RuntimeError"
    assert logged == ["logged"]


def test_compute_executor_worker_run_forever_bootstraps_and_sleeps(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        compute_executor_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(compute_executor_worker.compute_job_store, "create_schema", lambda: calls.append("job_schema"))
    monkeypatch.setattr(
        compute_executor_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(compute_executor_worker, "process_pending_jobs", lambda: calls.append("process") or 0)

    def _sleep(seconds):
        calls.append(f"sleep:{seconds}")
        raise RuntimeError("stop")

    monkeypatch.setattr(compute_executor_worker.time, "sleep", _sleep)

    with pytest.raises(RuntimeError, match="stop"):
        compute_executor_worker.run_forever()

    assert calls == [
        "exec_schema",
        "job_schema",
        "result_schema",
        "process",
        f"sleep:{compute_executor_worker.settings.COMPUTE_EXECUTOR_POLL_SECONDS}",
    ]


def test_compute_executor_worker_run_forever_honors_pre_set_stop_event(monkeypatch):
    stop_event = Event()
    stop_event.set()
    calls: list[str] = []

    monkeypatch.setattr(
        compute_executor_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(compute_executor_worker.compute_job_store, "create_schema", lambda: calls.append("job_schema"))
    monkeypatch.setattr(
        compute_executor_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(compute_executor_worker, "process_pending_jobs", lambda: calls.append("process") or 1)

    compute_executor_worker.run_forever(stop_event=stop_event)

    assert calls == ["exec_schema", "job_schema", "result_schema"]


def test_compute_executor_worker_run_forever_stops_during_idle_wait(monkeypatch):
    stop_event = Event()
    calls: list[str] = []

    monkeypatch.setattr(
        compute_executor_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(compute_executor_worker.compute_job_store, "create_schema", lambda: calls.append("job_schema"))
    monkeypatch.setattr(
        compute_executor_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(compute_executor_worker, "process_pending_jobs", lambda: calls.append("process") or 0)

    def _wait(timeout: float) -> bool:
        calls.append(f"wait:{timeout}")
        stop_event.set()
        return True

    monkeypatch.setattr(stop_event, "wait", _wait)

    compute_executor_worker.run_forever(stop_event=stop_event)

    assert calls == [
        "exec_schema",
        "job_schema",
        "result_schema",
        "process",
        f"wait:{compute_executor_worker.settings.COMPUTE_EXECUTOR_POLL_SECONDS}",
    ]
