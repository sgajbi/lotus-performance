from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Event
from typing import TypeVar, cast
from uuid import UUID

from app.core.config import get_settings
from app.observability import setup_worker_logging, worker_log_extra
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.lineage_metadata_store import (
    LineageMetadataStore,
    LineagePayload,
    LineagePayloadLeaseOwnershipError,
    LineageStatus,
    lineage_metadata_store,
)
from app.services.lineage_service import LineageService, lineage_service, resolve_artifact_stage_name

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
_WORKER_NAME = "lineage_worker"
_QUEUE_NAME = "lineage"


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


def process_pending_calculation(
    calculation_id: UUID,
    *,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore] | None = None,
    lineage_service_: LineageService | None = None,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] | None = None,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
    max_attempts: int | None = None,
    wait_seconds: float | None = None,
    poll_seconds: float | None = None,
    settings=None,
) -> bool:
    """Materialize lineage for one calculation and return whether it is complete.

    This targeted path supports workflows that must not publish a ready async result
    before the same calculation's lineage is terminally materialized.
    """
    runtime = _lineage_worker_runtime(
        limit=1,
        lineage_store=lineage_store,
        lineage_service_=lineage_service_,
        execution_store=execution_store,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        max_attempts=max_attempts,
        settings=settings,
    )
    active_settings = settings or get_settings()
    wait_budget_seconds = wait_seconds if wait_seconds is not None else float(runtime.lease_seconds)
    poll_interval_seconds = (
        poll_seconds if poll_seconds is not None else float(active_settings.LINEAGE_WORKER_POLL_SECONDS)
    )
    return _process_pending_calculation_with_runtime(
        calculation_id=calculation_id,
        runtime=runtime,
        wait_budget_seconds=wait_budget_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


def _process_pending_calculation_with_runtime(
    *,
    calculation_id: UUID,
    runtime: _LineageWorkerRuntime,
    wait_budget_seconds: float,
    poll_interval_seconds: float,
) -> bool:
    deadline = time.monotonic() + max(wait_budget_seconds, 0.0)
    materialization_attempts = 0
    while materialization_attempts < runtime.max_attempts:
        payload = runtime.lineage_store.lease_pending_payload(
            calculation_id=calculation_id,
            worker_id=runtime.worker_id,
            lease_seconds=runtime.lease_seconds,
        )
        if payload is None:
            pending_wait_result = _wait_for_pending_lineage_terminality(
                lineage_store=runtime.lineage_store,
                execution_store=runtime.execution_store,
                calculation_id=calculation_id,
                deadline=deadline,
                poll_interval_seconds=poll_interval_seconds,
            )
            if pending_wait_result is not None:
                return pending_wait_result
            continue
        materialization_attempts += 1
        if _materialize_leased_payload(
            payload=payload,
            lineage_store=runtime.lineage_store,
            lineage_service_=runtime.lineage_service,
            execution_store=runtime.execution_store,
            max_attempts=runtime.max_attempts,
            require_terminal_stage=True,
        ):
            return True
        record = runtime.lineage_store.get_record(calculation_id)
        if record is None or record.status != LineageStatus.PENDING:
            return False
    return (
        _lineage_terminal_status(
            lineage_store=runtime.lineage_store,
            execution_store=runtime.execution_store,
            calculation_id=calculation_id,
        )
        is True
    )


def _wait_for_pending_lineage_terminality(
    *,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore],
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
    calculation_id: UUID,
    deadline: float,
    poll_interval_seconds: float,
) -> bool | None:
    terminal_status = _lineage_terminal_status(
        lineage_store=lineage_store,
        execution_store=execution_store,
        calculation_id=calculation_id,
    )
    if terminal_status is not None:
        return terminal_status
    if time.monotonic() >= deadline:
        return False
    _sleep_until_next_lineage_poll(deadline=deadline, poll_interval_seconds=poll_interval_seconds)
    return None


def _sleep_until_next_lineage_poll(*, deadline: float, poll_interval_seconds: float) -> None:
    time.sleep(max(0.0, min(poll_interval_seconds, deadline - time.monotonic())))


