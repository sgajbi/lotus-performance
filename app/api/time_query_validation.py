from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.services.runtime_status_time import parse_utc_datetime
from core.errors import HTTP_422_UNPROCESSABLE


def validate_utc_query_timestamp_window(
    *,
    generated_after: str | None,
    generated_before: str | None,
) -> tuple[str | None, str | None]:
    parsed_after = _parse_optional_utc_query_timestamp(generated_after, field_name="generated_after")
    parsed_before = _parse_optional_utc_query_timestamp(generated_before, field_name="generated_before")
    if parsed_after is not None and parsed_before is not None and parsed_after > parsed_before:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": "invalid_utc_timestamp_filter_window",
                "fields": ["generated_after", "generated_before"],
                "message": "generated_after must be less than or equal to generated_before.",
            },
        )
    return generated_after, generated_before


def _parse_optional_utc_query_timestamp(value: str | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return parse_utc_datetime(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": "invalid_utc_timestamp_filter",
                "field": field_name,
                "message": f"{field_name} must be an ISO-8601 UTC timestamp.",
            },
        ) from exc
