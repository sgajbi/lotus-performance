import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any

_DEFAULT_ENTERPRISE_POLICY_VERSION = "1.0.0"
_MISSING_POLICY_VERSION_ISSUE = "missing_policy_version"
# Issue code and environment variable name contain "secret" but do not carry credential material.
_SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE = "secret_rotation_days_out_of_range"  # nosec B105
_MISSING_PRIMARY_KEY_ID_ISSUE = "missing_primary_key_id"
_PRODUCTION_WRITE_AUTHZ_DISABLED_ISSUE = "production_write_authz_disabled"
_PRODUCTION_PRIVILEGED_READ_AUTHZ_DISABLED_ISSUE = "production_privileged_read_authz_disabled"
_PRODUCTION_RUNTIME_CONFIG_ENFORCEMENT_DISABLED_ISSUE = "production_runtime_config_enforcement_disabled"
_PRODUCTION_RUNTIME_THRESHOLD_DISABLED_ISSUE_PREFIX = "production_runtime_threshold_disabled"
_RUNTIME_CONFIG_INVALID_PREFIX = "enterprise_runtime_config_invalid"
_DIAGNOSTIC_LIST_SEPARATOR = ","
_ENV_ENTERPRISE_RUNTIME_PROFILE = "ENTERPRISE_RUNTIME_PROFILE"
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
_PRODUCTION_LIKE_RUNTIME_PROFILES = frozenset({"prod", "production", "staging"})
_DEFAULT_RUNTIME_PROFILE = "local"
_EMPTY_ENV_VALUE = ""
_EMPTY_JSON_OBJECT = "{}"
_DEFAULT_MAX_WRITE_PAYLOAD_BYTES = 1_048_576
_DEFAULT_SECRET_ROTATION_DAYS = 90
_PRODUCTION_RUNTIME_THRESHOLD_FIELDS = (
    "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS",
    "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS",
    "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS",
    "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT",
    "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT",
    "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT",
    "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS",
    "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS",
    "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT",
    "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT",
    "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES",
    "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO",
    "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS",
    "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
    "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT",
    "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS",
    "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
    "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT",
)


def _env_value(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_enabled(name: str, default: str = "true") -> bool:
    return _env_value(name, default).strip().lower() in _ENV_ENABLED_VALUES


def _runtime_profile() -> str:
    return _env_value(_ENV_ENTERPRISE_RUNTIME_PROFILE, _DEFAULT_RUNTIME_PROFILE).strip().lower()


def _production_like_runtime_profile_enabled() -> bool:
    return _runtime_profile() in _PRODUCTION_LIKE_RUNTIME_PROFILES


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


def _secret_rotation_days_valid(rotation_days: int) -> bool:
    return 0 < rotation_days <= _DEFAULT_SECRET_ROTATION_DAYS


def _write_authz_primary_key_config_valid() -> bool:
    return not _write_authz_enabled() or _primary_key_configured()


def _production_primary_key_config_valid() -> bool:
    return not _production_like_runtime_profile_enabled() or _primary_key_configured()


def _runtime_config_issues_should_raise(issues: list[str]) -> bool:
    return bool(issues) and (_runtime_config_enforcement_enabled() or _production_like_runtime_profile_enabled())


def _production_runtime_profile_issues(existing_issues: list[str]) -> list[str]:
    if not _production_like_runtime_profile_enabled():
        return []

    return [
        issue
        for issue, requirement_satisfied in _production_runtime_profile_requirements(existing_issues)
        if not requirement_satisfied
    ]


def _production_runtime_profile_requirements(existing_issues: list[str]) -> tuple[tuple[str, bool], ...]:
    return (
        (_PRODUCTION_WRITE_AUTHZ_DISABLED_ISSUE, _write_authz_enabled()),
        (_PRODUCTION_PRIVILEGED_READ_AUTHZ_DISABLED_ISSUE, _privileged_read_authz_enabled()),
        (_PRODUCTION_RUNTIME_CONFIG_ENFORCEMENT_DISABLED_ISSUE, _runtime_config_enforcement_enabled()),
        (_MISSING_PRIMARY_KEY_ID_ISSUE, not _production_primary_key_issue_needed(existing_issues)),
    )


def _production_runtime_threshold_issues(settings: Any | None = None) -> list[str]:
    if not _production_like_runtime_profile_enabled():
        return []

    active_settings = settings if settings is not None else _default_settings()
    return [
        _runtime_threshold_disabled_issue(field_name)
        for field_name in _PRODUCTION_RUNTIME_THRESHOLD_FIELDS
        if _runtime_threshold_disabled(active_settings, field_name)
    ]


def _default_settings() -> Any:
    from app.core.config import get_settings

    return get_settings()


def _runtime_threshold_disabled(settings: Any, field_name: str) -> bool:
    value = getattr(settings, field_name, 0)
    try:
        return Decimal(str(value)) <= Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return True


def _runtime_threshold_disabled_issue(field_name: str) -> str:
    return f"{_PRODUCTION_RUNTIME_THRESHOLD_DISABLED_ISSUE_PREFIX}:{field_name}"


def _production_primary_key_issue_needed(existing_issues: list[str]) -> bool:
    return not _production_primary_key_config_valid() and _MISSING_PRIMARY_KEY_ID_ISSUE not in existing_issues


def _enterprise_runtime_config_issues(settings: Any | None = None) -> list[str]:
    issues: list[str] = []
    if not _normalized_enterprise_policy_version():
        issues.append(_MISSING_POLICY_VERSION_ISSUE)

    rotation_days = _env_int(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, _DEFAULT_SECRET_ROTATION_DAYS)
    if not _secret_rotation_days_valid(rotation_days):
        issues.append(_SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE)

    if not _write_authz_primary_key_config_valid():
        issues.append(_MISSING_PRIMARY_KEY_ID_ISSUE)

    issues.extend(_production_runtime_profile_issues(issues))
    issues.extend(_production_runtime_threshold_issues(settings=settings))
    return issues


def _runtime_config_invalid_message(issues: list[str]) -> str:
    return f"{_RUNTIME_CONFIG_INVALID_PREFIX}:{_DIAGNOSTIC_LIST_SEPARATOR.join(issues)}"


def validate_enterprise_runtime_config(settings: Any | None = None) -> list[str]:
    issues = _enterprise_runtime_config_issues(settings=settings)
    if _runtime_config_issues_should_raise(issues):
        raise RuntimeError(_runtime_config_invalid_message(issues))
    return issues
