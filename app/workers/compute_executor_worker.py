from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from threading import Event
from typing import Any, Callable, Coroutine, Iterator
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest, ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.inspection_requests import TWRInspectionRequest
from app.models.returns_series import InputMode, ReturnPoint, ReturnsSeriesRequest, RiskFreeSourceQuality
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode, TWRResolvedExecutionRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.observability import (
    correlation_id_var,
    request_id_var,
    setup_worker_logging,
    trace_id_var,
    worker_log_extra,
)
from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_ATTRIBUTION,
    ANALYTICS_WORKFLOW_BENCHMARK,
    ANALYTICS_WORKFLOW_CONTRIBUTION,
    ANALYTICS_WORKFLOW_RETURNS_SERIES,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_TWR_INSPECTION,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)
from app.services.async_observability_context import ASYNC_OBSERVABILITY_CONTEXT_FIELD
from app.services.async_result_store import AsyncResultStatus, AsyncResultStore, async_result_store
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.attribution_service import calculate_attribution
from app.services.benchmark_mode_service import resolve_benchmark_request
from app.services.benchmark_service import calculate_benchmark_response
from app.services.calculation_engine_version import calculation_engine_version
from app.services.compute_job_store import (
    ComputeJobLeaseOwnershipError,
    ComputeJobRecord,
    ComputeJobStore,
    ReconciledJobRecord,
    compute_job_store,
)
from app.services.contribution_mode_service import resolve_contribution_request
from app.services.contribution_service import calculate_contribution
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.execution_stage_errors import safe_unexpected_failure_message
from app.services.inspection import run_twr_inspection
from app.services.returns_series_service import calculate_returns_series, to_dataframe
from app.services.twr_mode_service import resolve_twr_request
from app.services.twr_service import calculate_twr_response
from app.services.workspace_summary_service import calculate_workspace_summary
from app.workers.lineage_worker import process_pending_calculation as process_pending_lineage_calculation
from core.errors import APIError
from core.repro import generate_canonical_hash, generate_canonical_hash_from_value
from engine.exceptions import EngineCalculationError, InvalidEngineInputError

logger = logging.getLogger(__name__)

_WORKER_NAME = "compute_executor_worker"
_QUEUE_NAME = "compute"


class WorkspaceSummaryLineageNotReadyError(RuntimeError):
    """Raised when workspace-summary lineage is not complete before result publication."""


@dataclass(frozen=True)
class _ComputeJobExecutionContext:
    settings: Any
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry]
    returns_series_calculator: Callable[..., Coroutine[Any, Any, Any]]
    contribution_calculator: Callable[..., Any]
    attribution_calculator: Callable[..., Any]
    benchmark_calculator: Callable[..., Any]
    twr_calculator: Callable[..., Any]
    workspace_summary_calculator: Callable[..., Any]
    workspace_summary_lineage_materializer: Callable[..., bool]
    inspection_calculator: Callable[[TWRInspectionRequest], Any]


_ComputeJobExecutor = Callable[[ComputeJobRecord, _ComputeJobExecutionContext], Any]


@dataclass(frozen=True)
class _ComputeJobRuntime:
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore]
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry]
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore]
    worker_id: str
    lease_seconds: int
    batch_size: int
    execution_context: _ComputeJobExecutionContext


@dataclass(frozen=True)
class _ComputeJobRuntimeOptions:
    settings: Any
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore]
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry]
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore]
    worker_id: str
    lease_seconds: int
    batch_size: int


@dataclass(frozen=True)
class _ComputeJobCalculators:
    returns_series_calculator: Callable[..., Coroutine[Any, Any, Any]]
    contribution_calculator: Callable[..., Any]
    attribution_calculator: Callable[..., Any]
    benchmark_calculator: Callable[..., Any]
    twr_calculator: Callable[..., Any]
    workspace_summary_calculator: Callable[..., Any]
    workspace_summary_lineage_materializer: Callable[..., bool]
    inspection_calculator: Callable[[TWRInspectionRequest], Any]


def process_pending_jobs(*, limit: int | None = None, settings=None) -> int:
    return _process_pending_jobs(limit=limit, settings=settings)


def _process_pending_jobs(
    *,
    limit: int | None = None,
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore] | None = None,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] | None = None,
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore] | None = None,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
    returns_series_calculator: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    contribution_calculator: Callable[..., Any] | None = None,
    attribution_calculator: Callable[..., Any] | None = None,
    benchmark_calculator: Callable[..., Any] | None = None,
    twr_calculator: Callable[..., Any] | None = None,
    workspace_summary_calculator: Callable[..., Any] | None = None,
    workspace_summary_lineage_materializer: Callable[..., bool] | None = None,
    inspection_calculator: Callable[[TWRInspectionRequest], Any] | None = None,
    settings=None,
) -> int:
    runtime = _build_compute_job_runtime(
        limit=limit,
        job_store=job_store,
        execution_store=execution_store,
        result_store=result_store,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        returns_series_calculator=returns_series_calculator,
        contribution_calculator=contribution_calculator,
        attribution_calculator=attribution_calculator,
        benchmark_calculator=benchmark_calculator,
        twr_calculator=twr_calculator,
        workspace_summary_calculator=workspace_summary_calculator,
        workspace_summary_lineage_materializer=workspace_summary_lineage_materializer,
        inspection_calculator=inspection_calculator,
        settings=settings,
    )
    _reconcile_stale_compute_jobs(runtime)
    pending = runtime.job_store.lease_pending_jobs(
        worker_id=runtime.worker_id,
        limit=runtime.batch_size,
        lease_seconds=runtime.lease_seconds,
    )
    processed = 0
    for job in pending:
        _process_leased_compute_job(job, runtime)
        processed += 1
    return processed


