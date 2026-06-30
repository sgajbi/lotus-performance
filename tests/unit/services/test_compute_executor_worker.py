from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.attribution_requests import AttributionRequest
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest, ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.requests import PerformanceRequest
from app.models.returns_series import ReturnsSeriesRequest
from app.models.twr_requests import TWRInputMode, TWRResolvedExecutionRequest
from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services import (
    attribution_service,
    benchmark_service,
    contribution_service,
    execution_lifecycle_service,
    returns_series_service,
    twr_service,
)
from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_ATTRIBUTION,
    ANALYTICS_WORKFLOW_BENCHMARK,
    ANALYTICS_WORKFLOW_CONTRIBUTION,
    ANALYTICS_WORKFLOW_RETURNS_SERIES,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)
from app.services.async_result_store import AsyncResultStatus, AsyncResultStore
from app.services.compute_job_store import (
    ComputeJobLeaseOwnershipError,
    ComputeJobRecord,
    ComputeJobStatus,
    ComputeJobStore,
    ReconciledJobRecord,
)
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore
from app.services.lineage_service import LineageService
from app.workers import compute_executor_worker
from core.errors import APIServiceUnavailableError


def _worker_settings(**overrides):
    return type(
        "Settings",
        (),
        {
            "APP_VERSION": "1.0.0",
            "LOG_LEVEL": "INFO",
            "COMPUTE_EXECUTOR_BATCH_SIZE": 10,
            "COMPUTE_EXECUTOR_WORKER_ID": "worker-test",
            "COMPUTE_EXECUTOR_LEASE_SECONDS": 30,
            "COMPUTE_EXECUTOR_POLL_SECONDS": 5.0,
            **overrides,
        },
    )()


def _running_compute_job(
    tmp_path,
    *,
    calculation_id=None,
    max_attempts: int = 1,
) -> tuple[ComputeJobStore, ExecutionRegistry, AsyncResultStore, ComputeJobRecord]:
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    active_calculation_id = calculation_id or uuid4()
    execution_store.create_execution(
        calculation_id=active_calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=active_calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={"portfolio_id": "P1"},
        max_attempts=max_attempts,
    )
    job_store.lease_pending_jobs(worker_id="worker-a", limit=1, lease_seconds=30)
    job_store.mark_running(active_calculation_id, worker_id="worker-a", lease_seconds=30)
    job = job_store.get_job(active_calculation_id)
    assert job is not None
    return job_store, execution_store, result_store, job


def _compute_job_record(
    *,
    calculation_id,
    analytics_type: str,
    request_payload: dict,
    max_attempts: int = 1,
) -> ComputeJobRecord:
    return ComputeJobRecord(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        job_status=ComputeJobStatus.RUNNING,
        request_payload=request_payload,
        response_payload=None,
        error_message=None,
        error_type=None,
        attempt_count=0,
        max_attempts=max_attempts,
        worker_id="worker-test",
        leased_at_utc=None,
        lease_expires_at_utc=None,
        last_error_at_utc=None,
        created_at_utc="2026-01-01T00:00:00+00:00",
        started_at_utc="2026-01-01T00:00:00+00:00",
        completed_at_utc=None,
    )


def test_execute_compute_job_restores_async_context_for_any_executor(monkeypatch):
    observed: dict[str, str] = {}

    def _executor(job, context):  # noqa: ANN001, ANN202, ARG001
        observed["correlation_id"] = correlation_id_var.get()
        observed["request_id"] = request_id_var.get()
        observed["trace_id"] = trace_id_var.get()
        return "ok"

    original_executors = dict(compute_executor_worker._COMPUTE_JOB_EXECUTORS)
    monkeypatch.setitem(compute_executor_worker._COMPUTE_JOB_EXECUTORS, "AnyWorkflow", _executor)
    job = SimpleNamespace(
        analytics_type="AnyWorkflow",
        request_payload={
            "observability_context": {
                "correlation_id": "corr-any-workflow",
                "request_id": "req-any-workflow",
                "trace_id": "trace-any-workflow",
            }
        },
    )
    correlation_token = correlation_id_var.set("corr-outside")
    request_token = request_id_var.set("req-outside")
    trace_token = trace_id_var.set("trace-outside")

    try:
        assert compute_executor_worker._execute_compute_job(job, SimpleNamespace()) == "ok"
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)
        compute_executor_worker._COMPUTE_JOB_EXECUTORS.clear()
        compute_executor_worker._COMPUTE_JOB_EXECUTORS.update(original_executors)

    assert observed == {
        "correlation_id": "corr-any-workflow",
        "request_id": "req-any-workflow",
        "trace_id": "trace-any-workflow",
    }


def test_compute_executor_worker_runtime_builder_preserves_explicit_overrides(tmp_path):
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    settings = _worker_settings(COMPUTE_EXECUTOR_BATCH_SIZE=99, COMPUTE_EXECUTOR_WORKER_ID="settings-worker")

    async def _returns_series_calculator(*args, **kwargs):  # noqa: ANN202, ARG001
        return None

    def _calculator(*args, **kwargs):  # noqa: ANN202, ARG001
        return None

    runtime = compute_executor_worker._build_compute_job_runtime(
        limit=3,
        job_store=job_store,
        execution_store=execution_store,
        result_store=result_store,
        worker_id="explicit-worker",
        lease_seconds=12,
        returns_series_calculator=_returns_series_calculator,
        contribution_calculator=_calculator,
        attribution_calculator=_calculator,
        benchmark_calculator=_calculator,
        twr_calculator=_calculator,
        workspace_summary_calculator=_calculator,
        inspection_calculator=_calculator,
        settings=settings,
    )

    assert runtime.job_store is job_store
    assert runtime.execution_store is execution_store
    assert runtime.result_store is result_store
    assert runtime.worker_id == "explicit-worker"
    assert runtime.lease_seconds == 12
    assert runtime.batch_size == 3
    assert runtime.execution_context.settings is settings
    assert runtime.execution_context.returns_series_calculator is _returns_series_calculator
    assert runtime.execution_context.contribution_calculator is _calculator


