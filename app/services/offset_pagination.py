from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from core.errors import APIUnprocessableEntityError

T = TypeVar("T")


@dataclass(frozen=True)
class OffsetPage(Generic[T]):
    items: list[T]
    next_page_token: str | None


def parse_offset_page_token(
    page_token: str | None,
    *,
    invalid_detail: str,
    negative_detail: str,
) -> int:
    try:
        start = int(page_token) if page_token else 0
    except ValueError as exc:
        raise APIUnprocessableEntityError(invalid_detail) from exc
    if start < 0:
        raise APIUnprocessableEntityError(negative_detail)
    return start


def slice_offset_page(
    items: Sequence[T],
    *,
    page_size: int,
    page_token: str | None,
    invalid_token_detail: str,
    negative_token_detail: str,
) -> OffsetPage[T]:
    start = parse_offset_page_token(
        page_token,
        invalid_detail=invalid_token_detail,
        negative_detail=negative_token_detail,
    )
    end = start + page_size
    next_page_token = str(end) if end < len(items) else None
    return OffsetPage(items=list(items[start:end]), next_page_token=next_page_token)
