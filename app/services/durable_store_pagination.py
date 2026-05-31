from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class RecoveryCursorItem(Protocol):
    @property
    def calculation_id(self) -> str: ...

    @property
    def recovered_at_utc(self) -> str: ...


@dataclass(frozen=True)
class RecoveryCursor:
    recovered_before: str | None
    calculation_id_before: str | None


def next_offset_or_none(*, offset: int, item_count: int, total_count: int) -> int | None:
    next_offset = offset + item_count
    return next_offset if next_offset < total_count else None


def recovery_cursor_or_none(*, next_offset: int | None, items: Sequence[RecoveryCursorItem]) -> RecoveryCursor:
    if next_offset is None or not items:
        return RecoveryCursor(recovered_before=None, calculation_id_before=None)
    last_item = items[-1]
    return RecoveryCursor(
        recovered_before=last_item.recovered_at_utc,
        calculation_id_before=last_item.calculation_id,
    )