def _reconcile_stale_compute_jobs(runtime: _ComputeJobRuntime) -> None:
    for reconciled_job in runtime.job_store.reconcile_stale_jobs():
        _handle_reconciled_stale_job(
            reconciled_job,
            job_store=runtime.job_store,
            result_store=runtime.result_store,
            execution_store=runtime.execution_store,
        )


def _process_leased_compute_job(job: ComputeJobRecord, runtime: _ComputeJobRuntime) -> None:
    acquisition_worker_id = _compute_job_acquisition_worker_id(
        compute_worker_id=runtime.worker_id,
        calculation_id=job.calculation_id,
    )
    runtime.job_store.mark_running_acquired(
        job.calculation_id,
        current_worker_id=runtime.worker_id,
        acquisition_worker_id=acquisition_worker_id,
        lease_seconds=runtime.lease_seconds,
    )
    active_runtime = replace(runtime, worker_id=acquisition_worker_id)
    active_job = replace(job, worker_id=acquisition_worker_id)
    try:
        response = _execute_compute_job(active_job, active_runtime.execution_context)
        _materialize_workspace_summary_lineage_before_success_publication(active_job, active_runtime)
    except Exception as exc:
        _handle_compute_job_failure(
            active_job,
            exc,
            job_store=active_runtime.job_store,
            result_store=active_runtime.result_store,
            execution_store=active_runtime.execution_store,
        )
        return

    response_payload = response.model_dump(mode="json")
    _publish_compute_job_success(active_job, runtime=active_runtime, response_payload=response_payload)


def _publish_compute_job_success(
    job: ComputeJobRecord,
    *,
    runtime: _ComputeJobRuntime,
    response_payload: dict[str, Any],
) -> None:
    try:
        runtime.job_store.ensure_active_lease_owner(job.calculation_id, worker_id=runtime.worker_id)
    except ComputeJobLeaseOwnershipError as exc:
        _log_stale_compute_success_publication_skipped(job, exc)
        return

    try:
        runtime.result_store.record_success(
            calculation_id=job.calculation_id,
            analytics_type=job.analytics_type,
            response_payload=response_payload,
        )
    except Exception as exc:
        _handle_compute_success_result_publication_failure(
            job,
            exc,
            job_store=runtime.job_store,
            result_store=runtime.result_store,
            execution_store=runtime.execution_store,
        )
        return

    try:
        runtime.job_store.mark_complete(
            job.calculation_id,
            response_payload=response_payload,
            worker_id=runtime.worker_id,
        )
    except Exception as exc:
        _log_compute_success_finalization_failure(job, exc)


def _materialize_workspace_summary_lineage_before_success_publication(
    job: ComputeJobRecord,
    runtime: _ComputeJobRuntime,
) -> None:
    if job.analytics_type != ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY:
        return
    _renew_workspace_summary_compute_lease(job, runtime)
    lineage_worker_id = _workspace_summary_inline_lineage_worker_id(
        compute_worker_id=runtime.worker_id,
        calculation_id=job.calculation_id,
    )
    if not runtime.execution_context.workspace_summary_lineage_materializer(
        job.calculation_id,
        worker_id=lineage_worker_id,
        settings=runtime.execution_context.settings,
    ):
        raise WorkspaceSummaryLineageNotReadyError(
            f"Workspace-summary lineage was not complete before async result publication: {job.calculation_id}"
        )
    _renew_workspace_summary_compute_lease(job, runtime)


def _renew_workspace_summary_compute_lease(job: ComputeJobRecord, runtime: _ComputeJobRuntime) -> None:
    runtime.job_store.renew_lease(
        job.calculation_id,
        worker_id=runtime.worker_id,
        lease_seconds=runtime.lease_seconds,
    )


def _workspace_summary_inline_lineage_worker_id(*, compute_worker_id: str, calculation_id: UUID) -> str:
    return f"inline-ws:{calculation_id.hex[:12]}:{uuid4().hex}"


def _compute_job_acquisition_worker_id(*, compute_worker_id: str, calculation_id: UUID) -> str:
    return f"{compute_worker_id}:cj:{calculation_id.hex[:12]}:{uuid4().hex}"