def test_compute_executor_worker_process_leased_job_records_success_before_completion(monkeypatch):
    calculation_id = uuid4()
    job = _compute_job_record(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={"portfolio_id": "P1"},
    )
    response_payload = {"calculation_id": str(calculation_id), "portfolio_id": "P1"}
    response = SimpleNamespace(model_dump=lambda mode="json": response_payload)
    calls: list[tuple[str, object, object | None, object | None]] = []

    class _JobStore:
        def mark_running(self, calculation_id_arg, *, worker_id, lease_seconds):
            calls.append(("mark_running", calculation_id_arg, worker_id, lease_seconds))

        def ensure_active_lease_owner(self, calculation_id_arg, *, worker_id):
            calls.append(("ensure_active_lease_owner", calculation_id_arg, worker_id, None))

        def mark_complete(self, calculation_id_arg, *, response_payload, worker_id):
            calls.append(("mark_complete", calculation_id_arg, response_payload, worker_id))

    class _ResultStore:
        def record_success(self, *, calculation_id, analytics_type, response_payload):
            calls.append(("record_success", calculation_id, analytics_type, response_payload))

    runtime = compute_executor_worker._ComputeJobRuntime(
        job_store=_JobStore(),
        execution_store=SimpleNamespace(),
        result_store=_ResultStore(),
        worker_id="worker-test",
        lease_seconds=30,
        batch_size=1,
        execution_context=SimpleNamespace(),
    )
    monkeypatch.setattr(compute_executor_worker, "_execute_compute_job", lambda _job, _context: response)

    compute_executor_worker._process_leased_compute_job(job, runtime)

    assert calls == [
        ("mark_running", calculation_id, "worker-test", 30),
        ("ensure_active_lease_owner", calculation_id, "worker-test", None),
        ("record_success", calculation_id, ANALYTICS_WORKFLOW_RETURNS_SERIES, response_payload),
        ("mark_complete", calculation_id, response_payload, "worker-test"),
    ]


