from __future__ import annotations

from datetime import datetime, timezone


def coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_filter_datetime(value: datetime | None, *, dialect_name: str) -> datetime | None:
    if value is None:
        return None
    normalized = coerce_utc_datetime(value)
    if dialect_name == "sqlite":
        return normalized.replace(tzinfo=None)
    return normalized


def format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return coerce_utc_datetime(value).isoformat().replace("+00:00", "Z")
