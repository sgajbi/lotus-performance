from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypeGuard

_INVALID_JSON_PAYLOAD = object()


def load_json_object_or_none(
    raw_payload: str | None,
    *,
    logger: logging.Logger,
    payload_name: str,
    identity_name: str,
    identity_value: str,
    empty_is_absent: bool = True,
) -> dict[str, Any] | None:
    present_payload = _present_json_payload_or_none(raw_payload, empty_is_absent=empty_is_absent)
    if present_payload is None:
        return None
    payload = _load_json_payload_or_invalid(
        present_payload,
        logger=logger,
        payload_name=payload_name,
        identity_name=identity_name,
        identity_value=identity_value,
    )
    if payload is _INVALID_JSON_PAYLOAD:
        return None
    if not _is_json_object_payload(payload):
        logger.warning("%s is not an object for %s=%s.", payload_name, identity_name, identity_value)
        return None
    return payload


def load_json_string_list_or_default(
    raw_payload: str,
    *,
    logger: logging.Logger,
    payload_name: str,
    identity_name: str,
    identity_value: str,
    default_value: list[str],
) -> list[str]:
    payload = _load_json_payload_or_invalid(
        raw_payload,
        logger=logger,
        payload_name=payload_name,
        identity_name=identity_name,
        identity_value=identity_value,
    )
    if payload is _INVALID_JSON_PAYLOAD:
        return default_value
    if not _is_non_empty_string_list_payload(payload):
        logger.warning("%s is not a string list for %s=%s.", payload_name, identity_name, identity_value)
        return default_value
    return payload


def _load_json_payload_or_invalid(
    raw_payload: str,
    *,
    logger: logging.Logger,
    payload_name: str,
    identity_name: str,
    identity_value: str,
) -> Any:
    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError:
        logger.warning("%s invalid JSON for %s=%s.", payload_name, identity_name, identity_value)
    return _INVALID_JSON_PAYLOAD


def _present_json_payload_or_none(raw_payload: str | None, *, empty_is_absent: bool) -> str | None:
    if raw_payload is None:
        return None
    if empty_is_absent and raw_payload == "":
        return None
    return raw_payload


def _is_non_empty_string_list_payload(payload: Any) -> TypeGuard[list[str]]:
    return isinstance(payload, list) and all(isinstance(item, str) and item for item in payload)


def _is_json_object_payload(payload: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(payload, dict)


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_object_file(
    path: Path, *, object_error_message: str = "JSON payload must be an object"
) -> dict[str, Any]:
    payload = read_json_file(path)
    if not isinstance(payload, dict):
        raise TypeError(object_error_message)
    return payload
