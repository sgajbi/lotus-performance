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
from app.models.attribution_requests import AttributionRequest
from app.models.contribution_requests import ContributionRequest
from app.models.returns_series import ReturnsSeriesRequest
from app.services.async_result_store import AsyncResultStore, async_result_store
from app.services.attribution_service import calculate_attribution
from app.services.compute_job_store import ComputeJobStore, compute_job_store
from app.services.contribution_service import calculate_contribution
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.returns_series_service import calculate_returns_series
from core.repro import generate_canonical_hash
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
    returns_series_calculator: Callable[[ReturnsSeriesRequest], Coroutine[Any, Any, Any]] | None = None,
    contribution_calculator: Callable[..., Any] | None = None,
    attribution_calculator: Callable[..., Any] | None = None,
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
                request = ReturnsSeriesRequest.model_validate(job.request_payload)
                response = asyncio.run(active_returns_series_calculator(request))
            elif job.analytics_type == "Attribution":
                request = AttributionRequest.model_validate(job.request_payload)
                input_fingerprint, calculation_hash = generate_canonical_hash(request, active_settings.APP_VERSION)
                response = active_attribution_calculator(
                    request,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                )
            elif job.analytics_type == "Contribution":
                request = ContributionRequest.model_validate(job.request_payload)
                input_fingerprint, calculation_hash = generate_canonical_hash(request, active_settings.APP_VERSION)
                response = active_contribution_calculator(
                    request,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
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