def _build_compute_job_runtime(
    *,
    limit: int | None,
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore] | None,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] | None,
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore] | None,
    worker_id: str | None,
    lease_seconds: int | None,
    returns_series_calculator: Callable[..., Coroutine[Any, Any, Any]] | None,
    contribution_calculator: Callable[..., Any] | None,
    attribution_calculator: Callable[..., Any] | None,
    benchmark_calculator: Callable[..., Any] | None,
    twr_calculator: Callable[..., Any] | None,
    workspace_summary_calculator: Callable[..., Any] | None,
    workspace_summary_lineage_materializer: Callable[..., bool] | None,
    inspection_calculator: Callable[[TWRInspectionRequest], Any] | None,
    settings,
) -> _ComputeJobRuntime:
    runtime_options = _resolve_compute_job_runtime_options(
        limit=limit,
        job_store=job_store,
        execution_store=execution_store,
        result_store=result_store,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        settings=settings,
    )
    return _ComputeJobRuntime(
        job_store=runtime_options.job_store,
        execution_store=runtime_options.execution_store,
        result_store=runtime_options.result_store,
        worker_id=runtime_options.worker_id,
        lease_seconds=runtime_options.lease_seconds,
        batch_size=runtime_options.batch_size,
        execution_context=_build_compute_job_execution_context(
            settings=runtime_options.settings,
            execution_store=runtime_options.execution_store,
            returns_series_calculator=returns_series_calculator,
            contribution_calculator=contribution_calculator,
            attribution_calculator=attribution_calculator,
            benchmark_calculator=benchmark_calculator,
            twr_calculator=twr_calculator,
            workspace_summary_calculator=workspace_summary_calculator,
            workspace_summary_lineage_materializer=workspace_summary_lineage_materializer,
            inspection_calculator=inspection_calculator,
        ),
    )


def _resolve_compute_job_runtime_options(
    *,
    limit: int | None,
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore] | None,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] | None,
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore] | None,
    worker_id: str | None,
    lease_seconds: int | None,
    settings,
) -> _ComputeJobRuntimeOptions:
    active_settings = settings or get_settings()
    return _ComputeJobRuntimeOptions(
        settings=active_settings,
        job_store=_truthy_or_default(job_store, compute_job_store),
        execution_store=_truthy_or_default(execution_store, execution_registry),
        result_store=_truthy_or_default(result_store, async_result_store),
        worker_id=_truthy_or_default(worker_id, active_settings.COMPUTE_EXECUTOR_WORKER_ID),
        lease_seconds=_truthy_or_default(lease_seconds, active_settings.COMPUTE_EXECUTOR_LEASE_SECONDS),
        batch_size=_truthy_or_default(limit, active_settings.COMPUTE_EXECUTOR_BATCH_SIZE),
    )


def _truthy_or_default(value: Any, default: Any) -> Any:
    return value or default


def _build_compute_job_execution_context(
    *,
    settings,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
    returns_series_calculator: Callable[..., Coroutine[Any, Any, Any]] | None,
    contribution_calculator: Callable[..., Any] | None,
    attribution_calculator: Callable[..., Any] | None,
    benchmark_calculator: Callable[..., Any] | None,
    twr_calculator: Callable[..., Any] | None,
    workspace_summary_calculator: Callable[..., Any] | None,
    workspace_summary_lineage_materializer: Callable[..., bool] | None,
    inspection_calculator: Callable[[TWRInspectionRequest], Any] | None,
) -> _ComputeJobExecutionContext:
    calculators = _resolve_compute_job_calculators(
        returns_series_calculator=returns_series_calculator,
        contribution_calculator=contribution_calculator,
        attribution_calculator=attribution_calculator,
        benchmark_calculator=benchmark_calculator,
        twr_calculator=twr_calculator,
        workspace_summary_calculator=workspace_summary_calculator,
        workspace_summary_lineage_materializer=workspace_summary_lineage_materializer,
        inspection_calculator=inspection_calculator,
    )
    return _ComputeJobExecutionContext(
        settings=settings,
        execution_store=execution_store,
        returns_series_calculator=calculators.returns_series_calculator,
        contribution_calculator=calculators.contribution_calculator,
        attribution_calculator=calculators.attribution_calculator,
        benchmark_calculator=calculators.benchmark_calculator,
        twr_calculator=calculators.twr_calculator,
        workspace_summary_calculator=calculators.workspace_summary_calculator,
        workspace_summary_lineage_materializer=calculators.workspace_summary_lineage_materializer,
        inspection_calculator=calculators.inspection_calculator,
    )


