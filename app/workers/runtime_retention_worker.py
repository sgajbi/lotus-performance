from __future__ import annotations

import logging
import time
from threading import Event

from app.core.config import get_settings
from app.observability import setup_worker_logging, worker_log_extra
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.runtime_retention_execution_service import execute_runtime_retention_cleanup

logger = logging.getLogger(__name__)
_WORKER_NAME = "runtime_retention_worker"
_QUEUE_NAME = "runtime_retention"


def run_cleanup_cycle(*, settings=None):
    active_settings = settings or get_settings()
    return execute_runtime_retention_cleanup(
        apply=bool(active_settings.RUNTIME_RETENTION_WORKER_APPLY),
        operator_id=active_settings.RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID,
        trigger_mode="scheduled",
        job_id=active_settings.RUNTIME_RETENTION_AUTOMATION_JOB_ID,
    )


def run_forever(*, stop_event: Event | None = None, settings=None) -> None:
    active_settings = settings or get_settings()
    setup_worker_logging(active_settings.LOG_LEVEL)
    logger.info(
        "Starting runtime retention worker",
        extra=worker_log_extra(
            worker_name=_WORKER_NAME,
            worker_id=active_settings.RUNTIME_RETENTION_AUTOMATION_JOB_ID,
            queue=_QUEUE_NAME,
            operator_id=active_settings.RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID,
        ),
    )
    bootstrap_durable_metadata_stores(
        execution_store=execution_registry,
        compute_store=compute_job_store,
        async_result_store_=async_result_store,
        lineage_store=lineage_metadata_store,
    )
    while not _stop_requested(stop_event):
        evidence = run_cleanup_cycle(settings=active_settings)
        logger.info(
            "Runtime retention scheduled cleanup completed",
            extra=worker_log_extra(
                worker_name=_WORKER_NAME,
                worker_id=active_settings.RUNTIME_RETENTION_AUTOMATION_JOB_ID,
                queue=_QUEUE_NAME,
                operator_id=active_settings.RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID,
                cleanup_mode=evidence.cleanup_mode,
                cleanup_status=evidence.status,
                prunable_execution_count=evidence.prunable_execution_count,
                trigger_mode="scheduled",
            ),
        )
        if _wait_for_next_poll(stop_event, active_settings.RUNTIME_RETENTION_WORKER_POLL_SECONDS):
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
