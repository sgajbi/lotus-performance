from __future__ import annotations

from typing import Any, TypeGuard


def is_required_evidence_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def is_optional_evidence_string(value: object) -> TypeGuard[str | None]:
    return value is None or is_required_evidence_string(value)


def required_evidence_string_fields_present(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(is_required_evidence_string(payload.get(key)) for key in keys)


def optional_evidence_string_fields_valid(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(is_optional_evidence_string(payload.get(key)) for key in keys)


def required_evidence_int_fields_present(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(type(payload.get(key)) is int for key in keys)


def optional_evidence_int_fields_valid(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(payload.get(key) is None or type(payload.get(key)) is int for key in keys)


def required_evidence_bool_fields_present(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(type(payload.get(key)) is bool for key in keys)


def is_required_evidence_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(is_required_evidence_string(item) for item in value)


def normalize_required_evidence_identifier(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def normalize_optional_evidence_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def required_evidence_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not is_required_evidence_string(value):
        raise ValueError(f"{key} must be a nonblank string")
    return value.strip()


def optional_evidence_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when present")
    return value.strip() or None
