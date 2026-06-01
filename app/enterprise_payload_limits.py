from typing import Any, Mapping

from app import enterprise_response_envelopes as _response_envelopes
from app.enterprise_capability_rules import _is_write_method
from app.enterprise_runtime_config import _parse_int_or_default

_HTTP_STATUS_PAYLOAD_TOO_LARGE = _response_envelopes._HTTP_STATUS_PAYLOAD_TOO_LARGE
_PAYLOAD_TOO_LARGE_DETAIL = _response_envelopes._PAYLOAD_TOO_LARGE_DETAIL
_RESPONSE_DETAIL_KEY = _response_envelopes._RESPONSE_DETAIL_KEY
_payload_too_large_response = _response_envelopes._payload_too_large_response
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
