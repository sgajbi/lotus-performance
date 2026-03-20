from __future__ import annotations

import asyncio
import logging
import time
from threading import Event
from typing import Any, Callable, Coroutine
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest, ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.returns_series import InputMode, ReturnsSeriesRequest
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode, TWRResolvedExecutionRequest
from app.services.async_result_store import AsyncResultStore, async_result_store
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.attribution_service import calculate_attribution
from app.services.benchmark_mode_service import resolve_benchmark_request
from app.services.benchmark_service import calculate_benchmark_response
from app.services.compute_job_store import ComputeJobStore, compute_job_store
from app.services.contribution_mode_service import resolve_contribution_request
from app.services.contribution_service import calculate_contribution
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.returns_series_service import calculate_returns_series
from app.services.twr_mode_service import resolve_twr_request
from app.services.twr_service import calculate_twr_response
from core.repro import generate_canonical_hash, generate_canonical_hash_from_value
from engine.exceptions import EngineCalculationError, InvalidEngineInputError

logger = logging.getLogger(__name__)


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
    settings=None,
) -> int:
    active_settings = settings or get_settings()
    batch_size = limit or active_settings.COMPUTE_EXECUTOR_BATCH_SIZE
    active_job_store = job_store or compute_job_store
    active_execution_store = execution_store or execution_registry
    active_result_store = result_store or async_result_store
    current_worker_id = worker_id or active_settings.COMPUTE_EXECUTOR_WORKER_ID
    current_lease_seconds = lease_seconds or active_settings.COMPUTE_EXECUTOR_LEASE_SECONDS
    active_returns_series_calculator = returns_series_calculator or calculate_returns_series
    active_contribution_calculator = contribution_calculator or calculate_contribution
    active_attribution_calculator = attribution_calculator or calculate_attribution
    active_benchmark_calculator = benchmark_calculator or calculate_benchmark_response
    active_twr_calculator = twr_calculator or calculate_twr_response
    reconciled = active_job_store.reconcile_stale_jobs()
    for reconciled_job in reconciled:
        if reconciled_job.reconciled_status.value == "failed":
            _record_terminal_failure(
                calculation_id=reconciled_job.calculation_id,
                analytics_type=reconciled_job.analytics_type,
                error_message=reconciled_job.error_message,
                error_type=reconciled_job.error_type,
                missing_execution_log_message="Execution record missing for reconciled compute job %s",
                result_store=active_result_store,
                execution_store=active_execution_store,
            )
        else:
            logger.warning(
                "Requeued stale compute job %s after expired %s lease",
                reconciled_job.calculation_id,
                reconciled_job.previous_status.value,
            )
    pending = active_job_store.lease_pending_jobs(
        worker_id=current_worker_id,
        limit=batch_size,
        lease_seconds=current_lease_seconds,
    )
    processed = 0
    for job in pending:
        active_job_store.mark_running(
            job.calculation_id,
            worker_id=current_worker_id,
            lease_seconds=current_lease_seconds,
        )
        try:
            if job.analytics_type == "ReturnsSeries":
                (
                    request,
                    source_input_mode,
                    resolved_benchmark_id_override,
                    resolved_benchmark_return_source_override,
                ) = _resolve_async_returns_series_job_request(job.request_payload)
                if source_input_mode == request.input_mode:
                    response = asyncio.run(active_returns_series_calculator(request))
                else:
                    response = asyncio.run(
                        active_returns_series_calculator(
                            request,
                            source_input_mode=source_input_mode,
                            resolved_benchmark_id_override=resolved_benchmark_id_override,
                            resolved_benchmark_return_source_override=resolved_benchmark_return_source_override,
                        )
                    )
            elif job.analytics_type == "Attribution":
                (
                    attribution_request,
                    attribution_input_mode,
                    resolved_benchmark_id,
                    resolved_benchmark_return_source,
                ) = _resolve_async_attribution_job_request(
                    job.request_payload,
                    settings=active_settings,
                )
                input_fingerprint, calculation_hash = generate_canonical_hash(
                    attribution_request,
                    active_settings.APP_VERSION,
                )
                active_execution_store.update_execution_identity(
                    job.calculation_id,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                )
                response = active_attribution_calculator(
                    attribution_request,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                    input_mode=attribution_input_mode,
                    resolved_benchmark_id=resolved_benchmark_id,
                    resolved_benchmark_return_source=resolved_benchmark_return_source,
                )
            elif job.analytics_type == "Contribution":
                contribution_request, contribution_input_mode = _resolve_async_contribution_job_request(
                    job.request_payload,
                    settings=active_settings,
                )
                input_fingerprint, calculation_hash = generate_canonical_hash(
                    contribution_request,
                    active_settings.APP_VERSION,
                )
                active_execution_store.update_execution_identity(
                    job.calculation_id,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                )
                response = active_contribution_calculator(
                    contribution_request,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                    input_mode=contribution_input_mode,
                )
            elif job.analytics_type == "BENCHMARK":
                benchmark_request, benchmark_input_mode = _resolve_async_benchmark_job_request(
                    job.request_payload,
                    settings=active_settings,
                )
                input_fingerprint, calculation_hash = generate_canonical_hash(
                    benchmark_request,
                    active_settings.APP_VERSION,
                )
                active_execution_store.update_execution_identity(
                    job.calculation_id,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                )
                response = active_benchmark_calculator(
                    benchmark_request,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                    input_mode=benchmark_input_mode,
                    engine_version=active_settings.APP_VERSION,
                    request_artifact_model=benchmark_request,
                )
            elif job.analytics_type == "TWR":
                (
                    twr_request,
                    twr_input_mode,
                    request_artifact_model,
                    portfolio_id,
                    resolved_benchmark_id,
                    benchmark_input_mode,
                    benchmark_return_source,
                    should_update_identity,
                ) = _resolve_async_twr_job_request(job.request_payload, settings=active_settings)
                if should_update_identity:
                    input_fingerprint, calculation_hash = generate_canonical_hash_from_value(
                        request_artifact_model,
                        active_settings.APP_VERSION,
                    )
                    active_execution_store.update_execution_identity(
                        job.calculation_id,
                        input_fingerprint=input_fingerprint,
                        calculation_hash=calculation_hash,
                    )
                else:
                    input_fingerprint, calculation_hash = generate_canonical_hash(
                        TWRAnalyticsRequest.model_validate(job.request_payload),
                        active_settings.APP_VERSION,
                    )
                response = active_twr_calculator(
                    twr_request.portfolio,
                    portfolio_id=portfolio_id,
                    input_mode=twr_input_mode,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                    engine_version=active_settings.APP_VERSION,
                    request_artifact_model=request_artifact_model,
                    benchmark_request=twr_request.benchmark,
                    benchmark_input_mode=benchmark_input_mode,
                    resolved_benchmark_id=resolved_benchmark_id,
                    benchmark_return_source=benchmark_return_source,
                )
            else:
                raise ValueError(f"Unsupported compute job analytics_type: {job.analytics_type}")
            active_result_store.record_success(
                calculation_id=job.calculation_id,
                analytics_type=job.analytics_type,
                response_payload=response.model_dump(mode="json"),
            )
            active_job_store.mark_complete(job.calculation_id, response_payload=response.model_dump(mode="json"))
        except Exception as exc:
            if _is_retryable_exception(exc):
                will_retry = active_job_store.mark_retryable_failure(
                    job.calculation_id,
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                )
                if will_retry:
                    logger.warning("Retrying compute job %s after %s", job.calculation_id, type(exc).__name__)
                else:
                    _record_terminal_failure(
                        calculation_id=job.calculation_id,
                        analytics_type=job.analytics_type,
                        error_message=str(exc),
                        error_type=type(exc).__name__,
                        missing_execution_log_message="Execution record missing for compute job %s",
                        result_store=active_result_store,
                        execution_store=active_execution_store,
                    )
            else:
                active_job_store.mark_failed(
                    job.calculation_id,
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                )
                _record_terminal_failure(
                    calculation_id=job.calculation_id,
                    analytics_type=job.analytics_type,
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                    missing_execution_log_message="Execution record missing for compute job %s",
                    result_store=active_result_store,
                    execution_store=active_execution_store,
                )
        processed += 1
    return processed


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(
        exc, (ValidationError, InvalidEngineInputError, EngineCalculationError, ValueError, NotImplementedError)
    ):
        return False
    if isinstance(exc, HTTPException):
        return exc.status_code >= 500
    return True