def _lineage_terminal_status(
    *,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore],
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
    calculation_id: UUID,
) -> bool | None:
    record = lineage_store.get_record(calculation_id)
    if record is None:
        return False
    if record.status == LineageStatus.FAILED:
        return False
    if record.status == LineageStatus.PENDING:
        return None
    stage_name = resolve_artifact_stage_name(calculation_type=record.calculation_type)
    return execution_store.stage_is_complete(calculation_id, stage_name)


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
        batch_size=_explicit_or_default(limit, active_settings.LINEAGE_WORKER_BATCH_SIZE),
        lineage_store=cast(
            LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore],
            _explicit_or_default(lineage_store, lineage_metadata_store),
        ),
        lineage_service=_explicit_or_default(lineage_service_, lineage_service),
        execution_store=cast(
            ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry],
            _explicit_or_default(execution_store, execution_registry),
        ),
        worker_id=_explicit_or_default(worker_id, active_settings.LINEAGE_WORKER_ID),
        lease_seconds=_explicit_or_default(lease_seconds, active_settings.LINEAGE_WORKER_LEASE_SECONDS),
        max_attempts=_explicit_or_default(max_attempts, active_settings.LINEAGE_WORKER_MAX_ATTEMPTS),
    )


def _explicit_or_default(explicit: _T | None, default: _T) -> _T:
    return explicit or default


def run_forever(*, stop_event: Event | None = None, settings=None) -> None:
    active_settings = settings or get_settings()
    setup_worker_logging(active_settings.LOG_LEVEL)
    logger.info(
        "Starting lineage worker poller",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            worker_id=active_settings.LINEAGE_WORKER_ID,
            queue=_QUEUE_NAME,
        ),
    )
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
    require_terminal_stage: bool = False,
) -> bool:
    try:
        success = lineage_service_.materialize_payload(
            calculation_id=payload.calculation_id,
            calculation_type=payload.calculation_type,
            request_json=payload.request_json,
            response_json=payload.response_json,
            calculation_details=payload.details,
            worker_id=payload.worker_id,
        )
    except LineagePayloadLeaseOwnershipError as exc:
        _log_stale_lineage_payload_finalization_skipped(payload, exc)
        return False
    if success:
        if require_terminal_stage and (
            _lineage_terminal_status(
                lineage_store=lineage_store,
                execution_store=execution_store,
                calculation_id=payload.calculation_id,
            )
            is not True
        ):
            return False
        try:
            lineage_store.delete_payload(payload.calculation_id, worker_id=payload.worker_id)
        except LineagePayloadLeaseOwnershipError as exc:
            _log_stale_lineage_payload_finalization_skipped(payload, exc)
            return False
        return True

    _handle_lineage_materialization_retry(
        payload=payload,
        lineage_store=lineage_store,
        execution_store=execution_store,
        max_attempts=max_attempts,
    )
    return False


def _log_stale_lineage_payload_finalization_skipped(payload: LineagePayload, exc: Exception) -> None:
    logger.warning(
        "Skipped lineage payload finalization because worker no longer owns the active lease.",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            queue=_QUEUE_NAME,
            calculation_id=str(payload.calculation_id),
            calculation_type=payload.calculation_type,
            error_type=type(exc).__name__,
            failure_classification="stale_owner_lineage_finalization_skipped",
            retryable=True,
            attempt_count=payload.attempt_count,
        ),
    )


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
    lineage_stage = resolve_artifact_stage_name(calculation_type=calculation_type)
    lineage_store.mark_failed(
        calculation_id=calculation_id,
        error_message=error_message,
    )
    logger.warning(
        "Lineage materialization failed after retry budget",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            queue=_QUEUE_NAME,
            calculation_id=str(calculation_id),
            calculation_type=calculation_type,
            lineage_stage=lineage_stage,
            failure_classification="terminal_lineage_materialization_failure",
            retryable=False,
        ),
    )
    try:
        execution_store.fail_stage_and_execution(
            calculation_id,
            lineage_stage,
            error_message,
        )
    except Exception:
        logger.warning(
            "Execution stage unavailable while marking lineage materialization failed",
            exc_info=True,
            extra=worker_log_extra(
                worker_name=_WORKER_NAME,
                queue=_QUEUE_NAME,
                calculation_id=str(calculation_id),
                calculation_type=calculation_type,
                lineage_stage=lineage_stage,
                failure_classification="lineage_execution_stage_unavailable",
                retryable=False,
            ),
        )
        try:
            execution_store.mark_failed(calculation_id, error_message)
        except Exception:
            logger.warning(
                "Execution record unavailable while marking lineage materialization failed",
                exc_info=True,
                extra=worker_log_extra(
                    worker_name=_WORKER_NAME,
                    queue=_QUEUE_NAME,
                    calculation_id=str(calculation_id),
                    calculation_type=calculation_type,
                    lineage_stage=lineage_stage,
                    failure_classification="lineage_execution_record_unavailable",
                    retryable=False,
                ),
            )


if __name__ == "__main__":
    run_forever()
