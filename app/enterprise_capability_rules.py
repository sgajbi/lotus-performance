from typing import Any

from app.enterprise_runtime_config import (
    _ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
    _ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON,
    _load_json_map,
)

_CAPABILITY_OPERATIONS_RUNTIME_MANAGE = "operations.runtime.manage"
_CAPABILITY_OPERATIONS_RUNTIME_READ = "operations.runtime.read"
_HTTP_METHOD_DELETE = "DELETE"
_HTTP_METHOD_GET = "GET"
_HTTP_METHOD_PATCH = "PATCH"
_HTTP_METHOD_POST = "POST"
_HTTP_METHOD_PUT = "PUT"
_CAPABILITY_RULE_METHOD_PATH_SEPARATOR = " "
_PATH_RUNTIME_RETENTION_CLEANUP_RUN = "/integration/runtime-retention-cleanups/run"
_PATH_RECOVERY_DRILL_RUN = "/integration/recovery-drills/run"
_PATH_RUNTIME_STATUS = "/integration/runtime-status"
_PATH_RUNTIME_WORK_ITEMS = "/integration/runtime-work-items"
_PATH_RUNTIME_RECOVERIES = "/integration/runtime-recoveries"
_PATH_RECOVERY_DRILLS = "/integration/recovery-drills"
_PATH_RUNTIME_RETENTION_CLEANUPS = "/integration/runtime-retention-cleanups"
_WRITE_METHODS = {_HTTP_METHOD_POST, _HTTP_METHOD_PUT, _HTTP_METHOD_PATCH, _HTTP_METHOD_DELETE}


def _normalized_http_method(method: str) -> str:
    return method.upper()


def _capability_rule_key(*, method: str, path: str) -> str:
    return f"{_normalized_http_method(method)}{_CAPABILITY_RULE_METHOD_PATH_SEPARATOR}{path}"


_RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE = _capability_rule_key(
    method=_HTTP_METHOD_POST,
    path=_PATH_RUNTIME_RETENTION_CLEANUP_RUN,
)
_RULE_RECOVERY_DRILL_RUN_WRITE = _capability_rule_key(method=_HTTP_METHOD_POST, path=_PATH_RECOVERY_DRILL_RUN)
_RULE_RUNTIME_STATUS_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RUNTIME_STATUS)
_RULE_RUNTIME_WORK_ITEMS_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RUNTIME_WORK_ITEMS)
_RULE_RUNTIME_RECOVERIES_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RUNTIME_RECOVERIES)
_RULE_RECOVERY_DRILLS_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RECOVERY_DRILLS)
_RULE_RUNTIME_RETENTION_CLEANUPS_READ = _capability_rule_key(
    method=_HTTP_METHOD_GET,
    path=_PATH_RUNTIME_RETENTION_CLEANUPS,
)
_DEFAULT_CAPABILITY_RULES = {
    _RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE: _CAPABILITY_OPERATIONS_RUNTIME_MANAGE,
    _RULE_RECOVERY_DRILL_RUN_WRITE: _CAPABILITY_OPERATIONS_RUNTIME_MANAGE,
}
_DEFAULT_PRIVILEGED_READ_RULES = {
    _RULE_RUNTIME_STATUS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RUNTIME_WORK_ITEMS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RUNTIME_RECOVERIES_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RECOVERY_DRILLS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RUNTIME_RETENTION_CLEANUPS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
}


def _is_write_method(method: str) -> bool:
    return _normalized_http_method(method) in _WRITE_METHODS


def _is_privileged_read_method(method: str) -> bool:
    return _normalized_http_method(method) == _HTTP_METHOD_GET


def _normalized_capability_rule_overrides(configured: dict[str, Any]) -> dict[str, str]:
    rules: dict[str, str] = {}
    for key, value in configured.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        rule_key = key.strip()
        capability = value.strip()
        if rule_key and capability:
            rules[rule_key] = capability
    return rules


def _path_matches_rule(path: str, rule_path: str) -> bool:
    normalized_rule_path = rule_path.rstrip("/") or "/"
    return path == normalized_rule_path or path.startswith(f"{normalized_rule_path}/")


def _capability_rule_path_for_method(*, rule_key: str, method: str) -> str | None:
    prefix = f"{_normalized_http_method(method)}{_CAPABILITY_RULE_METHOD_PATH_SEPARATOR}"
    if not rule_key.upper().startswith(prefix):
        return None
    return rule_key[len(prefix) :]


def _load_capability_rule_family(*, env_name: str, defaults: dict[str, str]) -> dict[str, str]:
    rules = dict(defaults)
    configured = _load_json_map(env_name)
    rules.update(_normalized_capability_rule_overrides(configured))
    return rules


def load_capability_rules() -> dict[str, str]:
    return _load_capability_rule_family(
        env_name=_ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
        defaults=_DEFAULT_CAPABILITY_RULES,
    )


def load_privileged_read_rules() -> dict[str, str]:
    return _load_capability_rule_family(
        env_name=_ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON,
        defaults=_DEFAULT_PRIVILEGED_READ_RULES,
    )


def _required_capability_from_rules(*, method: str, path: str, rules: dict[str, str]) -> str | None:
    for key, capability in rules.items():
        rule_path = _capability_rule_path_for_method(rule_key=key, method=method)
        if rule_path is not None and _path_matches_rule(path, rule_path):
            return capability
    return None


def _required_capability(method: str, path: str) -> str | None:
    return _required_capability_from_rules(method=method, path=path, rules=load_capability_rules())


def _required_privileged_read_capability(method: str, path: str) -> str | None:
    return _required_capability_from_rules(method=method, path=path, rules=load_privileged_read_rules())