def _resolve_compute_job_calculators(
    *,
    returns_series_calculator: Callable[..., Coroutine[Any, Any, Any]] | None,
    contribution_calculator: Callable[..., Any] | None,
    attribution_calculator: Callable[..., Any] | None,
    benchmark_calculator: Callable[..., Any] | None,
    twr_calculator: Callable[..., Any] | None,
    workspace_summary_calculator: Callable[..., Any] | None,
    workspace_summary_lineage_materializer: Callable[..., bool] | None,
    inspection_calculator: Callable[[TWRInspectionRequest], Any] | None,
) -> _ComputeJobCalculators:
    return _ComputeJobCalculators(
        returns_series_calculator=_truthy_or_default(returns_series_calculator, calculate_returns_series),
        contribution_calculator=_truthy_or_default(contribution_calculator, calculate_contribution),
        attribution_calculator=_truthy_or_default(attribution_calculator, calculate_attribution),
        benchmark_calculator=_truthy_or_default(benchmark_calculator, calculate_benchmark_response),
        twr_calculator=_truthy_or_default(twr_calculator, calculate_twr_response),
        workspace_summary_calculator=_truthy_or_default(
            workspace_summary_calculator,
            calculate_workspace_summary,
        ),
        workspace_summary_lineage_materializer=_truthy_or_default(
            workspace_summary_lineage_materializer,
            process_pending_lineage_calculation,
        ),
        inspection_calculator=_truthy_or_default(inspection_calculator, run_twr_inspection),
    )


def _execute_compute_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    executor = _compute_job_executor_for(job.analytics_type)
    request_payload = getattr(job, "request_payload", {})
    with _restored_async_observability_context(request_payload):
        return executor(job, context)


