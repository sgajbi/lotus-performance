from __future__ import annotations


def next_offset_or_none(*, offset: int, item_count: int, total_count: int) -> int | None:
    next_offset = offset + item_count
    return next_offset if next_offset < total_count else None
