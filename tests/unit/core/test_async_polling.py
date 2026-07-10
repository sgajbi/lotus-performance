from app.core.async_polling import (
    DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
    recommended_async_poll_after_seconds,
)
from app.core.config import Settings


def test_recommended_async_poll_after_seconds_defaults_to_one_second_floor() -> None:
    settings = Settings(COMPUTE_EXECUTOR_POLL_SECONDS=0.1, LINEAGE_WORKER_POLL_SECONDS=0.2)

    assert recommended_async_poll_after_seconds(settings) == DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS


def test_recommended_async_poll_after_seconds_ceilings_worker_cadence() -> None:
    settings = Settings(COMPUTE_EXECUTOR_POLL_SECONDS=2.1, LINEAGE_WORKER_POLL_SECONDS=1.5)

    assert recommended_async_poll_after_seconds(settings) == 3
