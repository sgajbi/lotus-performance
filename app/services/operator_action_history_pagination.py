from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.services.durable_store_pagination import next_offset_or_none

EntryT = TypeVar("EntryT")


@dataclass(frozen=True)
class HistoryPage(Generic[EntryT]):
    entries: list[EntryT]
    next_offset: int | None


def paginate_history_entries(
    entries: list[EntryT],
    *,
    limit: int | None,
    offset: int,
) -> HistoryPage[EntryT]:
    paged_entries = entries[offset:]
    if limit is not None:
        paged_entries = paged_entries[:limit]
    next_offset = (
        next_offset_or_none(offset=offset, item_count=len(paged_entries), total_count=len(entries))
        if limit is not None
        else None
    )
    return HistoryPage(entries=paged_entries, next_offset=next_offset)
