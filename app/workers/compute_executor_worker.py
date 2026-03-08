from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import get_settings
from app.models.attribution_requests import AttributionRequest
from app.models.contribution_requests import ContributionRequest
from app.models.returns_series import ReturnsSeriesRequest
from app.services.async_result_store import async_result_store
from app.services.attribution_service import calculate_attribution
from app.services.compute_job_store import compute_job_store
from app.services.contribution_service import calculate_contribution
from app.services.execution_registry import execution_registry
from app.services.returns_series_service import calculate_returns_series
from core.repro import generate_canonical_hash
from engine.exceptions import EngineCalculationError, InvalidEngineInputError

logger = logging.getLogger(__name__)
settings = get_settings()


def process_pending_jobs(*, limit: int | None = None) -> int:
    batch_size = limit or settings.COMPUTE_EXECUTOR_BATCH_SIZE
    reconciled = compute_job_store.reconcile_stale_jobs()
    for reconciled_job in reconciled:
        if reconciled_job.reconciled_status.value == "failed":
            async_result_store.record_failure(
                calculation_id=reconciled_job.calculation_id,
                analytics_type=reconciled_job.analytics_type,
                error_message=reconciled_job.error_message,
                error_type=reconciled_job.error_type,
            )
            try:
                execution_registry.fail_in_progress_stages(reconciled_job.calculation_id, reconciled_job.error_message)
                execution_registry.mark_failed(reconciled_job.calculation_id, reconciled_job.error_message)
            except KeyError:
                logger.exception(
                    "Execution record missing for reconciled compute job %s", reconciled_job.calculation_id
                )
        else:
            logger.warning(
                "Requeued stale compute job %s after expired %s lease",
                reconciled_job.calculation_id,
                reconciled_job.previous_status.value,
            )
    pending = compute_job_store.lease_pending_jobs(
        worker_id=settings.COMPUTE_EXECUTOR_WORKER_ID,
        limit=batch_size,
        lease_seconds=settings.COMPUTE_EXECUTOR_LEASE_SECONDS,
    )
    processed = 0
    for job in pending:
        compute_job_store.mark_running(
            job.calculation_id,
            worker_id=settings.COMPUTE_EXECUTOR_WORKER_ID,
            lease_seconds=settings.COMPUTE_EXECUTOR_LEASE_SECONDS,
        )
        try:
            if job.analytics_type == "ReturnsSeries":
                request = ReturnsSeriesRequest.model_validate(job.request_payload)
                response = asyncio.run(calculate_returns_series(request))
            elif job.analytics_type == "Attribution":
                request = AttributionRequest.model_validate(job.request_payload)
                input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)
                response = calculate_attribution(
                    request,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                )
            elif job.analytics_type == "Contribution":
                request = ContributionRequest.model_validate(job.request_payload)
                input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)
                response = calculate_contribution(
                    request,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                )
            else:
                raise ValueError(f"Unsupported compute job analytics_type: {job.analytics_type}")
            async_result_store.record_success(
                calculation_id=job.calculation_id,
                analytics_type=job.analytics_type,
                response_payload=response.model_dump(mode="json"),
            )
            compute_job_store.mark_complete(job.calculation_id, response_payload=response.model_dump(mode="json"))
        except Exception as exc:
            if _is_retryable_exception(exc):
                will_retry = compute_job_store.mark_retryable_failure(
                    job.calculation_id,
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                )
                if will_retry:
                    logger.warning("Retrying compute job %s after %s", job.calculation_id, type(exc).__name__)
                else:
                    async_result_store.record_failure(
                        calculation_id=job.calculation_id,
                        analytics_type=job.analytics_type,
                        error_message=str(exc),
                        error_type=type(exc).__name__,
                    )
                    try:
                        execution_registry.fail_in_progress_stages(job.calculation_id, str(exc))
                        execution_registry.mark_failed(job.calculation_id, str(exc))
                    except KeyError:
                        logger.exception("Execution record missing for compute job %s", job.calculation_id)
            else:
                async_result_store.record_failure(
                    calculation_id=job.calculation_id,
                    analytics_type=job.analytics_type,
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                )
                compute_job_store.mark_failed(
                    job.calculation_id,
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                )
                try:
                    execution_registry.fail_in_progress_stages(job.calculation_id, str(exc))
                    execution_registry.mark_failed(job.calculation_id, str(exc))
                except KeyError:
                    logger.exception("Execution record missing for compute job %s", job.calculation_id)
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


def run_forever() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    logger.info("Starting compute executor poller")
    execution_registry.create_schema()
    compute_job_store.create_schema()
    async_result_store.create_schema()
    while True:
        processed = process_pending_jobs()
        if processed == 0:
            time.sleep(settings.COMPUTE_EXECUTOR_POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
