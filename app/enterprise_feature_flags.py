from typing import Any

from app.enterprise_runtime_config import _ENV_ENTERPRISE_FEATURE_FLAGS_JSON, _load_json_map


def load_feature_flags() -> dict[str, dict[str, dict[str, bool]]]:
    return _load_json_map(_ENV_ENTERPRISE_FEATURE_FLAGS_JSON)


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _feature_flag_enabled(
    *,
    flags: dict[str, Any],
    feature_key: str,
    tenant_id: str,
    role: str,
) -> bool:
    feature = _dict_value(flags.get(feature_key))
    tenant = _dict_value(feature.get(tenant_id))
    value = tenant.get(role)
    if isinstance(value, bool):
        return value
    fallback = tenant.get("*")
    if isinstance(fallback, bool):
        return fallback
    global_default = _dict_value(feature.get("*")).get("*")
    return bool(global_default) if isinstance(global_default, bool) else False


def is_feature_enabled(feature_key: str, tenant_id: str, role: str) -> bool:
    return _feature_flag_enabled(
        flags=load_feature_flags(),
        feature_key=feature_key,
        tenant_id=tenant_id,
        role=role,
    )