def _compute_job_executor_for(analytics_type: str) -> _ComputeJobExecutor:
    try:
        return _COMPUTE_JOB_EXECUTORS[analytics_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported compute job analytics_type: {analytics_type}") from exc


def _execute_returns_series_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    (
        request,
        source_input_mode,
        resolved_benchmark_id_override,
        resolved_benchmark_return_source_override,
        risk_free_source_quality_override,
        freshness_portfolio_df_override,
        freshness_benchmark_df_override,
        freshness_risk_free_df_override,
    ) = _resolve_async_returns_series_job_request(job.request_payload)
    if source_input_mode == request.input_mode:
        return asyncio.run(context.returns_series_calculator(request))
    return asyncio.run(
        context.returns_series_calculator(
            request,
            source_input_mode=source_input_mode,
            resolved_benchmark_id_override=resolved_benchmark_id_override,
            resolved_benchmark_return_source_override=resolved_benchmark_return_source_override,
            risk_free_source_quality_override=risk_free_source_quality_override,
            freshness_portfolio_df_override=freshness_portfolio_df_override,
            freshness_benchmark_df_override=freshness_benchmark_df_override,
            freshness_risk_free_df_override=freshness_risk_free_df_override,
        )
    )


def _nonblank_context_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


@contextmanager
def _restored_async_observability_context(payload: dict[str, Any]) -> Iterator[None]:
    context = payload.get(ASYNC_OBSERVABILITY_CONTEXT_FIELD)
    if not isinstance(context, dict):
        yield
        return

    tokens = []
    for field_name, context_var in (
        ("correlation_id", correlation_id_var),
        ("request_id", request_id_var),
        ("trace_id", trace_id_var),
    ):
        value = _nonblank_context_value(context.get(field_name))
        if value is not None:
            tokens.append((context_var, context_var.set(value)))
    try:
        yield
    finally:
        for context_var, token in reversed(tokens):
            context_var.reset(token)


def _payload_without_async_observability_context(payload: dict[str, Any]) -> dict[str, Any]:
    return {field: value for field, value in payload.items() if field != ASYNC_OBSERVABILITY_CONTEXT_FIELD}


def _update_execution_identity(
    job: ComputeJobRecord,
    context: _ComputeJobExecutionContext,
    request_artifact_model: Any,
) -> tuple[str, str]:
    input_fingerprint, calculation_hash = generate_canonical_hash(
        request_artifact_model,
        calculation_engine_version(context.settings),
    )
    context.execution_store.update_execution_identity(
        job.calculation_id,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    return input_fingerprint, calculation_hash


def _execute_attribution_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    (
        attribution_request,
        attribution_input_mode,
        resolved_benchmark_id,
        resolved_benchmark_return_source,
    ) = _resolve_async_attribution_job_request(
        job.request_payload,
        settings=context.settings,
    )
    input_fingerprint, calculation_hash = _update_execution_identity(job, context, attribution_request)
    return context.attribution_calculator(
        attribution_request,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        input_mode=attribution_input_mode,
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=resolved_benchmark_return_source,
    )


def _execute_contribution_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    contribution_request, contribution_input_mode = _resolve_async_contribution_job_request(
        job.request_payload,
        settings=context.settings,
    )
    input_fingerprint, calculation_hash = _update_execution_identity(job, context, contribution_request)
    return context.contribution_calculator(
        contribution_request,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        input_mode=contribution_input_mode,
    )


def _execute_benchmark_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    benchmark_request, benchmark_input_mode = _resolve_async_benchmark_job_request(
        job.request_payload,
        settings=context.settings,
    )
    input_fingerprint, calculation_hash = _update_execution_identity(job, context, benchmark_request)
    return context.benchmark_calculator(
        benchmark_request,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        input_mode=benchmark_input_mode,
        engine_version=calculation_engine_version(context.settings),
        request_artifact_model=benchmark_request,
    )


def _execute_twr_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    (
        twr_request,
        twr_input_mode,
        request_artifact_model,
        portfolio_id,
        resolved_benchmark_id,
        twr_benchmark_input_mode,
        benchmark_return_source,
        should_update_identity,
    ) = _resolve_async_twr_job_request(job.request_payload, settings=context.settings)
    if should_update_identity:
        input_fingerprint, calculation_hash = generate_canonical_hash_from_value(
            request_artifact_model,
            calculation_engine_version(context.settings),
        )
        context.execution_store.update_execution_identity(
            job.calculation_id,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
    else:
        input_fingerprint, calculation_hash = generate_canonical_hash(
            TWRAnalyticsRequest.model_validate(job.request_payload),
            calculation_engine_version(context.settings),
        )
    return context.twr_calculator(
        twr_request.portfolio,
        portfolio_id=portfolio_id,
        input_mode=twr_input_mode,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        engine_version=calculation_engine_version(context.settings),
        request_artifact_model=request_artifact_model,
        benchmark_request=twr_request.benchmark,
        benchmark_input_mode=twr_benchmark_input_mode,
        resolved_benchmark_id=resolved_benchmark_id,
        benchmark_return_source=benchmark_return_source,
    )


def _execute_workspace_summary_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    workspace_request = WorkspaceSummaryRequest.model_validate(
        _payload_without_async_observability_context(job.request_payload)
    )
    _update_execution_identity(job, context, workspace_request)
    response = context.workspace_summary_calculator(workspace_request, settings=context.settings)
    return response


def _execute_twr_inspection_job(job: ComputeJobRecord, context: _ComputeJobExecutionContext) -> Any:
    inspection_request = TWRInspectionRequest.model_validate(
        _payload_without_async_observability_context(job.request_payload)
    )
    _update_execution_identity(job, context, inspection_request)
    return context.inspection_calculator(inspection_request)


_COMPUTE_JOB_EXECUTORS: dict[str, _ComputeJobExecutor] = {
    ANALYTICS_WORKFLOW_RETURNS_SERIES: _execute_returns_series_job,
    ANALYTICS_WORKFLOW_ATTRIBUTION: _execute_attribution_job,
    ANALYTICS_WORKFLOW_CONTRIBUTION: _execute_contribution_job,
    ANALYTICS_WORKFLOW_BENCHMARK: _execute_benchmark_job,
    ANALYTICS_WORKFLOW_TWR: _execute_twr_job,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY: _execute_workspace_summary_job,
    ANALYTICS_WORKFLOW_TWR_INSPECTION: _execute_twr_inspection_job,
}


def _handle_compute_job_failure(
    job: ComputeJobRecord,
    exc: Exception,
    *,
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore],
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore],
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
) -> None:
    error_message = safe_unexpected_failure_message("Compute job execution")
    error_type = type(exc).__name__
    if _is_retryable_exception(exc):
        try:
            will_retry = job_store.mark_retryable_failure(
                job.calculation_id,
                error_message=error_message,
                error_type=error_type,
                worker_id=job.worker_id,
            )
        except ComputeJobLeaseOwnershipError as ownership_exc:
            _log_stale_compute_failure_finalization_skipped(job, exc, ownership_exc, retryable=True)
            return
        if will_retry:
            logger.warning(
                "Retrying compute job after retryable failure",
                extra=worker_log_extra(
                    worker_name=_WORKER_NAME,
                    queue=_QUEUE_NAME,
                    calculation_id=str(job.calculation_id),
                    analytics_type=job.analytics_type,
                    error_type=error_type,
                    failure_classification="retryable_compute_failure",
                    retryable=True,
                    attempt_count=getattr(job, "attempt_count", None),
                    max_attempts=getattr(job, "max_attempts", None),
                ),
            )
            return
        _record_terminal_failure(
            calculation_id=job.calculation_id,
            analytics_type=job.analytics_type,
            error_message=error_message,
            error_type=error_type,
            missing_execution_log_message="Execution record missing for compute job %s",
            result_store=result_store,
            execution_store=execution_store,
        )
        return
    try:
        job_store.mark_failed(
            job.calculation_id,
            error_message=error_message,
            error_type=error_type,
            worker_id=job.worker_id,
        )
    except ComputeJobLeaseOwnershipError as ownership_exc:
        _log_stale_compute_failure_finalization_skipped(job, exc, ownership_exc, retryable=False)
        return
    _record_terminal_failure(
        calculation_id=job.calculation_id,
        analytics_type=job.analytics_type,
        error_message=error_message,
        error_type=error_type,
        missing_execution_log_message="Execution record missing for compute job %s",
        result_store=result_store,
        execution_store=execution_store,
    )


def _handle_compute_success_result_publication_failure(
    job: ComputeJobRecord,
    exc: Exception,
    *,
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore],
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore],
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
) -> None:
    logger.exception(
        "Compute job success result publication failed after calculation completed.",
        extra=_compute_success_log_extra(job, exc, failure_classification="success_result_publication_failed"),
    )
    _handle_compute_job_failure(
        job,
        exc,
        job_store=job_store,
        result_store=result_store,
        execution_store=execution_store,
    )


