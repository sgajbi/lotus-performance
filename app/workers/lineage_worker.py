from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Event
from uuid import UUID

from app.core.config import get_settings
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.lineage_metadata_store import LineageMetadataStore, LineagePayload, lineage_metadata_store
from app.services.lineage_service import LineageService, lineage_service, resolve_artifact_stage_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _LineageWorkerRuntime:
    batch_size: int
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore]
    lineage_service: LineageService
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry]
    worker_id: str
    lease_seconds: int
    max_attempts: int


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
    runtime = _lineage_worker_runtime(
        limit=limit,
        lineage_store=lineage_store,
        lineage_service_=lineage_service_,
        execution_store=execution_store,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        max_attempts=max_attempts,
        settings=settings,
    )
    pending = runtime.lineage_store.lease_pending_payloads(
        worker_id=runtime.worker_id,
        limit=runtime.batch_size,
        lease_seconds=runtime.lease_seconds,
    )
    processed = 0
    for payload in pending:
        if _materialize_leased_payload(
            payload=payload,
            lineage_store=runtime.lineage_store,
            lineage_service_=runtime.lineage_service,
            execution_store=runtime.execution_store,
            max_attempts=runtime.max_attempts,
        ):
            processed += 1
    return processed


def _lineage_worker_runtime(
    *,
    limit: int | None,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore] | None,
    lineage_service_: LineageService | None,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] | None,
    worker_id: str | None,
    lease_seconds: int | None,
    max_attempts: int | None,
    settings,
) -> _LineageWorkerRuntime:
    active_settings = settings or get_settings()
    return _LineageWorkerRuntime(
        batch_size=limit or active_settings.LINEAGE_WORKER_BATCH_SIZE,
        lineage_store=lineage_store or lineage_metadata_store,
        lineage_service=lineage_service_ or lineage_service,
        execution_store=execution_store or execution_registry,
        worker_id=worker_id or active_settings.LINEAGE_WORKER_ID,
        lease_seconds=lease_seconds or active_settings.LINEAGE_WORKER_LEASE_SECONDS,
        max_attempts=max_attempts or active_settings.LINEAGE_WORKER_MAX_ATTEMPTS,
    )


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


def _materialize_leased_payload(
    *,
    payload: LineagePayload,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore],
    lineage_service_: LineageService,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
    max_attempts: int,
) -> bool:
    success = lineage_service_.materialize_payload(
        calculation_id=payload.calculation_id,
        calculation_type=payload.calculation_type,
        request_json=payload.request_json,
        response_json=payload.response_json,
        calculation_details=payload.details,
    )
    if success:
        lineage_store.delete_payload(payload.calculation_id)
        return True

    _handle_lineage_materialization_retry(
        payload=payload,
        lineage_store=lineage_store,
        execution_store=execution_store,
        max_attempts=max_attempts,
    )
    return False


def _handle_lineage_materialization_retry(
    *,
    payload: LineagePayload,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore],
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
    max_attempts: int,
) -> None:
    current_payload = lineage_store.get_payload(payload.calculation_id)
    if current_payload is None:
        return
    if current_payload.attempt_count >= max_attempts:
        _mark_lineage_materialization_failed(
            calculation_id=payload.calculation_id,
            calculation_type=payload.calculation_type,
            lineage_store=lineage_store,
            execution_store=execution_store,
            error_message="Lineage materialization failed after exhausting retry budget.",
        )
    else:
        lineage_store.mark_pending(payload.calculation_id)


def _mark_lineage_materialization_failed(
    *,
    calculation_id: UUID,
    calculation_type: str,
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
            resolve_artifact_stage_name(calculation_type=calculation_type),
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
