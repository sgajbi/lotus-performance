import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("enterprise_readiness")

_SERVICE_NAME = "lotus-performance"
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_REQUIRED_HEADERS = {"x-actor-id", "x-tenant-id", "x-role", "x-correlation-id"}
_DEFAULT_CAPABILITY_RULES = {
    "POST /integration/runtime-retention-cleanups/run": "operations.runtime.manage",
    "POST /integration/recovery-drills/run": "operations.runtime.manage",
}
_DEFAULT_PRIVILEGED_READ_RULES = {
    "GET /integration/runtime-status": "operations.runtime.read",
    "GET /integration/runtime-work-items": "operations.runtime.read",
    "GET /integration/runtime-recoveries": "operations.runtime.read",
    "GET /integration/recovery-drills": "operations.runtime.read",
    "GET /integration/runtime-retention-cleanups": "operations.runtime.read",
}
_REDACT_FIELDS = {
    "password",
    "secret",
    "token",
    "authorization",
    "ssn",
    "account_number",
    "client_email",
}


def _is_write_method(method: str) -> bool:
    return method.upper() in _WRITE_METHODS


def _is_privileged_read_method(method: str) -> bool:
    return method.upper() == "GET"


def _env_enabled(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _load_json_map(name: str) -> dict[str, Any]:
    raw = os.getenv(name, "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _configured_enterprise_policy_version() -> str:
    return os.getenv("ENTERPRISE_POLICY_VERSION", "1.0.0")


def enterprise_policy_version() -> str:
    return _configured_enterprise_policy_version().strip() or "1.0.0"


def _enterprise_runtime_config_issues() -> list[str]:
    issues: list[str] = []
    if not _configured_enterprise_policy_version().strip():
        issues.append("missing_policy_version")

    rotation_days = _env_int("ENTERPRISE_SECRET_ROTATION_DAYS", 90)
    if rotation_days <= 0 or rotation_days > 90:
        issues.append("secret_rotation_days_out_of_range")

    if _env_enabled("ENTERPRISE_ENFORCE_AUTHZ", "false") and not os.getenv("ENTERPRISE_PRIMARY_KEY_ID", "").strip():
        issues.append("missing_primary_key_id")

    return issues


def validate_enterprise_runtime_config() -> list[str]:
    issues = _enterprise_runtime_config_issues()
    if issues and _env_enabled("ENTERPRISE_ENFORCE_RUNTIME_CONFIG", "false"):
        raise RuntimeError(f"enterprise_runtime_config_invalid:{','.join(issues)}")
    return issues


def load_feature_flags() -> dict[str, dict[str, dict[str, bool]]]:
    return _load_json_map("ENTERPRISE_FEATURE_FLAGS_JSON")


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


def _load_capability_rule_family(*, env_name: str, defaults: dict[str, str]) -> dict[str, str]:
    rules = dict(defaults)
    configured = _load_json_map(env_name)
    rules.update(_normalized_capability_rule_overrides(configured))
    return rules


def load_capability_rules() -> dict[str, str]:
    return _load_capability_rule_family(
        env_name="ENTERPRISE_CAPABILITY_RULES_JSON",
        defaults=_DEFAULT_CAPABILITY_RULES,
    )


def load_privileged_read_rules() -> dict[str, str]:
    return _load_capability_rule_family(
        env_name="ENTERPRISE_PRIVILEGED_READ_RULES_JSON",
        defaults=_DEFAULT_PRIVILEGED_READ_RULES,
    )


def is_feature_enabled(feature_key: str, tenant_id: str, role: str) -> bool:
    return _feature_flag_enabled(
        flags=load_feature_flags(),
        feature_key=feature_key,
        tenant_id=tenant_id,
        role=role,
    )


def _required_capability_from_rules(*, method: str, path: str, rules: dict[str, str]) -> str | None:
    method = method.upper()
    for key, capability in rules.items():
        prefix = f"{method} "
        if key.upper().startswith(prefix) and _path_matches_rule(path, key[len(prefix) :]):
            return capability
    return None


def _required_capability(method: str, path: str) -> str | None:
    return _required_capability_from_rules(method=method, path=path, rules=load_capability_rules())


def _required_privileged_read_capability(method: str, path: str) -> str | None:
    return _required_capability_from_rules(method=method, path=path, rules=load_privileged_read_rules())


def _normalized_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(value).strip() for key, value in headers.items()}


def _header_capabilities(normalized_headers: Mapping[str, str]) -> set[str]:
    return {part.strip() for part in normalized_headers.get("x-capabilities", "").split(",") if part.strip()}


def _has_required_capability(normalized_headers: Mapping[str, str], required_capability: str | None) -> bool:
    return required_capability is None or required_capability in _header_capabilities(normalized_headers)


def _missing_required_headers(normalized_headers: Mapping[str, str]) -> list[str]:
    return sorted(header for header in _REQUIRED_HEADERS if not normalized_headers.get(header))


def _has_service_identity(normalized_headers: Mapping[str, str]) -> bool:
    return bool(normalized_headers.get("x-service-identity") or normalized_headers.get("authorization"))


def _audit_identity_from_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    normalized = _normalized_headers(headers)
    return {
        "actor_id": normalized.get("x-actor-id") or "unknown",
        "tenant_id": normalized.get("x-tenant-id") or "default",
        "role": normalized.get("x-role") or "unknown",
        "correlation_id": normalized.get("x-correlation-id", ""),
    }


def _allowed_audit_metadata(*, method: str, path: str, status_code: int) -> dict[str, Any] | None:
    write_capability = _required_capability(method, path)
    privileged_read_capability = _required_privileged_read_capability(method, path)
    is_privileged_read = _is_privileged_read_method(method)
    required_capability = privileged_read_capability if is_privileged_read else write_capability
    if not _is_write_method(method) and not (
        is_privileged_read
        and _env_enabled("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "false")
        and privileged_read_capability is not None
    ):
        return None
    return {
        "status_code": status_code,
        "access_mode": "privileged_read" if is_privileged_read else "write",
        "required_capability": required_capability,
        "governed_surface": path if required_capability is not None else None,
    }


def _authorization_denied_response(
    *,
    method: str,
    path: str,
    reason: str | None,
    audit_identity: dict[str, str],
) -> JSONResponse:
    emit_audit_event(
        action=f"DENY {method} {path}",
        **audit_identity,
        metadata={"reason": reason},
    )
    return JSONResponse(status_code=403, content={"detail": "authorization_policy_denied", "reason": reason})


def _emit_allowed_audit_event(
    *,
    method: str,
    path: str,
    audit_identity: dict[str, str],
    metadata: dict[str, Any],
) -> None:
    emit_audit_event(
        action=f"{method} {path}",
        **audit_identity,
        metadata=metadata,
    )


def _content_length(headers: Mapping[str, Any]) -> int:
    try:
        return int(headers.get("content-length", "0"))
    except (TypeError, ValueError):
        return 0


def _write_payload_too_large(
    *,
    method: str,
    headers: Mapping[str, Any],
    max_write_payload_bytes: int,
) -> bool:
    return _is_write_method(method) and _content_length(headers) > max_write_payload_bytes


def _authorize_with_required_capability(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    required_capability: str | None,
) -> tuple[bool, str | None]:
    normalized = _normalized_headers(headers)
    missing = _missing_required_headers(normalized)
    if missing:
        return False, f"missing_headers:{','.join(missing)}"

    if not _has_service_identity(normalized):
        return False, "missing_service_identity"

    if not _has_required_capability(normalized, required_capability):
        return False, f"missing_capability:{required_capability}"

    return True, None


def authorize_write_request(method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    if not _is_write_method(method) or not _env_enabled("ENTERPRISE_ENFORCE_AUTHZ", "false"):
        return True, None

    return _authorize_with_required_capability(
        method=method,
        path=path,
        headers=headers,
        required_capability=_required_capability(method, path),
    )


def authorize_privileged_read_request(method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    if not _is_privileged_read_method(method) or not _env_enabled("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "false"):
        return True, None

    required_capability = _required_privileged_read_capability(method, path)
    if required_capability is None:
        return True, None

    return _authorize_with_required_capability(
        method=method,
        path=path,
        headers=headers,
        required_capability=required_capability,
    )


def _authorize_enterprise_request(*, method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    authorized, reason = authorize_write_request(method, path, headers)
    if not authorized:
        return authorized, reason
    return authorize_privileged_read_request(method, path, headers)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _REDACT_FIELDS:
                output[key] = "***REDACTED***"
            else:
                output[key] = redact_sensitive(item)
        return output
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def _audit_event_payload(
    *,
    action: str,
    actor_id: str,
    tenant_id: str,
    role: str,
    correlation_id: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "service": _SERVICE_NAME,
        "action": action,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "role": role,
        "correlation_id": correlation_id or "",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "policy_version": enterprise_policy_version(),
        "metadata": redact_sensitive(metadata),
    }


def _apply_enterprise_policy_header(response: Response) -> Response:
    response.headers["X-Enterprise-Policy-Version"] = enterprise_policy_version()
    return response


def emit_audit_event(
    *,
    action: str,
    actor_id: str,
    tenant_id: str,
    role: str,
    correlation_id: str | None,
    metadata: dict[str, Any],
) -> None:
    logger.info(
        "enterprise_audit_event",
        extra={
            "audit": _audit_event_payload(
                action=action,
                actor_id=actor_id,
                tenant_id=tenant_id,
                role=role,
                correlation_id=correlation_id,
                metadata=metadata,
            )
        },
    )


def build_enterprise_audit_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    # Enforce enterprise audit and authorization policy on governed surfaces.
    async def middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        max_write_payload_bytes = _env_int("ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES", 1_048_576)
        if _write_payload_too_large(
            method=request.method,
            headers=request.headers,
            max_write_payload_bytes=max_write_payload_bytes,
        ):
            return JSONResponse(status_code=413, content={"detail": "payload_too_large"})

        audit_identity = _audit_identity_from_headers(request.headers)
        authorized, reason = _authorize_enterprise_request(
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
        )
        if not authorized:
            return _authorization_denied_response(
                method=request.method,
                path=request.url.path,
                reason=reason,
                audit_identity=audit_identity,
            )

        response = await call_next(request)
        _apply_enterprise_policy_header(response)
        allowed_audit_metadata = _allowed_audit_metadata(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        if allowed_audit_metadata is not None:
            _emit_allowed_audit_event(
                method=request.method,
                path=request.url.path,
                audit_identity=audit_identity,
                metadata=allowed_audit_metadata,
            )
        return response

    return middleware