def _log_compute_success_finalization_failure(job: ComputeJobRecord, exc: Exception) -> None:
    logger.exception(
        "Compute job success finalization failed after result publication.",
        extra=_compute_success_log_extra(job, exc, failure_classification="success_finalization_failed"),
    )


def _log_stale_compute_success_publication_skipped(job: ComputeJobRecord, exc: Exception) -> None:
    logger.warning(
        "Skipped compute job success publication because worker no longer owns the active lease.",
        extra=_compute_success_log_extra(
            job,
            exc,
            failure_classification="stale_owner_success_publication_skipped",
        ),
    )


def _log_stale_compute_failure_finalization_skipped(
    job: ComputeJobRecord,
    original_exc: Exception,
    ownership_exc: ComputeJobLeaseOwnershipError,
    *,
    retryable: bool,
) -> None:
    logger.warning(
        "Skipped compute job failure finalization because worker no longer owns the active lease.",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            queue=_QUEUE_NAME,
            calculation_id=str(job.calculation_id),
            analytics_type=job.analytics_type,
            error_type=type(original_exc).__name__,
            ownership_error_type=type(ownership_exc).__name__,
            failure_classification="stale_owner_failure_finalization_skipped",
            retryable=retryable,
            attempt_count=getattr(job, "attempt_count", None),
            max_attempts=getattr(job, "max_attempts", None),
        ),
    )


def _compute_success_log_extra(job: ComputeJobRecord, exc: Exception, *, failure_classification: str):
    return worker_log_extra(
        worker_name=_WORKER_NAME,
        queue=_QUEUE_NAME,
        calculation_id=str(job.calculation_id),
        analytics_type=job.analytics_type,
        error_type=type(exc).__name__,
        failure_classification=failure_classification,
        retryable=True,
        attempt_count=getattr(job, "attempt_count", None),
        max_attempts=getattr(job, "max_attempts", None),
    )


def _handle_reconciled_stale_job(
    reconciled_job: ReconciledJobRecord,
    *,
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore],
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore],
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
) -> None:
    if _recover_reconciled_job_from_success_result(
        reconciled_job,
        job_store=job_store,
        result_store=result_store,
    ):
        return
    if reconciled_job.reconciled_status.value == "failed":
        _record_terminal_failure(
            calculation_id=reconciled_job.calculation_id,
            analytics_type=reconciled_job.analytics_type,
            error_message=reconciled_job.error_message,
            error_type=reconciled_job.error_type,
            missing_execution_log_message="Execution record missing for reconciled compute job %s",
            result_store=result_store,
            execution_store=execution_store,
        )
        return
    logger.warning(
        "Requeued stale compute job after expired lease",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            queue=_QUEUE_NAME,
            calculation_id=str(reconciled_job.calculation_id),
            analytics_type=reconciled_job.analytics_type,
            previous_status=reconciled_job.previous_status.value,
            reconciled_status=reconciled_job.reconciled_status.value,
            failure_classification="stale_compute_lease_requeued",
            retryable=True,
            attempt_count=reconciled_job.attempt_count,
            max_attempts=reconciled_job.max_attempts,
            error_type=reconciled_job.error_type,
        ),
    )


def _recover_reconciled_job_from_success_result(
    reconciled_job: ReconciledJobRecord,
    *,
    job_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore],
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore],
) -> bool:
    result = result_store.get_result(reconciled_job.calculation_id)
    if (
        result is None
        or result.result_status != AsyncResultStatus.COMPLETE
        or result.analytics_type != reconciled_job.analytics_type
        or result.response_payload is None
    ):
        return False

    job_store.mark_complete(reconciled_job.calculation_id, response_payload=result.response_payload)
    logger.warning(
        "Recovered compute job completion from persisted success result.",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            queue=_QUEUE_NAME,
            calculation_id=str(reconciled_job.calculation_id),
            analytics_type=reconciled_job.analytics_type,
            previous_status=reconciled_job.previous_status.value,
            reconciled_status="complete",
            failure_classification="success_finalization_recovered",
            retryable=False,
            attempt_count=reconciled_job.attempt_count,
            max_attempts=reconciled_job.max_attempts,
            error_type=reconciled_job.error_type,
        ),
    )
    return True


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, APIError):
        if exc.retryable is not None:
            return exc.retryable
        return exc.status_code >= 500
    if isinstance(
        exc,
        (
            ValidationError,
            InvalidEngineInputError,
            EngineCalculationError,
            ValueError,
            KeyError,
            NotImplementedError,
        ),
    ):
        return False
    return True


