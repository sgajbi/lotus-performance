from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class InspectionQueryContext:
    status_filter: str
    now: datetime
    min_age_threshold: datetime | None


def build_inspection_query_context(
    *,
    status_filter: str,
    min_age_seconds: float,
    now: datetime | None = None,
) -> InspectionQueryContext:
    inspection_now = now or datetime.now(timezone.utc)
    normalized_status_filter = status_filter.lower()
    min_age_threshold = inspection_now - timedelta(seconds=min_age_seconds) if min_age_seconds > 0 else None
    return InspectionQueryContext(
        status_filter=normalized_status_filter,
        now=inspection_now,
        min_age_threshold=min_age_threshold,
    )


def apply_min_age_filter(statement: Any, *, active_since: Any, min_age_threshold: datetime | None) -> Any:
    if min_age_threshold is None:
        return statement
    return statement.where(active_since <= min_age_threshold)
