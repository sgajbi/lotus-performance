from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.runtime_status_time import parse_utc_datetime


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
