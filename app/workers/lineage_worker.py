from __future__ import annotations

import logging
import time

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


def run_forever() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    logger.info("Starting lineage worker poller")
    execution_registry.create_schema()
    lineage_metadata_store.create_schema()
    while True:
        processed = process_pending_jobs()
        if processed == 0:
            time.sleep(settings.LINEAGE_WORKER_POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
