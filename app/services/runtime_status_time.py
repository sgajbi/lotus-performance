from __future__ import annotations

from datetime import UTC, datetime

from app.services.durable_store_time import elapsed_seconds_since


def parse_utc_datetime(timestamp_utc: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def age_seconds_since(timestamp_utc: str) -> float:
    return elapsed_seconds_since(datetime.now(UTC), parse_utc_datetime(timestamp_utc))


def parse_reclaimed_at_utc(timestamp_utc: str) -> datetime:
    return parse_utc_datetime(timestamp_utc)