def test_compute_executor_worker_preserves_success_result_when_completion_fails(monkeypatch):
    calculation_id = uuid4()
    job = _compute_job_record(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={"portfolio_id": "P1"},
    )
    response_payload = {"calculation_id": str(calculation_id), "portfolio_id": "P1"}
    response = SimpleNamespace(model_dump=lambda mode="json": response_payload)
    calls: list[tuple[str, object, object | None, object | None]] = []
    exceptions: list[tuple[tuple, dict]] = []

    class _JobStore:
        def mark_running(self, calculation_id_arg, *, worker_id, lease_seconds):
            calls.append(("mark_running", calculation_id_arg, worker_id, lease_seconds))

        def ensure_active_lease_owner(self, calculation_id_arg, *, worker_id):
            calls.append(("ensure_active_lease_owner", calculation_id_arg, worker_id, None))

        def mark_complete(self, calculation_id_arg, *, response_payload, worker_id):
            calls.append(("mark_complete", calculation_id_arg, response_payload, worker_id))
            raise RuntimeError("job completion store outage")

        def mark_retryable_failure(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("success finalization must not mark retryable failure")

        def mark_failed(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("success finalization must not mark failed")

    class _ResultStore:
        def record_success(self, *, calculation_id, analytics_type, response_payload):
            calls.append(("record_success", calculation_id, analytics_type, response_payload))

        def record_failure(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("success finalization must not overwrite the result with failure")

    runtime = compute_executor_worker._ComputeJobRuntime(
        job_store=_JobStore(),
        execution_store=SimpleNamespace(),
        result_store=_ResultStore(),
        worker_id="worker-test",
        lease_seconds=30,
        batch_size=1,
        execution_context=SimpleNamespace(),
    )
    monkeypatch.setattr(compute_executor_worker, "_execute_compute_job", lambda _job, _context: response)
    monkeypatch.setattr(
        compute_executor_worker.logger,
        "exception",
        lambda *args, **kwargs: exceptions.append((args, kwargs)),
    )

    compute_executor_worker._process_leased_compute_job(job, runtime)

    assert calls == [
        ("mark_running", calculation_id, "worker-test", 30),
        ("ensure_active_lease_owner", calculation_id, "worker-test", None),
        ("record_success", calculation_id, ANALYTICS_WORKFLOW_RETURNS_SERIES, response_payload),
        ("mark_complete", calculation_id, response_payload, "worker-test"),
    ]
    assert exceptions and exceptions[0][0] == ("Compute job success finalization failed after result publication.",)
    extra_fields = exceptions[0][1]["extra"]["extra_fields"]
    assert extra_fields["failure_classification"] == "success_finalization_failed"


def test_compute_executor_worker_skips_stale_owner_success_after_reclaim(tmp_path, monkeypatch):
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    calculation_id = uuid4()
    response_payload = {"calculation_id": str(calculation_id), "portfolio_id": "P1"}
    response = SimpleNamespace(model_dump=lambda mode="json": response_payload)

    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={"portfolio_id": "P1"},
        max_attempts=2,
    )
    leased = job_store.lease_pending_jobs(worker_id="worker-a", limit=1, lease_seconds=30)
    assert len(leased) == 1

    def _execute_and_reclaim(_job, _context):
        with job_store._session() as session:
            row = job_store._get_model(session, calculation_id)
            row.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
        reconciled = job_store.reconcile_stale_jobs()
        assert len(reconciled) == 1
        assert reconciled[0].reconciled_status == ComputeJobStatus.PENDING
        reclaimed = job_store.lease_pending_jobs(worker_id="worker-b", limit=1, lease_seconds=30)
        assert len(reclaimed) == 1
        job_store.mark_running(calculation_id, worker_id="worker-b", lease_seconds=30)
        return response

    warnings: list[tuple[tuple, dict]] = []
    runtime = compute_executor_worker._ComputeJobRuntime(
        job_store=job_store,
        execution_store=SimpleNamespace(),
        result_store=result_store,
        worker_id="worker-a",
        lease_seconds=30,
        batch_size=1,
        execution_context=SimpleNamespace(),
    )
    monkeypatch.setattr(compute_executor_worker, "_execute_compute_job", _execute_and_reclaim)
    monkeypatch.setattr(
        compute_executor_worker.logger,
        "warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    compute_executor_worker._process_leased_compute_job(leased[0], runtime)

    assert result_store.get_result(calculation_id) is None
    current_job = job_store.get_job(calculation_id)
    assert current_job is not None
    assert current_job.job_status == ComputeJobStatus.RUNNING
    assert current_job.worker_id == "worker-b"
    assert current_job.response_payload is None
    assert warnings and warnings[0][0] == (
        "Skipped compute job success publication because worker no longer owns the active lease.",
    )
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["failure_classification"] == "stale_owner_success_publication_skipped"


def test_compute_executor_worker_skips_stale_owner_retryable_failure_finalization(monkeypatch):
    calculation_id = uuid4()
    job = _compute_job_record(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={"portfolio_id": "P1"},
        max_attempts=2,
    )
    warnings: list[tuple[tuple, dict]] = []

    class _JobStore:
        def mark_retryable_failure(self, calculation_id_arg, *, error_message, error_type, worker_id):
            assert calculation_id_arg == calculation_id
            assert error_message == "transient outage"
            assert error_type == "RuntimeError"
            assert worker_id == "worker-test"
            raise ComputeJobLeaseOwnershipError("stale worker")

        def mark_failed(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("stale retryable failure must not mark terminal failure")

    class _ResultStore:
        def record_failure(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("stale retryable failure must not write async result failure")

    monkeypatch.setattr(
        compute_executor_worker.logger,
        "warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    compute_executor_worker._handle_compute_job_failure(
        job,
        RuntimeError("transient outage"),
        job_store=_JobStore(),
        result_store=_ResultStore(),
        execution_store=SimpleNamespace(),
    )

    assert warnings and warnings[0][0] == (
        "Skipped compute job failure finalization because worker no longer owns the active lease.",
    )
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["failure_classification"] == "stale_owner_failure_finalization_skipped"
    assert extra_fields["retryable"] is True
    assert extra_fields["error_type"] == "RuntimeError"
    assert extra_fields["ownership_error_type"] == "ComputeJobLeaseOwnershipError"


def test_compute_executor_worker_skips_stale_owner_terminal_failure_finalization(monkeypatch):
    calculation_id = uuid4()
    job = _compute_job_record(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={"portfolio_id": "P1"},
        max_attempts=1,
    )
    warnings: list[tuple[tuple, dict]] = []

    class _JobStore:
        def mark_retryable_failure(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("non-retryable failure must not mark retryable failure")

        def mark_failed(self, calculation_id_arg, *, error_message, error_type, worker_id):
            assert calculation_id_arg == calculation_id
            assert error_message == "bad input"
            assert error_type == "ValueError"
            assert worker_id == "worker-test"
            raise ComputeJobLeaseOwnershipError("stale worker")

    class _ResultStore:
        def record_failure(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("stale terminal failure must not write async result failure")

    monkeypatch.setattr(
        compute_executor_worker.logger,
        "warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    compute_executor_worker._handle_compute_job_failure(
        job,
        ValueError("bad input"),
        job_store=_JobStore(),
        result_store=_ResultStore(),
        execution_store=SimpleNamespace(),
    )

    assert warnings and warnings[0][0] == (
        "Skipped compute job failure finalization because worker no longer owns the active lease.",
    )
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["failure_classification"] == "stale_owner_failure_finalization_skipped"
    assert extra_fields["retryable"] is False
    assert extra_fields["error_type"] == "ValueError"
    assert extra_fields["ownership_error_type"] == "ComputeJobLeaseOwnershipError"


def test_compute_executor_worker_does_not_complete_job_when_success_result_publication_fails(monkeypatch):
    calculation_id = uuid4()
    job = _compute_job_record(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={"portfolio_id": "P1"},
        max_attempts=2,
    )
    response_payload = {"calculation_id": str(calculation_id), "portfolio_id": "P1"}
    response = SimpleNamespace(model_dump=lambda mode="json": response_payload)
    calls: list[tuple[str, object, object | None]] = []
    exceptions: list[tuple[tuple, dict]] = []

    class _JobStore:
        def mark_running(self, calculation_id_arg, *, worker_id, lease_seconds):
            calls.append(("mark_running", calculation_id_arg, worker_id))

        def ensure_active_lease_owner(self, calculation_id_arg, *, worker_id):
            calls.append(("ensure_active_lease_owner", calculation_id_arg, worker_id))

        def mark_complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("job must not complete without a persisted result")

        def mark_retryable_failure(self, calculation_id_arg, *, error_message, error_type, worker_id):
            calls.append(("mark_retryable_failure", calculation_id_arg, error_type))
            assert worker_id == "worker-test"
            return True

    class _ResultStore:
        def record_success(self, *, calculation_id, analytics_type, response_payload):  # noqa: ARG002
            calls.append(("record_success", calculation_id, analytics_type))
            raise RuntimeError("result store outage")

        def record_failure(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("retryable result publication failure must not write terminal failure")

    runtime = compute_executor_worker._ComputeJobRuntime(
        job_store=_JobStore(),
        execution_store=SimpleNamespace(),
        result_store=_ResultStore(),
        worker_id="worker-test",
        lease_seconds=30,
        batch_size=1,
        execution_context=SimpleNamespace(),
    )
    monkeypatch.setattr(compute_executor_worker, "_execute_compute_job", lambda _job, _context: response)
    monkeypatch.setattr(
        compute_executor_worker.logger,
        "exception",
        lambda *args, **kwargs: exceptions.append((args, kwargs)),
    )
    monkeypatch.setattr(compute_executor_worker.logger, "warning", lambda *args, **kwargs: None)

    compute_executor_worker._process_leased_compute_job(job, runtime)

    assert calls == [
        ("mark_running", calculation_id, "worker-test"),
        ("ensure_active_lease_owner", calculation_id, "worker-test"),
        ("record_success", calculation_id, ANALYTICS_WORKFLOW_RETURNS_SERIES),
        ("mark_retryable_failure", calculation_id, "RuntimeError"),
    ]
    assert exceptions and exceptions[0][0] == (
        "Compute job success result publication failed after calculation completed.",
    )
    extra_fields = exceptions[0][1]["extra"]["extra_fields"]
    assert extra_fields["failure_classification"] == "success_result_publication_failed"


def test_compute_executor_worker_runtime_options_use_settings_defaults(tmp_path):
    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    settings = _worker_settings(
        COMPUTE_EXECUTOR_BATCH_SIZE=7,
        COMPUTE_EXECUTOR_WORKER_ID="settings-worker",
        COMPUTE_EXECUTOR_LEASE_SECONDS=45,
    )

    options = compute_executor_worker._resolve_compute_job_runtime_options(
        limit=None,
        job_store=job_store,
        execution_store=execution_store,
        result_store=result_store,
        worker_id=None,
        lease_seconds=None,
        settings=settings,
    )

    assert options.settings is settings
    assert options.job_store is job_store
    assert options.execution_store is execution_store
    assert options.result_store is result_store
    assert options.worker_id == "settings-worker"
    assert options.lease_seconds == 45
    assert options.batch_size == 7


def test_compute_executor_worker_runtime_options_preserve_truthy_default_policy(tmp_path):
    settings = _worker_settings(
        COMPUTE_EXECUTOR_BATCH_SIZE=7,
        COMPUTE_EXECUTOR_WORKER_ID="settings-worker",
        COMPUTE_EXECUTOR_LEASE_SECONDS=45,
    )

    options = compute_executor_worker._resolve_compute_job_runtime_options(
        limit=0,
        job_store=None,
        execution_store=None,
        result_store=None,
        worker_id="",
        lease_seconds=0,
        settings=settings,
    )

    assert options.worker_id == "settings-worker"
    assert options.lease_seconds == 45
    assert options.batch_size == 7


def test_compute_executor_worker_execution_context_preserves_all_calculator_overrides(tmp_path):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    settings = _worker_settings()

    async def _returns_series_calculator(*args, **kwargs):  # noqa: ANN202, ARG001
        return None

    def _calculator(*args, **kwargs):  # noqa: ANN202, ARG001
        return None

    context = compute_executor_worker._build_compute_job_execution_context(
        settings=settings,
        execution_store=execution_store,
        returns_series_calculator=_returns_series_calculator,
        contribution_calculator=_calculator,
        attribution_calculator=_calculator,
        benchmark_calculator=_calculator,
        twr_calculator=_calculator,
        workspace_summary_calculator=_calculator,
        inspection_calculator=_calculator,
    )

    assert context.settings is settings
    assert context.execution_store is execution_store
    assert context.returns_series_calculator is _returns_series_calculator
    assert context.contribution_calculator is _calculator
    assert context.attribution_calculator is _calculator
    assert context.benchmark_calculator is _calculator
    assert context.twr_calculator is _calculator
    assert context.workspace_summary_calculator is _calculator
    assert context.inspection_calculator is _calculator


def test_compute_executor_worker_calculator_options_use_default_calculators():
    calculators = compute_executor_worker._resolve_compute_job_calculators(
        returns_series_calculator=None,
        contribution_calculator=None,
        attribution_calculator=None,
        benchmark_calculator=None,
        twr_calculator=None,
        workspace_summary_calculator=None,
        inspection_calculator=None,
    )

    assert calculators.returns_series_calculator is compute_executor_worker.calculate_returns_series
    assert calculators.contribution_calculator is compute_executor_worker.calculate_contribution
    assert calculators.attribution_calculator is compute_executor_worker.calculate_attribution
    assert calculators.benchmark_calculator is compute_executor_worker.calculate_benchmark_response
    assert calculators.twr_calculator is compute_executor_worker.calculate_twr_response
    assert calculators.workspace_summary_calculator is compute_executor_worker.calculate_workspace_summary
    assert calculators.inspection_calculator is compute_executor_worker.run_twr_inspection


def test_compute_executor_worker_calculator_options_preserve_truthy_default_policy():
    class FalsyCalculator:
        def __call__(self, *args, **kwargs):  # noqa: ANN202, ANN002, ANN003, ARG002
            return None

        def __bool__(self):
            return False

    falsy_calculator = FalsyCalculator()

    calculators = compute_executor_worker._resolve_compute_job_calculators(
        returns_series_calculator=falsy_calculator,
        contribution_calculator=falsy_calculator,
        attribution_calculator=falsy_calculator,
        benchmark_calculator=falsy_calculator,
        twr_calculator=falsy_calculator,
        workspace_summary_calculator=falsy_calculator,
        inspection_calculator=falsy_calculator,
    )

    assert calculators.returns_series_calculator is compute_executor_worker.calculate_returns_series
    assert calculators.contribution_calculator is compute_executor_worker.calculate_contribution
    assert calculators.attribution_calculator is compute_executor_worker.calculate_attribution
    assert calculators.benchmark_calculator is compute_executor_worker.calculate_benchmark_response
    assert calculators.twr_calculator is compute_executor_worker.calculate_twr_response
    assert calculators.workspace_summary_calculator is compute_executor_worker.calculate_workspace_summary
    assert calculators.inspection_calculator is compute_executor_worker.run_twr_inspection


def test_compute_executor_worker_dispatches_known_workflow_through_executor_registry(monkeypatch):
    job = SimpleNamespace(analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES)
    context = SimpleNamespace()
    captured = {}

    def _executor(job_arg, context_arg):  # noqa: ANN202, ANN001
        captured["job"] = job_arg
        captured["context"] = context_arg
        return "handled"

    monkeypatch.setitem(
        compute_executor_worker._COMPUTE_JOB_EXECUTORS,
        ANALYTICS_WORKFLOW_RETURNS_SERIES,
        _executor,
    )

    assert compute_executor_worker._execute_compute_job(job, context) == "handled"
    assert captured == {"job": job, "context": context}


def test_compute_executor_worker_executor_lookup_rejects_unsupported_workflow():
    with pytest.raises(ValueError, match="Unsupported compute job analytics_type: unsupported"):
        compute_executor_worker._compute_job_executor_for("unsupported")


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
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={
            **request.model_dump(mode="json"),
            "observability_context": {
                "correlation_id": "corr-async-returns-series",
                "request_id": "req-async-returns-series",
                "trace_id": "trace-async-returns-series",
            },
        },
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
    assert result.response_payload["metadata"]["correlation_id"] == "corr-async-returns-series"
    assert result.response_payload["metadata"]["request_id"] == "req-async-returns-series"
    assert result.response_payload["metadata"]["trace_id"] == "trace-async-returns-series"
    assert correlation_id_var.get() != "corr-async-returns-series"


def test_compute_executor_worker_dispatches_benchmark_job_and_updates_execution_identity(tmp_path):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        portfolio_id="BMK_1",
        execution_mode="async",
        requested_window={},
    )
    request = BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "benchmark_currency": "USD",
            "return_source": "calculated",
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                }
            ],
        }
    )
    captured: dict = {}

    async def _unused_async(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("unexpected async calculator")

    def _unused(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("unexpected calculator")

    def _benchmark_calculator(request_arg, **kwargs):
        captured["request"] = request_arg
        captured.update(kwargs)
        return SimpleNamespace(model_dump=lambda mode: {"status": "complete", "mode": mode})

    context = compute_executor_worker._ComputeJobExecutionContext(
        settings=_worker_settings(APP_VERSION="9.9.9"),
        execution_store=execution_store,
        returns_series_calculator=_unused_async,
        contribution_calculator=_unused,
        attribution_calculator=_unused,
        benchmark_calculator=_benchmark_calculator,
        twr_calculator=_unused,
        workspace_summary_calculator=_unused,
        inspection_calculator=_unused,
    )
    job = _compute_job_record(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        request_payload=request.model_dump(mode="json"),
    )

    response = compute_executor_worker._execute_compute_job(job, context)

    assert response.model_dump(mode="json") == {"status": "complete", "mode": "json"}
    assert captured["request"] == request
    assert captured["input_mode"] == compute_executor_worker.BenchmarkInputMode.STATEFUL
    assert captured["engine_version"] == "9.9.9"
    assert captured["request_artifact_model"] == request
    execution = execution_store.get_execution(calculation_id)
    assert execution is not None
    assert execution.input_fingerprint
    assert execution.calculation_hash


def test_compute_executor_worker_processes_resolved_stateful_returns_series_job(tmp_path, monkeypatch):
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
    resolved_request = ReturnsSeriesRequest.model_validate(
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
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload={
            "resolved_request": resolved_request.model_dump(mode="json"),
            "source_input_mode": "stateful",
        },
    )

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE
    assert result.response_payload["provenance"]["input_mode"] == "stateful"


def test_resolve_async_returns_series_job_request_preserves_risk_free_source_quality():
    resolved_request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "input_mode": "stateless",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": True},
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.01"},
                    {"date": "2026-02-24", "return_value": "0.02"},
                    {"date": "2026-02-25", "return_value": "0.03"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-23", "return_value": "0.0001"},
                    {"date": "2026-02-24", "return_value": "0.0001"},
                    {"date": "2026-02-25", "return_value": "0.0001"},
                ],
            },
        }
    )

    request, source_input_mode, _, _, quality = compute_executor_worker._resolve_async_returns_series_job_request(
        {
            "resolved_request": resolved_request.model_dump(mode="json"),
            "source_input_mode": "stateful",
            "risk_free_source_quality": {"raw_points": 5, "normalized_points": 3, "skipped_points": 2},
        }
    )

    assert request == resolved_request
    assert source_input_mode.value == "stateful"
    assert quality is not None
    assert quality.raw_points == 5
    assert quality.normalized_points == 3
    assert quality.skipped_points == 2


def test_compute_executor_worker_processes_resolved_benchmark_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(benchmark_service, "execution_registry", execution_store)
    monkeypatch.setattr(execution_lifecycle_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        execution_lifecycle_service,
        "lineage_service",
        LineageService(storage_path=str(tmp_path / "lineage"), metadata_store=lineage_store),
    )

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    resolved_request = BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2026-01-02",
            "report_end_date": "2026-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "return_source": "calculated",
            "benchmark_currency": "USD",
            "component_observations": [
                {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "component_return": 0.01},
                {"component_id": "IDX_B", "perf_date": "2026-01-02", "weight_bop": 0.4, "component_return": 0.02},
                {"component_id": "IDX_A", "perf_date": "2026-01-03", "weight_bop": 0.6, "component_return": 0.01},
                {"component_id": "IDX_B", "perf_date": "2026-01-03", "weight_bop": 0.4, "component_return": 0.02},
            ],
        }
    )

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        portfolio_id="BMK_1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        request_payload={
            "resolved_request": resolved_request.model_dump(mode="json"),
            "source_input_mode": "stateful",
        },
    )

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE
    assert result.response_payload["input_mode"] == "stateful"
    assert result.response_payload["benchmark_id"] == "BMK_1"


