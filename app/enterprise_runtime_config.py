import json
import os
from typing import Any

_DEFAULT_ENTERPRISE_POLICY_VERSION = "1.0.0"
_MISSING_POLICY_VERSION_ISSUE = "missing_policy_version"
# Issue code and environment variable name contain "secret" but do not carry credential material.
_SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE = "secret_rotation_days_out_of_range"  # nosec B105
_MISSING_PRIMARY_KEY_ID_ISSUE = "missing_primary_key_id"
_RUNTIME_CONFIG_INVALID_PREFIX = "enterprise_runtime_config_invalid"
_DIAGNOSTIC_LIST_SEPARATOR = ","
_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ = "ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ"
_ENV_ENTERPRISE_ENFORCE_AUTHZ = "ENTERPRISE_ENFORCE_AUTHZ"
_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG = "ENTERPRISE_ENFORCE_RUNTIME_CONFIG"
_ENV_ENTERPRISE_PRIMARY_KEY_ID = "ENTERPRISE_PRIMARY_KEY_ID"
_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES = "ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES"
_ENV_ENTERPRISE_POLICY_VERSION = "ENTERPRISE_POLICY_VERSION"
_ENV_ENTERPRISE_SECRET_ROTATION_DAYS = "ENTERPRISE_SECRET_ROTATION_DAYS"  # nosec B105
_ENV_ENTERPRISE_FEATURE_FLAGS_JSON = "ENTERPRISE_FEATURE_FLAGS_JSON"
_ENV_ENTERPRISE_CAPABILITY_RULES_JSON = "ENTERPRISE_CAPABILITY_RULES_JSON"
_ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON = "ENTERPRISE_PRIVILEGED_READ_RULES_JSON"
_ENV_SWITCH_DISABLED_DEFAULT = "false"
_ENV_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
_EMPTY_ENV_VALUE = ""
_EMPTY_JSON_OBJECT = "{}"
_DEFAULT_MAX_WRITE_PAYLOAD_BYTES = 1_048_576
_DEFAULT_SECRET_ROTATION_DAYS = 90


def _env_value(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_enabled(name: str, default: str = "true") -> bool:
    return _env_value(name, default).strip().lower() in _ENV_ENABLED_VALUES


def _privileged_read_authz_enabled() -> bool:
    return _env_enabled(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, _ENV_SWITCH_DISABLED_DEFAULT)


def _write_authz_enabled() -> bool:
    return _env_enabled(_ENV_ENTERPRISE_ENFORCE_AUTHZ, _ENV_SWITCH_DISABLED_DEFAULT)


def _runtime_config_enforcement_enabled() -> bool:
    return _env_enabled(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, _ENV_SWITCH_DISABLED_DEFAULT)


def _primary_key_configured() -> bool:
    return bool(_env_value(_ENV_ENTERPRISE_PRIMARY_KEY_ID, _EMPTY_ENV_VALUE).strip())


def _max_write_payload_bytes() -> int:
    return _env_int(_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES, _DEFAULT_MAX_WRITE_PAYLOAD_BYTES)


def _load_json_map(name: str) -> dict[str, Any]:
    raw = _env_value(name, _EMPTY_JSON_OBJECT)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _empty_json_map()
    return parsed if isinstance(parsed, dict) else _empty_json_map()


def _empty_json_map() -> dict[str, Any]:
    return {}


def _env_int(name: str, default: int) -> int:
    return _parse_int_or_default(_env_value(name, str(default)), default)


def _parse_int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _configured_enterprise_policy_version() -> str:
    return _env_value(_ENV_ENTERPRISE_POLICY_VERSION, _DEFAULT_ENTERPRISE_POLICY_VERSION)


def _normalized_enterprise_policy_version() -> str:
    return _configured_enterprise_policy_version().strip()


def enterprise_policy_version() -> str:
    return _normalized_enterprise_policy_version() or _DEFAULT_ENTERPRISE_POLICY_VERSION


def _enterprise_runtime_config_issues() -> list[str]:
    issues: list[str] = []
    if not _normalized_enterprise_policy_version():
        issues.append(_MISSING_POLICY_VERSION_ISSUE)

    rotation_days = _env_int(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, _DEFAULT_SECRET_ROTATION_DAYS)
    if rotation_days <= 0 or rotation_days > _DEFAULT_SECRET_ROTATION_DAYS:
        issues.append(_SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE)

    if _write_authz_enabled() and not _primary_key_configured():
        issues.append(_MISSING_PRIMARY_KEY_ID_ISSUE)

    return issues


def _runtime_config_invalid_message(issues: list[str]) -> str:
    return f"{_RUNTIME_CONFIG_INVALID_PREFIX}:{_DIAGNOSTIC_LIST_SEPARATOR.join(issues)}"


def validate_enterprise_runtime_config() -> list[str]:
    issues = _enterprise_runtime_config_issues()
    if issues and _runtime_config_enforcement_enabled():
        raise RuntimeError(_runtime_config_invalid_message(issues))
    return issues
