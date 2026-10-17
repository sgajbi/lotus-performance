"""Opt-in operator authority for Core's enterprise HMAC context v1.

This is service execution authority, independent of the original caller. It
does not authorize financial sources, source cuts, or institutional use.
"""

from __future__ import annotations

import hashlib
import hmac
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.services.core_tenant_authority import TenantAuthority, TenantAuthorityError


class CoreExecutionScopeDenied(TenantAuthorityError):
    def __init__(self) -> None:
        super().__init__(
            status_code=403,
            detail="Admitted tenant is outside configured Core service execution scope.",
            error_code="CORE_EXECUTION_SCOPE_DENIED",
            retryable=False,
        )


class MalformedCoreRequestContext(TenantAuthorityError):
    """Propagated metadata cannot enter Core's bounded signed context."""

    def __init__(self) -> None:
        super().__init__(
            status_code=400,
            detail="Core request context requires a nonblank correlation id of at most 128 printable ASCII characters.",
            error_code="CORE_REQUEST_CONTEXT_MALFORMED",
            retryable=False,
        )


def _bounded_context_value(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 128 or any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise ValueError("Core context requires nonblank bounded ASCII header values")
    return value


def _exact_scope_value(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Core context allowlist values must be text")
    value = _bounded_context_value(value)
    if "*" in value or "," in value:
        raise ValueError("Core context allowlists require exact values without wildcards or commas")
    return value


def _core_correlation_value(value: str) -> str:
    try:
        return _bounded_context_value(value)
    except ValueError:
        raise MalformedCoreRequestContext() from None


class CoreRequestContextAuthority(BaseModel):
    """Frozen explicit service identity and exact operator grants; never caller claims."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    service_identity: str
    key_id: str
    secret: SecretStr = Field(repr=False, exclude=True)
    actor_id: str
    role: str
    tenants: frozenset[str]
    capabilities: frozenset[str]

    @field_validator("service_identity", "key_id", "actor_id", "role")
    @classmethod
    def bounded_identity(cls, value: str) -> str:
        value = _bounded_context_value(value)
        if "*" in value:
            raise ValueError("Core service execution identity must be exact")
        return value

    @field_validator("secret")
    @classmethod
    def nonblank_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Core context requires an explicit nonblank HMAC secret")
        # Native Core trims the configured secret before verification.
        return SecretStr(value.get_secret_value().strip())

    @field_validator("tenants", "capabilities", mode="before")
    @classmethod
    def exact_allowlist(cls, values: object) -> frozenset[str]:
        if not isinstance(values, (list, tuple, set, frozenset)) or not values:
            raise ValueError("Core context requires a nonempty exact allowlist")
        normalized = list(map(_exact_scope_value, values))
        if len(set(normalized)) != len(normalized):
            raise ValueError("Core context allowlists require unique exact values")
        return frozenset(normalized)

    def signed_headers(self, *, tenant: TenantAuthority, propagation: dict[str, str]) -> dict[str, str]:
        if tenant.tenant_id not in self.tenants:
            raise CoreExecutionScopeDenied()
        # Build a private final map, replacing any untrusted authority fields.
        headers = {
            key.lower(): value.strip()
            for key, value in propagation.items()
            if key.lower() in {"x-correlation-id", "x-request-id", "x-trace-id", "traceparent"}
        }
        headers.update(
            {
                "x-enterprise-auth-key-id": self.key_id,
                "x-service-identity": self.service_identity,
                "x-actor-id": self.actor_id,
                "x-tenant-id": tenant.tenant_id,
                "x-role": self.role,
                "x-correlation-id": _core_correlation_value(headers.get("x-correlation-id", "")),
                "x-enterprise-auth-timestamp": str(int(time.time())),
                "x-capabilities": ",".join(sorted(self.capabilities)),
            }
        )
        canonical = "\n".join(
            [
                "lotus-enterprise-auth-context-v1",
                *(
                    headers[name]
                    for name in (
                        "x-enterprise-auth-key-id",
                        "x-service-identity",
                        "x-actor-id",
                        "x-tenant-id",
                        "x-role",
                        "x-correlation-id",
                        "x-enterprise-auth-timestamp",
                        "x-capabilities",
                    )
                ),
            ]
        )
        headers["x-enterprise-auth-signature"] = hmac.new(
            self.secret.get_secret_value().encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return headers

    @staticmethod
    def isolate_request(request: httpx.Request, *, signed_headers: dict[str, str]) -> None:
        """Admit only framing and this logical call's context after pool merges."""
        framing = {"host", "content-length", "content-type", "transfer-encoding", "accept-encoding"}
        for name in list(request.headers):
            if name not in framing:
                del request.headers[name]
        request.headers.update(signed_headers)
