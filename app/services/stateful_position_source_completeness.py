"""Shared completeness proof for retained stateful position rows."""

from __future__ import annotations


def position_source_rows_are_complete(
    *,
    payload: dict[str, object],
    retained_row_count: int,
) -> bool:
    """Require Core's source/retained/discarded counts before treating rows as a complete calendar."""
    metadata = payload.get("retrieval_metadata")
    if not isinstance(metadata, dict):
        return False
    source_row_count = _non_negative_int_or_none(metadata.get("source_row_count"))
    declared_retained_row_count = _non_negative_int_or_none(metadata.get("retained_row_count"))
    discarded_source_row_count = _non_negative_int_or_none(metadata.get("discarded_source_row_count"))
    return (
        source_row_count is not None
        and declared_retained_row_count == retained_row_count
        and discarded_source_row_count == 0
        and source_row_count >= retained_row_count
    )


def _non_negative_int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
