from __future__ import annotations

import asyncio
import logging
import time

from app.core.config import get_settings
from app.models.contribution_requests import ContributionRequest
from app.models.returns_series import ReturnsSeriesRequest
from app.services.compute_job_store import compute_job_store
from app.services.contribution_service import calculate_contribution
from app.services.execution_registry import execution_registry
from app.services.returns_series_service import calculate_returns_series
from core.repro import generate_canonical_hash

logger = logging.getLogger(__name__)
settings = get_settings()


def process_pending_jobs(*, limit: int | None = None) -> int:
    batch_size = limit or settings.COMPUTE_EXECUTOR_BATCH_SIZE
    pending = compute_job_store.list_pending_jobs(limit=batch_size)
    processed = 0
    for job in pending:
        compute_job_store.mark_running(job.calculation_id)
        try:
            if job.analytics_type == "ReturnsSeries":
                request = ReturnsSeriesRequest.model_validate(job.request_payload)
                response = asyncio.run(calculate_returns_series(request))
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
            compute_job_store.mark_complete(job.calculation_id, response_payload=response.model_dump(mode="json"))
        except Exception as exc:
            compute_job_store.mark_failed(job.calculation_id, error_message=str(exc))
            try:
                execution_registry.mark_failed(job.calculation_id, str(exc))
            except KeyError:
                logger.exception("Execution record missing for compute job %s", job.calculation_id)
        processed += 1
    return processed


def run_forever() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    logger.info("Starting compute executor poller")
    execution_registry.create_schema()
    compute_job_store.create_schema()
    while True:
        processed = process_pending_jobs()
        if processed == 0:
            time.sleep(settings.COMPUTE_EXECUTOR_POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
