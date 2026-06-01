from typing import Any

_REDACTED_VALUE = "***REDACTED***"
_REDACT_FIELDS = {
    "password",
    "secret",
    "token",
    "authorization",
    "ssn",
    "account_number",
    "client_email",
}


def _normalized_redaction_field(field: Any) -> str:
    return str(field).lower()


def _should_redact_field(field: Any) -> bool:
    return _normalized_redaction_field(field) in _REDACT_FIELDS


def _redacted_mapping_value(*, field: Any, value: Any) -> Any:
    return _REDACTED_VALUE if _should_redact_field(field) else redact_sensitive(value)


def _redacted_mapping(values: dict[Any, Any]) -> dict[Any, Any]:
    output: dict[Any, Any] = {}
    for key, item in values.items():
        output[key] = _redacted_mapping_value(field=key, value=item)
    return output


def _redacted_sequence(values: list[Any]) -> list[Any]:
    return [redact_sensitive(item) for item in values]


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return _redacted_mapping(value)
    if isinstance(value, list):
        return _redacted_sequence(value)
    return value