def test_compute_executor_worker_processes_resolved_twr_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(twr_service, "execution_registry", execution_store)
    monkeypatch.setattr(execution_lifecycle_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        execution_lifecycle_service,
        "lineage_service",
        LineageService(storage_path=str(tmp_path / "lineage"), metadata_store=lineage_store),
    )

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    resolved_request = TWRResolvedExecutionRequest(
        portfolio=PerformanceRequest.model_validate(
            {
                "calculation_id": str(calculation_id),
                "portfolio_id": "P1",
                "performance_start_date": "2024-12-31",
                "report_end_date": "2025-01-02",
                "metric_basis": "NET",
                "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                    {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
                ],
            }
        ),
        benchmark=BenchmarkPerformanceRequest.model_validate(
            {
                "calculation_id": str(calculation_id),
                "benchmark_id": "BMK_1",
                "benchmark_start_date": "2025-01-01",
                "report_end_date": "2025-01-02",
                "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                "return_source": "calculated",
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-01-02", "weight_bop": 1.0, "component_return": 0.01},
                ],
            }
        ),
    )

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_TWR,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_TWR,
        request_payload={
            "resolved_request": resolved_request.model_dump(mode="json"),
            "source_input_mode": "stateful",
            "benchmark_input_mode": "stateful",
            "resolved_benchmark_id": "BMK_1",
            "benchmark_return_source": "calculated",
            "portfolio_id": "P1",
        },
    )

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE
    assert result.response_payload["input_mode"] == TWRInputMode.STATEFUL.value
    benchmark_context = result.response_payload["benchmark_context"]
    assert benchmark_context["benchmark_id"] == "BMK_1"
    assert benchmark_context["benchmark_currency"] == "USD"
    assert benchmark_context["input_mode"] == "stateful"
    assert benchmark_context["return_source"] == "calculated"
    assert benchmark_context["supportability_evidence"]["calendar_alignment_state"] == "aligned"
    assert benchmark_context["supportability_evidence"]["currency_state"] == "single_currency"
    period_result = result.response_payload["results_by_period"]["YTD"]
    assert period_result["benchmark"]["benchmark_id"] == "BMK_1"
    assert period_result["relative_performance"] is not None