def _resolve_async_contribution_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[ContributionRequest, ContributionInputMode]:
    payload = _payload_without_async_observability_context(payload)
    try:
        request = ContributionRequest.model_validate(payload)
    except ValidationError:
        analytics_request = ContributionAnalyticsRequest.model_validate(payload)
        resolved_contribution = asyncio.run(resolve_contribution_request(analytics_request, settings=settings))
        return resolved_contribution.contribution_request, resolved_contribution.input_mode
    return request, ContributionInputMode.STATEFUL


def _resolve_async_returns_series_job_request(
    payload: dict[str, Any],
) -> tuple[ReturnsSeriesRequest, InputMode, str | None, str | None, RiskFreeSourceQuality | None, Any, Any, Any]:
    request_payload = _payload_without_async_observability_context(payload)
    resolved_request_payload = request_payload.get("resolved_request")
    source_input_mode = request_payload.get("source_input_mode")
    resolved_benchmark_id = request_payload.get("resolved_benchmark_id")
    resolved_benchmark_return_source = request_payload.get("resolved_benchmark_return_source")
    risk_free_source_quality = request_payload.get("risk_free_source_quality")
    if isinstance(resolved_request_payload, dict) and isinstance(source_input_mode, str):
        return (
            ReturnsSeriesRequest.model_validate(resolved_request_payload),
            InputMode(source_input_mode),
            resolved_benchmark_id if isinstance(resolved_benchmark_id, str) else None,
            resolved_benchmark_return_source if isinstance(resolved_benchmark_return_source, str) else None,
            RiskFreeSourceQuality.model_validate(risk_free_source_quality)
            if isinstance(risk_free_source_quality, dict)
            else None,
            _returns_series_freshness_dataframe(request_payload, "freshness_portfolio_returns", "portfolio"),
            _returns_series_freshness_dataframe(request_payload, "freshness_benchmark_returns", "benchmark"),
            _returns_series_freshness_dataframe(request_payload, "freshness_risk_free_returns", "risk_free"),
        )
    request = ReturnsSeriesRequest.model_validate(request_payload)
    return request, request.input_mode, None, None, None, None, None, None


def _returns_series_freshness_dataframe(
    payload: dict[str, Any],
    field_name: str,
    series_type: str,
) -> Any:
    records = payload.get(field_name)
    if records is None:
        return None
    if not isinstance(records, list):
        return None
    points = [ReturnPoint.model_validate(record) for record in records]
    return to_dataframe(points, series_type=f"{series_type} freshness")


def _resolve_async_attribution_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[AttributionRequest, AttributionInputMode, str | None, str | None]:
    payload = _payload_without_async_observability_context(payload)
    resolved_job_request = _resolved_async_attribution_job_request_from_payload(payload)
    if resolved_job_request is not None:
        return resolved_job_request

    try:
        request = AttributionRequest.model_validate(payload)
    except ValidationError:
        analytics_request = AttributionAnalyticsRequest.model_validate(payload)
        resolved_attribution = asyncio.run(resolve_attribution_request(analytics_request, settings=settings))
        return (
            resolved_attribution.attribution_request,
            resolved_attribution.input_mode,
            resolved_attribution.resolved_benchmark_id,
            resolved_attribution.resolved_benchmark_return_source,
        )
    return request, AttributionInputMode.STATEFUL, None, None


def _resolved_async_attribution_job_request_from_payload(
    payload: dict[str, Any],
) -> tuple[AttributionRequest, AttributionInputMode, str | None, str | None] | None:
    resolved_request_payload = payload.get("resolved_request")
    source_input_mode = payload.get("source_input_mode")
    resolved_benchmark_id = payload.get("resolved_benchmark_id")
    resolved_benchmark_return_source = payload.get("resolved_benchmark_return_source")
    if isinstance(resolved_request_payload, dict) and isinstance(source_input_mode, str):
        return (
            AttributionRequest.model_validate(resolved_request_payload),
            AttributionInputMode(source_input_mode),
            resolved_benchmark_id if isinstance(resolved_benchmark_id, str) else None,
            resolved_benchmark_return_source if isinstance(resolved_benchmark_return_source, str) else None,
        )
    return None


def _resolve_async_benchmark_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[BenchmarkPerformanceRequest, BenchmarkInputMode]:
    payload = _payload_without_async_observability_context(payload)
    resolved_request_payload = payload.get("resolved_request")
    source_input_mode = payload.get("source_input_mode")
    if isinstance(resolved_request_payload, dict) and isinstance(source_input_mode, str):
        return BenchmarkPerformanceRequest.model_validate(resolved_request_payload), BenchmarkInputMode(
            source_input_mode
        )
    try:
        request = BenchmarkPerformanceRequest.model_validate(payload)
    except ValidationError:
        analytics_request = BenchmarkAnalyticsRequest.model_validate(payload)
        resolved_benchmark = asyncio.run(resolve_benchmark_request(analytics_request, settings=settings))
        return resolved_benchmark.benchmark_request, resolved_benchmark.input_mode
    return request, BenchmarkInputMode.STATEFUL


