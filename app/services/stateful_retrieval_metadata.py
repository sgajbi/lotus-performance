from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from numbers import Real

from app.services.stateful_input_service import RetrievalMetadata

MALFORMED_RETRIEVAL_METADATA_COUNT_REASON = "MALFORMED_UPSTREAM_RETRIEVAL_METADATA_COUNT"


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
    parsed_chunk_count, invalid_chunk_count = _metadata_count(
        chunk_count,
        default_value=default_chunk_count,
        coerce_numeric_counts=coerce_numeric_counts,
    )
    parsed_page_count, invalid_page_count = _metadata_count(
        page_count,
        default_value=default_page_count,
        coerce_numeric_counts=coerce_numeric_counts,
    )
    invalid_count_fields = tuple(
        field_name
        for field_name, invalid in (
            ("retrieval_metadata.chunk_count", invalid_chunk_count),
            ("retrieval_metadata.page_count", invalid_page_count),
        )
        if invalid
    )
    return RetrievalMetadata(
        chunk_count=parsed_chunk_count,
        page_count=parsed_page_count,
        invalid_count_fields=invalid_count_fields,
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


def add_zero_default_retrieval_metadata(
    total: RetrievalMetadata,
    payload: Mapping[str, object] | None,
) -> RetrievalMetadata:
    metadata = parse_zero_default_retrieval_metadata(payload)
    return RetrievalMetadata(
        chunk_count=total.chunk_count + metadata.chunk_count,
        page_count=total.page_count + metadata.page_count,
    )


def _metadata_count(
    value: object,
    *,
    default_value: int,
    coerce_numeric_counts: bool,
) -> tuple[int, bool]:
    if value is None:
        return default_value, False
    if type(value) is int and value > 0:
        return value, False
    if coerce_numeric_counts:
        coerced_count = _coerced_metadata_count(value)
        if coerced_count is not None:
            return coerced_count, False
    return default_value, True


def _coerced_metadata_count(value: object) -> int | None:
    if isinstance(value, str):
        return _positive_integral_decimal_or_none(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return _positive_integral_decimal_or_none(str(value))
    return None


def _positive_integral_decimal_or_none(value: str) -> int | None:
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if decimal_value <= 0 or decimal_value != decimal_value.to_integral_value():
        return None
    return int(decimal_value)
