from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

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
    next_offset = None
    if limit is not None and offset + len(paged_entries) < len(entries):
        next_offset = offset + len(paged_entries)
    return HistoryPage(entries=paged_entries, next_offset=next_offset)
