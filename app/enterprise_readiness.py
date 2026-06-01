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


def _normalized_header(headers: Mapping[str, str], name: str, default: str = "") -> str:
    value = headers.get(name)
    if value is None:
        return default
    return str(value).strip() or default


def _configured_enterprise_policy_version() -> str:
    return os.getenv("ENTERPRISE_POLICY_VERSION", "1.0.0")


def enterprise_policy_version() -> str:
    return _configured_enterprise_policy_version().strip() or "1.0.0"


def validate_enterprise_runtime_config() -> list[str]:
    issues: list[str] = []
    if not _configured_enterprise_policy_version().strip():
        issues.append("missing_policy_version")

    rotation_days = _env_int("ENTERPRISE_SECRET_ROTATION_DAYS", 90)
    if rotation_days <= 0 or rotation_days > 90:
        issues.append("secret_rotation_days_out_of_range")

    if _env_enabled("ENTERPRISE_ENFORCE_AUTHZ", "false") and not os.getenv("ENTERPRISE_PRIMARY_KEY_ID", "").strip():
        issues.append("missing_primary_key_id")

    if issues and _env_enabled("ENTERPRISE_ENFORCE_RUNTIME_CONFIG", "false"):
        raise RuntimeError(f"enterprise_runtime_config_invalid:{','.join(issues)}")
    return issues


def load_feature_flags() -> dict[str, dict[str, dict[str, bool]]]:
    return _load_json_map("ENTERPRISE_FEATURE_FLAGS_JSON")


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def load_capability_rules() -> dict[str, str]:
    rules = dict(_DEFAULT_CAPABILITY_RULES)
    configured = _load_json_map("ENTERPRISE_CAPABILITY_RULES_JSON")
    rules.update(_normalized_capability_rule_overrides(configured))
    return rules


def load_privileged_read_rules() -> dict[str, str]:
    rules = dict(_DEFAULT_PRIVILEGED_READ_RULES)
    configured = _load_json_map("ENTERPRISE_PRIVILEGED_READ_RULES_JSON")
    rules.update(_normalized_capability_rule_overrides(configured))
    return rules


def is_feature_enabled(feature_key: str, tenant_id: str, role: str) -> bool:
    flags = load_feature_flags()
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


def _required_capability(method: str, path: str) -> str | None:
    method = method.upper()
    for key, capability in load_capability_rules().items():
        prefix = f"{method} "
        if key.upper().startswith(prefix) and _path_matches_rule(path, key[len(prefix) :]):
            return capability
    return None


def _required_privileged_read_capability(method: str, path: str) -> str | None:
    method = method.upper()
    for key, capability in load_privileged_read_rules().items():
        prefix = f"{method} "
        if key.upper().startswith(prefix) and _path_matches_rule(path, key[len(prefix) :]):
            return capability
    return None


def _authorize_with_required_capability(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    required_capability: str | None,
) -> tuple[bool, str | None]:
    normalized = {str(k).lower(): str(v).strip() for k, v in headers.items()}
    missing = sorted(header for header in _REQUIRED_HEADERS if not normalized.get(header))
    if missing:
        return False, f"missing_headers:{','.join(missing)}"

    if not (normalized.get("x-service-identity") or normalized.get("authorization")):
        return False, "missing_service_identity"

    if required_capability:
        capabilities = {part.strip() for part in normalized.get("x-capabilities", "").split(",") if part.strip()}
        if required_capability not in capabilities:
            return False, f"missing_capability:{required_capability}"

    return True, None


def authorize_write_request(method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    if method.upper() not in _WRITE_METHODS or not _env_enabled("ENTERPRISE_ENFORCE_AUTHZ", "false"):
        return True, None

    return _authorize_with_required_capability(
        method=method,
        path=path,
        headers=headers,
        required_capability=_required_capability(method, path),
    )


def authorize_privileged_read_request(method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    if method.upper() != "GET" or not _env_enabled("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "false"):
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


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _REDACT_FIELDS:
                output[key] = "***REDACTED***"
            else:
                output[key] = redact_sensitive(item)
        return output
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


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
            "audit": {
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
        },
    )


def build_enterprise_audit_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    # Enforce enterprise audit and authorization policy on governed surfaces.
    async def middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        max_write_payload_bytes = _env_int("ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES", 1_048_576)
        try:
            content_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            content_length = 0
        if request.method in _WRITE_METHODS and content_length > max_write_payload_bytes:
            return JSONResponse(status_code=413, content={"detail": "payload_too_large"})

        authorized, reason = authorize_write_request(request.method, request.url.path, dict(request.headers))
        if not authorized:
            emit_audit_event(
                action=f"DENY {request.method} {request.url.path}",
                actor_id=_normalized_header(request.headers, "X-Actor-Id", "unknown"),
                tenant_id=_normalized_header(request.headers, "X-Tenant-Id", "default"),
                role=_normalized_header(request.headers, "X-Role", "unknown"),
                correlation_id=_normalized_header(request.headers, "X-Correlation-Id"),
                metadata={"reason": reason},
            )
            return JSONResponse(status_code=403, content={"detail": "authorization_policy_denied", "reason": reason})

        authorized, reason = authorize_privileged_read_request(request.method, request.url.path, dict(request.headers))
        if not authorized:
            emit_audit_event(
                action=f"DENY {request.method} {request.url.path}",
                actor_id=_normalized_header(request.headers, "X-Actor-Id", "unknown"),
                tenant_id=_normalized_header(request.headers, "X-Tenant-Id", "default"),
                role=_normalized_header(request.headers, "X-Role", "unknown"),
                correlation_id=_normalized_header(request.headers, "X-Correlation-Id"),
                metadata={"reason": reason},
            )
            return JSONResponse(status_code=403, content={"detail": "authorization_policy_denied", "reason": reason})

        response = await call_next(request)
        response.headers["X-Enterprise-Policy-Version"] = enterprise_policy_version()
        write_capability = _required_capability(request.method, request.url.path)
        privileged_read_capability = _required_privileged_read_capability(request.method, request.url.path)
        required_capability = privileged_read_capability if request.method.upper() == "GET" else write_capability
        if request.method in _WRITE_METHODS or (
            request.method.upper() == "GET"
            and _env_enabled("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "false")
            and privileged_read_capability is not None
        ):
            emit_audit_event(
                action=f"{request.method} {request.url.path}",
                actor_id=_normalized_header(request.headers, "X-Actor-Id", "unknown"),
                tenant_id=_normalized_header(request.headers, "X-Tenant-Id", "default"),
                role=_normalized_header(request.headers, "X-Role", "unknown"),
                correlation_id=_normalized_header(request.headers, "X-Correlation-Id"),
                metadata={
                    "status_code": response.status_code,
                    "access_mode": "privileged_read" if request.method.upper() == "GET" else "write",
                    "required_capability": required_capability,
                    "governed_surface": request.url.path if required_capability is not None else None,
                },
            )
        return response

    return middleware
