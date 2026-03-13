from __future__ import annotations

import logging
import time
from threading import Event

from app.core.config import get_settings
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.lineage_service import lineage_service

logger = logging.getLogger(__name__)
settings = get_settings()


def process_pending_jobs(*, limit: int | None = None) -> int:
    batch_size = limit or settings.LINEAGE_WORKER_BATCH_SIZE
    pending = lineage_metadata_store.list_pending_payloads(limit=batch_size)
    processed = 0
    for payload in pending:
        lineage_metadata_store.increment_attempt_count(payload.calculation_id)
        lineage_service.materialize_payload(
            calculation_id=payload.calculation_id,
            calculation_type=payload.calculation_type,
            request_json=payload.request_json,
            response_json=payload.response_json,
            calculation_details=payload.details,
        )
        processed += 1
    return processed


def run_forever(*, stop_event: Event | None = None) -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    logger.info("Starting lineage worker poller")
    execution_registry.create_schema()
    lineage_metadata_store.create_schema()
    while not _stop_requested(stop_event):
        processed = process_pending_jobs()
        if processed == 0 and _wait_for_next_poll(stop_event, settings.LINEAGE_WORKER_POLL_SECONDS):
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
