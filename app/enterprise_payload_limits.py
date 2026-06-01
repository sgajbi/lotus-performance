from typing import Any, Mapping

from fastapi.responses import JSONResponse

from app.enterprise_capability_rules import _is_write_method
from app.enterprise_runtime_config import _parse_int_or_default

_RESPONSE_DETAIL_KEY = "detail"
_PAYLOAD_TOO_LARGE_DETAIL = "payload_too_large"
_HTTP_STATUS_PAYLOAD_TOO_LARGE = 413
_CONTENT_LENGTH_HEADER = "content-length"
_MISSING_CONTENT_LENGTH = "0"


def _content_length(headers: Mapping[str, Any]) -> int:
    return _parse_int_or_default(headers.get(_CONTENT_LENGTH_HEADER, _MISSING_CONTENT_LENGTH), 0)


def _write_payload_too_large(
    *,
    method: str,
    headers: Mapping[str, Any],
    max_write_payload_bytes: int,
) -> bool:
    return _is_write_method(method) and _content_length(headers) > max_write_payload_bytes


def _payload_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=_HTTP_STATUS_PAYLOAD_TOO_LARGE,
        content={_RESPONSE_DETAIL_KEY: _PAYLOAD_TOO_LARGE_DETAIL},
    )
