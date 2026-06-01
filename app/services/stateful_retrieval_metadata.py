from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from numbers import Real

from app.services.stateful_input_service import RetrievalMetadata


def parse_retrieval_metadata(
    payload: Mapping[str, object],
    *,
    default_chunk_count: int = 1,
    default_page_count: int = 1,
    coerce_numeric_counts: bool = False,
) -> RetrievalMetadata:
    metadata_raw = payload.get("retrieval_metadata")
    if not isinstance(metadata_raw, Mapping):
        return RetrievalMetadata(chunk_count=default_chunk_count, page_count=default_page_count)
    chunk_count = metadata_raw.get("chunk_count")
    page_count = metadata_raw.get("page_count")
    return RetrievalMetadata(
        chunk_count=_metadata_count(
            chunk_count,
            default_value=default_chunk_count,
            coerce_numeric_counts=coerce_numeric_counts,
        ),
        page_count=_metadata_count(
            page_count,
            default_value=default_page_count,
            coerce_numeric_counts=coerce_numeric_counts,
        ),
    )


def parse_zero_default_retrieval_metadata(payload: Mapping[str, object] | None) -> RetrievalMetadata:
    if payload is None:
        return RetrievalMetadata(chunk_count=0, page_count=0)
    return parse_retrieval_metadata(
        payload,
        default_chunk_count=0,
        default_page_count=0,
        coerce_numeric_counts=True,
    )


def _metadata_count(
    value: object,
    *,
    default_value: int,
    coerce_numeric_counts: bool,
) -> int:
    if type(value) is int and value > 0:
        return value
    if coerce_numeric_counts and isinstance(value, str):
        return int(value)
    if coerce_numeric_counts and isinstance(value, Real) and not isinstance(value, bool):
        return int(Decimal(str(value)))
    return default_value
