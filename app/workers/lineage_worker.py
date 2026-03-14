from __future__ import annotations

import logging
import time
from threading import Event
from uuid import UUID

from app.core.config import get_settings
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.lineage_metadata_store import LineageMetadataStore, lineage_metadata_store
from app.services.lineage_service import LineageService, lineage_service

logger = logging.getLogger(__name__)


def process_pending_jobs(
    *,
    limit: int | None = None,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore] | None = None,
    lineage_service_: LineageService | None = None,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] | None = None,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
    max_attempts: int | None = None,
    settings=None,
) -> int:
    active_settings = settings or get_settings()
    batch_size = limit or active_settings.LINEAGE_WORKER_BATCH_SIZE
    active_lineage_store = lineage_store or lineage_metadata_store
    active_lineage_service = lineage_service_ or lineage_service
    active_execution_store = execution_store or execution_registry
    current_worker_id = worker_id or active_settings.LINEAGE_WORKER_ID
    current_lease_seconds = lease_seconds or active_settings.LINEAGE_WORKER_LEASE_SECONDS
    current_max_attempts = max_attempts or active_settings.LINEAGE_WORKER_MAX_ATTEMPTS
    pending = active_lineage_store.lease_pending_payloads(
        worker_id=current_worker_id,
        limit=batch_size,
        lease_seconds=current_lease_seconds,
    )
    processed = 0
    for payload in pending:
        success = active_lineage_service.materialize_payload(
            calculation_id=payload.calculation_id,
            calculation_type=payload.calculation_type,
            request_json=payload.request_json,
            response_json=payload.response_json,
            calculation_details=payload.details,
        )
        if success:
            processed += 1
            continue

        current_payload = active_lineage_store.get_payload(payload.calculation_id)
        if current_payload is None:
            continue
        if current_payload.attempt_count >= current_max_attempts:
            _mark_lineage_materialization_failed(
                calculation_id=payload.calculation_id,
                lineage_store=active_lineage_store,
                execution_store=active_execution_store,
                error_message="Lineage materialization failed after exhausting retry budget.",
            )
        else:
            active_lineage_store.mark_pending(payload.calculation_id)
    return processed


def run_forever(*, stop_event: Event | None = None, settings=None) -> None:
    active_settings = settings or get_settings()
    logging.basicConfig(level=getattr(logging, active_settings.LOG_LEVEL.upper(), logging.INFO))
    logger.info("Starting lineage worker poller")
    bootstrap_durable_metadata_stores(
        execution_store=execution_registry,
        lineage_store=lineage_metadata_store,
    )
    while not _stop_requested(stop_event):
        processed = process_pending_jobs(settings=active_settings)
        if processed == 0 and _wait_for_next_poll(stop_event, active_settings.LINEAGE_WORKER_POLL_SECONDS):
            break


def _stop_requested(stop_event: Event | None) -> bool:
    return False if stop_event is None else stop_event.is_set()


def _wait_for_next_poll(stop_event: Event | None, poll_seconds: float) -> bool:
    if stop_event is None:
        time.sleep(poll_seconds)
        return False
    return stop_event.wait(timeout=poll_seconds)


def _mark_lineage_materialization_failed(
    *,
    calculation_id: UUID,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore],
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
    error_message: str,
) -> None:
    lineage_store.mark_failed(
        calculation_id=calculation_id,
        error_message=error_message,
    )
    try:
        execution_store.fail_stage(
            calculation_id,
            "lineage_materialization",
            error_message,
        )
    except Exception:
        logger.warning(
            "Execution stage unavailable while marking lineage materialization failed: %s",
            calculation_id,
            exc_info=True,
        )


if __name__ == "__main__":
    run_forever()