def test_compute_executor_worker_processes_pending_contribution_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(contribution_service, "execution_registry", execution_store)
    monkeypatch.setattr(execution_lifecycle_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        execution_lifecycle_service,
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
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {
                    "position_id": "Stock_A",
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                        {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                    ],
                }
            ],
        }
    )

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
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


def test_compute_executor_worker_processes_pending_workspace_summary_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    request_payload = {
        "calculation_id": str(calculation_id),
        "portfolio_id": "P1",
        "report_end_date": "2026-03-31",
        "performance_start_date": "2025-12-31",
        "input_mode": "stateless",
        "periods": [{"period": "1M", "frequencies": ["daily"]}],
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2026-03-31", "begin_mv": 1000.0, "end_mv": 1010.0},
            ]
        },
    }

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
        request_payload=request_payload,
    )

    captured: dict[str, str] = {}

    def _workspace_summary_calculator(workspace_request, *, settings):
        captured["input_mode"] = workspace_request.input_mode.value
        return type(
            "WorkspaceSummaryResponseStub",
            (),
            {
                "model_dump": lambda self, mode="json": {
                    "calculation_id": str(workspace_request.calculation_id),
                    "portfolio_id": workspace_request.portfolio_id,
                    "input_mode": workspace_request.input_mode.value,
                    "meta": {"engine_version": settings.APP_VERSION},
                }
            },
        )()

    assert (
        compute_executor_worker._process_pending_jobs(
            limit=10,
            workspace_summary_calculator=_workspace_summary_calculator,
            settings=_worker_settings(APP_VERSION="test-version"),
        )
        == 1
    )

    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.COMPLETE
    assert captured["input_mode"] == "stateless"

    execution = execution_store.get_execution(calculation_id)
    assert execution is not None
    assert execution.input_fingerprint is not None
    assert execution.calculation_hash is not None

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE
    assert result.response_payload["portfolio_id"] == "P1"


def test_compute_executor_worker_updates_identity_for_stateful_contribution_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(contribution_service, "execution_registry", execution_store)
    monkeypatch.setattr(execution_lifecycle_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        execution_lifecycle_service,
        "lineage_service",
        LineageService(storage_path=str(tmp_path / "lineage"), metadata_store=lineage_store),
    )

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    analytics_request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    resolved_request = ContributionRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {
                    "position_id": "Stock_A",
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                        {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                    ],
                }
            ],
        }
    )

    async def _resolve_contribution_request(*_args, **_kwargs):
        return type(
            "ResolvedContribution",
            (),
            {
                "contribution_request": resolved_request,
                "input_mode": ContributionInputMode.STATEFUL,
            },
        )()

    monkeypatch.setattr(
        compute_executor_worker,
        "resolve_contribution_request",
        _resolve_contribution_request,
    )

    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
        input_fingerprint="stale-fingerprint",
        calculation_hash="stale-hash",
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
        request_payload=analytics_request.model_dump(mode="json"),
    )

    worker_settings = _worker_settings()
    assert compute_executor_worker.process_pending_jobs(limit=10, settings=worker_settings) == 1

    expected_input_fingerprint, expected_calculation_hash = compute_executor_worker.generate_canonical_hash(
        resolved_request,
        worker_settings.APP_VERSION,
    )
    execution = execution_store.get_execution(calculation_id)
    assert execution is not None
    assert execution.input_fingerprint == expected_input_fingerprint
    assert execution.calculation_hash == expected_calculation_hash