def _resolve_async_contribution_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[ContributionRequest, ContributionInputMode]:
    try:
        request = ContributionRequest.model_validate(payload)
    except ValidationError:
        analytics_request = ContributionAnalyticsRequest.model_validate(payload)
        resolved_contribution = asyncio.run(resolve_contribution_request(analytics_request, settings=settings))
        return resolved_contribution.contribution_request, resolved_contribution.input_mode
    return request, ContributionInputMode.STATEFUL


def _resolve_async_returns_series_job_request(
    payload: dict[str, Any],
) -> tuple[ReturnsSeriesRequest, InputMode, str | None, str | None]:
    resolved_request_payload = payload.get("resolved_request")
    source_input_mode = payload.get("source_input_mode")
    resolved_benchmark_id = payload.get("resolved_benchmark_id")
    resolved_benchmark_return_source = payload.get("resolved_benchmark_return_source")
    if isinstance(resolved_request_payload, dict) and isinstance(source_input_mode, str):
        return (
            ReturnsSeriesRequest.model_validate(resolved_request_payload),
            InputMode(source_input_mode),
            resolved_benchmark_id if isinstance(resolved_benchmark_id, str) else None,
            resolved_benchmark_return_source if isinstance(resolved_benchmark_return_source, str) else None,
        )
    request = ReturnsSeriesRequest.model_validate(payload)
    return request, request.input_mode, None, None


