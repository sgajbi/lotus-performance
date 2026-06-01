from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from app.services.operator_action_evidence_strings import normalize_optional_evidence_identifier
from app.services.runtime_status_time import parse_utc_datetime

AppliedHistoryFilters = dict[str, str | int]
OptionalHistoryFilter = tuple[str, str | int | None]
HistoryEntryT = TypeVar("HistoryEntryT")
HistoryExactFilter = tuple[str | None, Callable[[HistoryEntryT], str | None]]


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
        normalized_value = _normalize_optional_history_filter(value)
        if normalized_value is not None:
            filters[key] = normalized_value
    if generated_after is not None:
        filters["generated_after"] = generated_after
    if generated_before is not None:
        filters["generated_before"] = generated_before
    return filters


def filter_history_entries(
    entries: list[HistoryEntryT],
    *,
    exact_filters: tuple[HistoryExactFilter[HistoryEntryT], ...],
    generated_after: str | None,
    generated_before: str | None,
    get_generated_at_utc: Callable[[HistoryEntryT], str],
) -> list[HistoryEntryT]:
    filtered = entries
    for expected_value, read_value in exact_filters:
        normalized_expected = _normalize_optional_history_filter(expected_value)
        if isinstance(normalized_expected, str):
            filtered = [entry for entry in filtered if read_value(entry) == normalized_expected]

    generated_at_bounds = parse_generated_at_bounds(
        generated_after=generated_after,
        generated_before=generated_before,
    )
    if generated_at_bounds.has_bounds:
        filtered = [
            entry
            for entry in filtered
            if generated_at_within_bounds(get_generated_at_utc(entry), bounds=generated_at_bounds)
        ]
    return filtered


def _normalize_optional_history_filter(value: str | int | None) -> str | int | None:
    if isinstance(value, str):
        return normalize_optional_evidence_identifier(value)
    return value