def test_compute_executor_worker_processes_pending_attribution_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(attribution_service, "execution_registry", execution_store)
    monkeypatch.setattr(execution_lifecycle_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        execution_lifecycle_service,
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
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
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


def test_compute_executor_worker_processes_resolved_stateful_attribution_job(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "execution_registry", execution_store)
    monkeypatch.setattr(attribution_service, "execution_registry", execution_store)
    monkeypatch.setattr(execution_lifecycle_service, "execution_registry", execution_store)
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "async_result_store", result_store)
    lineage_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    lineage_store.create_schema()
    monkeypatch.setattr(
        execution_lifecycle_service,
        "lineage_service",
        LineageService(storage_path=str(tmp_path / "lineage"), metadata_store=lineage_store),
    )

    job_store = ComputeJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    job_store.create_schema()
    monkeypatch.setattr(compute_executor_worker, "compute_job_store", job_store)

    calculation_id = uuid4()
    resolved_request = AttributionRequest.model_validate(
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
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
        request_payload={
            "resolved_request": resolved_request.model_dump(mode="json"),
            "source_input_mode": "stateful",
            "resolved_benchmark_id": "BMK_1",
            "resolved_benchmark_return_source": "calculated",
        },
    )

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE
    assert result.response_payload["input_mode"] == "stateful"
    assert result.response_payload["benchmark_context"] == {
        "benchmark_id": "BMK_1",
        "return_source": "calculated",
    }


def test_compute_executor_worker_resolves_attribution_job_from_resolved_payload():
    resolved_request = AttributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
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

    result = compute_executor_worker._resolved_async_attribution_job_request_from_payload(
        {
            "resolved_request": resolved_request.model_dump(mode="json"),
            "source_input_mode": "stateful",
            "resolved_benchmark_id": "BMK_1",
            "resolved_benchmark_return_source": "calculated",
        }
    )

    assert result is not None
    request, input_mode, benchmark_id, benchmark_return_source = result
    assert request == resolved_request
    assert input_mode == compute_executor_worker.AttributionInputMode.STATEFUL
    assert benchmark_id == "BMK_1"
    assert benchmark_return_source == "calculated"


def test_compute_executor_worker_skips_attribution_resolved_payload_without_input_mode():
    assert (
        compute_executor_worker._resolved_async_attribution_job_request_from_payload(
            {"resolved_request": {"portfolio_id": "P1"}}
        )
        is None
    )


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
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
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
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload=request.model_dump(mode="json"),
        max_attempts=2,
    )

    async def _retryable(_request):
        raise APIServiceUnavailableError("upstream unavailable")

    monkeypatch.setattr(compute_executor_worker, "calculate_returns_series", _retryable)

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1
    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.PENDING
    assert job.attempt_count == 1
    assert job.error_type == "APIServiceUnavailableError"
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
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        request_payload=request.model_dump(mode="json"),
        max_attempts=1,
    )

    async def _retryable(_request):
        raise APIServiceUnavailableError("upstream unavailable")

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
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
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
    logged: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        compute_executor_worker.logger, "exception", lambda *args, **kwargs: logged.append((args, kwargs))
    )

    compute_executor_worker._record_terminal_failure(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        error_message="boom",
        error_type="RuntimeError",
        missing_execution_log_message="Execution record missing for compute job %s",
    )

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.error_type == "RuntimeError"
    assert logged
    extra_fields = logged[0][1]["extra"]["extra_fields"]
    assert extra_fields["worker_name"] == "compute_executor_worker"
    assert extra_fields["queue"] == "compute"
    assert extra_fields["calculation_id"] == str(calculation_id)
    assert extra_fields["analytics_type"] == ANALYTICS_WORKFLOW_RETURNS_SERIES
    assert extra_fields["failure_classification"] == "terminal_compute_failure"
    assert extra_fields["retryable"] is False


