from __future__ import annotations

from fastapi import HTTPException

from app.services.runtime_status_time import parse_utc_datetime
from core.errors import HTTP_422_UNPROCESSABLE


def validate_optional_utc_query_timestamp(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        parse_utc_datetime(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": "invalid_utc_timestamp_filter",
                "field": field_name,
                "message": f"{field_name} must be an ISO-8601 UTC timestamp.",
            },
        ) from exc
    return value
