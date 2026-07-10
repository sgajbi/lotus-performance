from __future__ import annotations

from math import ceil

from app.core.config import Settings, get_settings

ASYNC_RETRY_AFTER_HEADER = "Retry-After"
DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS = 1


def recommended_async_poll_after_seconds(settings: Settings | None = None) -> int:
    active_settings = settings or get_settings()
    worker_poll_seconds = max(
        active_settings.COMPUTE_EXECUTOR_POLL_SECONDS,
        active_settings.LINEAGE_WORKER_POLL_SECONDS,
        DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
    )
    return max(DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS, ceil(worker_poll_seconds))