def test_compute_executor_worker_run_forever_bootstraps_and_sleeps(monkeypatch):
    calls: list[str] = []
    settings = _worker_settings(COMPUTE_EXECUTOR_POLL_SECONDS=7.0)
    monkeypatch.setattr(
        compute_executor_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(compute_executor_worker.compute_job_store, "create_schema", lambda: calls.append("job_schema"))
    monkeypatch.setattr(
        compute_executor_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(
        compute_executor_worker,
        "process_pending_jobs",
        lambda **kwargs: calls.append("process") or 0,
    )

    def _sleep(seconds):
        calls.append(f"sleep:{seconds}")
        raise RuntimeError("stop")

    monkeypatch.setattr(compute_executor_worker.time, "sleep", _sleep)

    with pytest.raises(RuntimeError, match="stop"):
        compute_executor_worker.run_forever(settings=settings)

    assert calls == [
        "exec_schema",
        "job_schema",
        "result_schema",
        "process",
        f"sleep:{settings.COMPUTE_EXECUTOR_POLL_SECONDS}",
    ]


def test_compute_executor_worker_run_forever_honors_pre_set_stop_event(monkeypatch):
    stop_event = Event()
    stop_event.set()
    calls: list[str] = []
    settings = _worker_settings()

    monkeypatch.setattr(
        compute_executor_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(compute_executor_worker.compute_job_store, "create_schema", lambda: calls.append("job_schema"))
    monkeypatch.setattr(
        compute_executor_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(
        compute_executor_worker,
        "process_pending_jobs",
        lambda **kwargs: calls.append("process") or 1,
    )

    compute_executor_worker.run_forever(stop_event=stop_event, settings=settings)

    assert calls == ["exec_schema", "job_schema", "result_schema"]


def test_compute_executor_worker_run_forever_stops_during_idle_wait(monkeypatch):
    stop_event = Event()
    calls: list[str] = []
    settings = _worker_settings(COMPUTE_EXECUTOR_POLL_SECONDS=3.0)

    monkeypatch.setattr(
        compute_executor_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(compute_executor_worker.compute_job_store, "create_schema", lambda: calls.append("job_schema"))
    monkeypatch.setattr(
        compute_executor_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(
        compute_executor_worker,
        "process_pending_jobs",
        lambda **kwargs: calls.append("process") or 0,
    )

    def _wait(timeout: float) -> bool:
        calls.append(f"wait:{timeout}")
        stop_event.set()
        return True

    monkeypatch.setattr(stop_event, "wait", _wait)

    compute_executor_worker.run_forever(stop_event=stop_event, settings=settings)

    assert calls == [
        "exec_schema",
        "job_schema",
        "result_schema",
        "process",
        f"wait:{settings.COMPUTE_EXECUTOR_POLL_SECONDS}",
    ]


def test_compute_executor_worker_logs_requeued_stale_job(monkeypatch):
    class _ReconciledJob:
        def __init__(self):
            self.calculation_id = uuid4()
            self.analytics_type = "ReturnsSeries"
            self.reconciled_status = type("Status", (), {"value": "pending"})()
            self.previous_status = type("Status", (), {"value": "running"})()
            self.attempt_count = 1
            self.max_attempts = 2
            self.error_type = "LeaseExpired"

    warnings: list[tuple[tuple, dict]] = []
    job_store = type(
        "JobStore",
        (),
        {
            "reconcile_stale_jobs": lambda self: [_ReconciledJob()],
            "lease_pending_jobs": lambda self, **kwargs: [],
        },
    )()
    monkeypatch.setattr(
        compute_executor_worker.logger, "warning", lambda *args, **kwargs: warnings.append((args, kwargs))
    )

    processed = compute_executor_worker._process_pending_jobs(
        job_store=job_store,
        execution_store=compute_executor_worker.execution_registry,
        result_store=SimpleNamespace(get_result=lambda calculation_id: None),
        settings=_worker_settings(),
    )

    assert processed == 0
    assert warnings and warnings[0][0] == ("Requeued stale compute job after expired lease",)
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["worker_name"] == "compute_executor_worker"
    assert extra_fields["queue"] == "compute"
    assert extra_fields["analytics_type"] == "ReturnsSeries"
    assert extra_fields["previous_status"] == "running"
    assert extra_fields["failure_classification"] == "stale_compute_lease_requeued"


def test_compute_executor_worker_handles_reconciled_stale_requeue(monkeypatch):
    warnings: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        compute_executor_worker.logger, "warning", lambda *args, **kwargs: warnings.append((args, kwargs))
    )
    reconciled_job = ReconciledJobRecord(
        calculation_id=uuid4(),
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        previous_status=ComputeJobStatus.RUNNING,
        reconciled_status=ComputeJobStatus.PENDING,
        attempt_count=1,
        max_attempts=2,
        error_message="lease expired",
        error_type="LeaseExpired",
    )

    compute_executor_worker._handle_reconciled_stale_job(
        reconciled_job,
        job_store=SimpleNamespace(mark_complete=lambda *args, **kwargs: None),
        result_store=SimpleNamespace(get_result=lambda calculation_id: None),
        execution_store=compute_executor_worker.execution_registry,
    )

    assert warnings and warnings[0][0] == ("Requeued stale compute job after expired lease",)
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["calculation_id"] == str(reconciled_job.calculation_id)
    assert extra_fields["analytics_type"] == ANALYTICS_WORKFLOW_RETURNS_SERIES
    assert extra_fields["previous_status"] == "running"
    assert extra_fields["reconciled_status"] == "pending"
    assert extra_fields["failure_classification"] == "stale_compute_lease_requeued"
    assert extra_fields["attempt_count"] == 1
    assert extra_fields["max_attempts"] == 2


def test_compute_executor_worker_handles_reconciled_stale_terminal_failure(tmp_path):
    result_store = AsyncResultStore(f"sqlite:///{tmp_path / 'results.db'}")
    result_store.create_schema()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    reconciled_job = ReconciledJobRecord(
        calculation_id=calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        previous_status=ComputeJobStatus.RUNNING,
        reconciled_status=ComputeJobStatus.FAILED,
        attempt_count=2,
        max_attempts=2,
        error_message="lease expired after retry budget",
        error_type="LeaseExpired",
    )

    compute_executor_worker._handle_reconciled_stale_job(
        reconciled_job,
        job_store=SimpleNamespace(mark_complete=lambda *args, **kwargs: None),
        result_store=result_store,
        execution_store=execution_store,
    )

    result = result_store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.error_type == "LeaseExpired"
    execution = execution_store.get_execution(calculation_id)
    assert execution is not None
    assert execution.status.value == "failed"


def test_compute_executor_worker_recovers_reconciled_job_from_persisted_success_result(tmp_path, monkeypatch):
    job_store, execution_store, result_store, job = _running_compute_job(tmp_path, max_attempts=1)
    response_payload = {"calculation_id": str(job.calculation_id), "portfolio_id": "P1"}
    result_store.record_success(
        calculation_id=job.calculation_id,
        analytics_type=job.analytics_type,
        response_payload=response_payload,
    )
    reconciled_job = ReconciledJobRecord(
        calculation_id=job.calculation_id,
        analytics_type=job.analytics_type,
        previous_status=ComputeJobStatus.RUNNING,
        reconciled_status=ComputeJobStatus.FAILED,
        attempt_count=1,
        max_attempts=1,
        error_message="lease expired after retry budget",
        error_type="LeaseExpired",
    )
    warnings: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        compute_executor_worker.logger, "warning", lambda *args, **kwargs: warnings.append((args, kwargs))
    )

    compute_executor_worker._handle_reconciled_stale_job(
        reconciled_job,
        job_store=job_store,
        result_store=result_store,
        execution_store=execution_store,
    )

    updated_job = job_store.get_job(job.calculation_id)
    assert updated_job is not None
    assert updated_job.job_status == ComputeJobStatus.COMPLETE
    assert updated_job.response_payload == response_payload
    result = result_store.get_result(job.calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE
    execution = execution_store.get_execution(job.calculation_id)
    assert execution is not None
    assert execution.status.value != "failed"
    assert warnings and warnings[0][0] == ("Recovered compute job completion from persisted success result.",)
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["failure_classification"] == "success_finalization_recovered"
    assert extra_fields["reconciled_status"] == "complete"


def test_compute_executor_worker_handles_retryable_failure_with_remaining_budget(tmp_path, monkeypatch):
    job_store, execution_store, result_store, job = _running_compute_job(tmp_path, max_attempts=2)
    warnings: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        compute_executor_worker.logger, "warning", lambda *args, **kwargs: warnings.append((args, kwargs))
    )

    compute_executor_worker._handle_compute_job_failure(
        job,
        RuntimeError("temporary store outage"),
        job_store=job_store,
        result_store=result_store,
        execution_store=execution_store,
    )

    updated_job = job_store.get_job(job.calculation_id)
    assert updated_job is not None
    assert updated_job.job_status == ComputeJobStatus.PENDING
    assert updated_job.error_type == "RuntimeError"
    assert result_store.get_result(job.calculation_id) is None
    execution = execution_store.get_execution(job.calculation_id)
    assert execution is not None
    assert execution.status.value == "pending"
    assert warnings and warnings[0][0] == ("Retrying compute job after retryable failure",)
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["worker_name"] == "compute_executor_worker"
    assert extra_fields["queue"] == "compute"
    assert extra_fields["calculation_id"] == str(job.calculation_id)
    assert extra_fields["analytics_type"] == ANALYTICS_WORKFLOW_RETURNS_SERIES
    assert extra_fields["error_type"] == "RuntimeError"
    assert extra_fields["failure_classification"] == "retryable_compute_failure"
    assert extra_fields["retryable"] is True


def test_compute_executor_worker_handles_retryable_failure_after_exhausted_budget(tmp_path):
    job_store, execution_store, result_store, job = _running_compute_job(tmp_path, max_attempts=1)

    compute_executor_worker._handle_compute_job_failure(
        job,
        RuntimeError("temporary store outage"),
        job_store=job_store,
        result_store=result_store,
        execution_store=execution_store,
    )

    updated_job = job_store.get_job(job.calculation_id)
    assert updated_job is not None
    assert updated_job.job_status == ComputeJobStatus.FAILED
    result = result_store.get_result(job.calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.error_type == "RuntimeError"
    execution = execution_store.get_execution(job.calculation_id)
    assert execution is not None
    assert execution.status.value == "failed"


def test_compute_executor_worker_handles_non_retryable_failure(tmp_path):
    job_store, execution_store, result_store, job = _running_compute_job(tmp_path, max_attempts=2)

    compute_executor_worker._handle_compute_job_failure(
        job,
        ValueError("unsupported analytics type"),
        job_store=job_store,
        result_store=result_store,
        execution_store=execution_store,
    )

    updated_job = job_store.get_job(job.calculation_id)
    assert updated_job is not None
    assert updated_job.job_status == ComputeJobStatus.FAILED
    assert updated_job.error_type == "ValueError"
    result = result_store.get_result(job.calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.error_type == "ValueError"
    execution = execution_store.get_execution(job.calculation_id)
    assert execution is not None
    assert execution.status.value == "failed"


def test_compute_executor_worker_rejects_unsupported_analytics_type(tmp_path, monkeypatch):
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
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="Unknown",
        portfolio_id="P1",
        execution_mode="async",
        requested_window={},
    )
    job_store.enqueue_job(
        calculation_id=calculation_id,
        analytics_type="Unknown",
        request_payload={"portfolio_id": "P1"},
        max_attempts=1,
    )

    assert compute_executor_worker.process_pending_jobs(limit=10) == 1
    job = job_store.get_job(calculation_id)
    assert job is not None
    assert job.job_status == ComputeJobStatus.FAILED
    assert "Unsupported compute job analytics_type" in (job.error_message or "")


def test_compute_executor_worker_resolves_benchmark_jobs_from_persisted_stateful_payload():
    request = BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "benchmark_currency": "USD",
            "return_source": "calculated",
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                }
            ],
        }
    )

    resolved_request, input_mode = compute_executor_worker._resolve_async_benchmark_job_request(
        request.model_dump(mode="json"),
        settings=_worker_settings(),
    )

    assert resolved_request == request
    assert input_mode == compute_executor_worker.BenchmarkInputMode.STATEFUL


def test_compute_executor_worker_resolves_twr_jobs_from_resolved_payload_and_raw_analytics_payload(monkeypatch):
    resolved_request_payload = {
        "portfolio": {
            "portfolio_id": "P1",
            "performance_start_date": "2025-01-01",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1001.0}],
        },
        "benchmark": None,
    }
    persisted = {
        "resolved_request": resolved_request_payload,
        "source_input_mode": "stateful",
        "benchmark_input_mode": "stateful",
        "resolved_benchmark_id": "BMK_1",
        "benchmark_return_source": "calculated",
        "portfolio_id": "P1",
    }

    (
        resolved_request,
        input_mode,
        request_artifact_model,
        portfolio_id,
        benchmark_id,
        benchmark_input_mode,
        source,
        should_update,
    ) = compute_executor_worker._resolve_async_twr_job_request(
        persisted,
        settings=_worker_settings(),
    )
    assert input_mode == compute_executor_worker.TWRInputMode.STATEFUL
    assert request_artifact_model == resolved_request
    assert portfolio_id == "P1"
    assert benchmark_id == "BMK_1"
    assert benchmark_input_mode == compute_executor_worker.BenchmarkInputMode.STATEFUL
    assert source == "calculated"
    assert should_update is True

    persisted_without_optional_identity = {
        "resolved_request": resolved_request_payload,
        "source_input_mode": "stateful",
        "benchmark_input_mode": None,
        "resolved_benchmark_id": 123,
    }

    (
        resolved_request,
        input_mode,
        request_artifact_model,
        portfolio_id,
        benchmark_id,
        benchmark_input_mode,
        source,
        should_update,
    ) = compute_executor_worker._resolve_async_twr_job_request(
        persisted_without_optional_identity,
        settings=_worker_settings(),
    )

    assert input_mode == compute_executor_worker.TWRInputMode.STATEFUL
    assert request_artifact_model == resolved_request
    assert portfolio_id == "P1"
    assert benchmark_id is None
    assert benchmark_input_mode is None
    assert source == "calculated"
    assert should_update is True

    analytics_request = compute_executor_worker.TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P2",
            "performance_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "metric_basis": "NET",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1001.0}],
        }
    )

    async def _resolve_twr_request(request, settings):  # noqa: ARG001
        return SimpleNamespace(
            performance_request=PerformanceRequest.model_validate(
                {
                    "portfolio_id": request.portfolio_id,
                    "performance_start_date": "2025-01-01",
                    "metric_basis": "NET",
                    "report_end_date": "2025-01-02",
                    "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1001.0}],
                }
            ),
            benchmark_request=None,
            input_mode=compute_executor_worker.TWRInputMode.STATELESS,
            resolved_benchmark_id=None,
            benchmark_input_mode=None,
        )

    monkeypatch.setattr(compute_executor_worker, "resolve_twr_request", _resolve_twr_request)

    (
        resolved_request,
        input_mode,
        request_artifact_model,
        portfolio_id,
        benchmark_id,
        benchmark_input_mode,
        source,
        should_update,
    ) = compute_executor_worker._resolve_async_twr_job_request(
        analytics_request.model_dump(mode="json"),
        settings=_worker_settings(),
    )

    assert input_mode == compute_executor_worker.TWRInputMode.STATELESS
    assert request_artifact_model.portfolio_id == "P2"
    assert portfolio_id == "P2"
    assert benchmark_id is None
    assert benchmark_input_mode is None
    assert source == "calculated"
    assert should_update is False