def _resolve_async_twr_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[
    TWRResolvedExecutionRequest,
    TWRInputMode,
    TWRResolvedExecutionRequest | TWRAnalyticsRequest,
    str,
    str | None,
    BenchmarkInputMode | None,
    str,
    bool,
]:
    payload = _payload_without_async_observability_context(payload)
    resolved_request_payload = payload.get("resolved_request")
    source_input_mode = payload.get("source_input_mode")
    if isinstance(resolved_request_payload, dict) and isinstance(source_input_mode, str):
        return _resolve_persisted_twr_job_request(
            payload,
            resolved_request_payload=resolved_request_payload,
            source_input_mode=source_input_mode,
        )
    return _resolve_raw_twr_job_request(payload, settings=settings)


def _resolve_persisted_twr_job_request(
    payload: dict[str, Any],
    *,
    resolved_request_payload: dict[str, Any],
    source_input_mode: str,
) -> tuple[
    TWRResolvedExecutionRequest,
    TWRInputMode,
    TWRResolvedExecutionRequest,
    str,
    str | None,
    BenchmarkInputMode | None,
    str,
    bool,
]:
    resolved_request = TWRResolvedExecutionRequest.model_validate(resolved_request_payload)
    benchmark_input_mode = payload.get("benchmark_input_mode")
    resolved_benchmark_id = payload.get("resolved_benchmark_id")
    return (
        resolved_request,
        TWRInputMode(source_input_mode),
        resolved_request,
        payload.get("portfolio_id", resolved_request.portfolio.portfolio_id),
        resolved_benchmark_id if isinstance(resolved_benchmark_id, str) else None,
        BenchmarkInputMode(benchmark_input_mode) if isinstance(benchmark_input_mode, str) else None,
        payload.get("benchmark_return_source", "calculated"),
        True,
    )


def _resolve_raw_twr_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[
    TWRResolvedExecutionRequest,
    TWRInputMode,
    TWRResolvedExecutionRequest | TWRAnalyticsRequest,
    str,
    str | None,
    BenchmarkInputMode | None,
    str,
    bool,
]:
    analytics_request = TWRAnalyticsRequest.model_validate(payload)
    resolved_request = asyncio.run(resolve_twr_request(analytics_request, settings=settings))
    resolved_identity_payload = TWRResolvedExecutionRequest(
        portfolio=resolved_request.performance_request,
        benchmark=resolved_request.benchmark_request,
    )
    should_update_identity = (
        resolved_request.input_mode == TWRInputMode.STATEFUL or resolved_request.benchmark_request is not None
    )
    request_artifact_model = resolved_identity_payload if should_update_identity else analytics_request
    return (
        resolved_identity_payload,
        resolved_request.input_mode,
        request_artifact_model,
        analytics_request.portfolio_id,
        resolved_request.resolved_benchmark_id,
        resolved_request.benchmark_input_mode,
        analytics_request.benchmark.return_source.value if analytics_request.benchmark is not None else "calculated",
        should_update_identity,
    )


def _record_terminal_failure(
    *,
    calculation_id: UUID,
    analytics_type: str,
    error_message: str,
    error_type: str,
    missing_execution_log_message: str,
    result_store: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore] | None = None,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] | None = None,
) -> None:
    active_result_store = result_store or async_result_store
    active_execution_store = execution_store or execution_registry
    active_result_store.record_failure(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        error_message=error_message,
        error_type=error_type,
    )
    try:
        active_execution_store.fail_in_progress_stages(calculation_id, error_message)
        active_execution_store.mark_failed(calculation_id, error_message)
    except KeyError:
        logger.exception(
            missing_execution_log_message,
            calculation_id,
            extra=worker_log_extra(
                worker_name=_WORKER_NAME,
                queue=_QUEUE_NAME,
                calculation_id=str(calculation_id),
                analytics_type=analytics_type,
                error_type=error_type,
                failure_classification="terminal_compute_failure",
                retryable=False,
            ),
        )


def run_forever(*, stop_event: Event | None = None, settings=None) -> None:
    active_settings = settings or get_settings()
    setup_worker_logging(active_settings.LOG_LEVEL)
    logger.info(
        "Starting compute executor poller",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            worker_id=active_settings.COMPUTE_EXECUTOR_WORKER_ID,
            queue=_QUEUE_NAME,
        ),
    )
    bootstrap_durable_metadata_stores(
        execution_store=execution_registry,
        compute_store=compute_job_store,
        async_result_store_=async_result_store,
    )
    while not _stop_requested(stop_event):
        processed = process_pending_jobs(settings=active_settings)
        if processed == 0 and _wait_for_next_poll(stop_event, active_settings.COMPUTE_EXECUTOR_POLL_SECONDS):
            break


def _stop_requested(stop_event: Event | None) -> bool:
    return False if stop_event is None else stop_event.is_set()


def _wait_for_next_poll(stop_event: Event | None, poll_seconds: float) -> bool:
    if stop_event is None:
        time.sleep(poll_seconds)
        return False
    return stop_event.wait(timeout=poll_seconds)


if __name__ == "__main__":
    run_forever()
