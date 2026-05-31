from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.runtime_status_time import parse_utc_datetime

AppliedHistoryFilters = dict[str, str | int]
OptionalHistoryFilter = tuple[str, str | int | None]


@dataclass(frozen=True)
class GeneratedAtBounds:
    after: datetime | None
    before: datetime | None

    @property
    def has_bounds(self) -> bool:
        return self.after is not None or self.before is not None


def parse_generated_at_bounds(
    *,
    generated_after: str | None,
    generated_before: str | None,
) -> GeneratedAtBounds:
    return GeneratedAtBounds(
        after=parse_generated_at_filter(generated_after),
        before=parse_generated_at_filter(generated_before),
    )


def generated_at_within_bounds(generated_at_utc: str, *, bounds: GeneratedAtBounds) -> bool:
    generated_at = parse_generated_at_filter(generated_at_utc)
    if generated_at is None:
        return False
    if bounds.after is not None and generated_at < bounds.after:
        return False
    if bounds.before is not None and generated_at > bounds.before:
        return False
    return True


def parse_generated_at_filter(value: str | None) -> datetime | None:
    if value is None:
        return None
    return parse_utc_datetime(value)


def build_applied_history_filters(
    *,
    limit: int | None,
    offset: int,
    optional_filters: tuple[OptionalHistoryFilter, ...],
    generated_after: str | None,
    generated_before: str | None,
) -> AppliedHistoryFilters:
    filters: AppliedHistoryFilters = {}
    if limit is not None:
        filters["limit"] = limit
    if offset > 0:
        filters["offset"] = offset
    for key, value in optional_filters:
        if value is not None:
            filters[key] = value
    if generated_after is not None:
        filters["generated_after"] = generated_after
    if generated_before is not None:
        filters["generated_before"] = generated_before
    return filters