def _resolve_async_attribution_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[AttributionRequest, AttributionInputMode, str | None, str | None]:
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


def _resolve_async_benchmark_job_request(
    payload: dict[str, Any],
    *,
    settings,
) -> tuple[BenchmarkPerformanceRequest, BenchmarkInputMode]:
    resolved_request_payload = payload.get("resolved_request")
    source_input_mode = payload.get("source_input_mode")
    if isinstance(resolved_request_payload, dict) and isinstance(source_input_mode, str):
        return BenchmarkPerformanceRequest.model_validate(resolved_request_payload), BenchmarkInputMode(source_input_mode)
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
    resolved_request_payload = payload.get("resolved_request")
    source_input_mode = payload.get("source_input_mode")
    benchmark_input_mode = payload.get("benchmark_input_mode")
    resolved_benchmark_id = payload.get("resolved_benchmark_id")
    benchmark_return_source = payload.get("benchmark_return_source", "calculated")
    if isinstance(resolved_request_payload, dict) and isinstance(source_input_mode, str):
        resolved_request = TWRResolvedExecutionRequest.model_validate(resolved_request_payload)
        return (
            resolved_request,
            TWRInputMode(source_input_mode),
            resolved_request,
            payload.get("portfolio_id", resolved_request.portfolio.portfolio_id),
            resolved_benchmark_id if isinstance(resolved_benchmark_id, str) else None,
            BenchmarkInputMode(benchmark_input_mode) if isinstance(benchmark_input_mode, str) else None,
            benchmark_return_source,
            True,
        )

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
        logger.exception(missing_execution_log_message, calculation_id)


def run_forever(*, stop_event: Event | None = None, settings=None) -> None:
    active_settings = settings or get_settings()
    logging.basicConfig(level=getattr(logging, active_settings.LOG_LEVEL.upper(), logging.INFO))
    logger.info("Starting compute executor poller")
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
