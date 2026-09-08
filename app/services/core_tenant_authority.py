"""The tenant authority governing a computation, or a refusal.

lotus-core made ingress fail-closed on 2026-08-30: every protected route
answers `401 TENANT_CONTEXT_REQUIRED` without a valid `X-Tenant-Id`. This
module is the single place that decides whether this service holds tenant
authority for a Core-bound read, and it is deliberately unable to supply one.

The rule it exists to enforce is that a missing tenant is a refusal, never a
default. A computation that cannot name the tenant it belongs to must not
reach Core at all -- not because the call would fail (it would), but because
a service that can invent a tenant can serve one tenant's data to another.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.errors import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED, APIError

#: Core's admission contract. `X-Actor-Id`, `X-Role` and `X-Service-Identity`
#: are optional there and are not minted here.
TENANT_HEADER = "X-Tenant-Id"
MAX_TENANT_ID_LENGTH = 128


class TenantAuthorityError(APIError):
    """Base for refusals about the caller's admitted tenant.

    Exists so callers can exempt admission outcomes from their own error
    handling by naming one class. Source-retrieval code that rewrites APIErrors
    into data-quality outcomes must let these through: a caller that was refused
    has not been given thin data.
    """


class MissingTenantAuthorityError(TenantAuthorityError):
    """Raised when a Core-bound read has no admitted tenant to travel under.

    This is a refusal, not a failure to look one up. It carries the operation
    so an operator can see which read was refused rather than only that one
    was.

    It also carries its HTTP mapping. Without one it subclassed `RuntimeError`
    and nothing mapped it, so through the real application this refusal reached
    the caller as an unhandled 500: an internal-fault shape for what is a
    caller-authority condition, and retryable-looking to anything that reads
    status classes. `APIError` is this codebase's existing seam for that, and
    `core_api_error_exception_handler` is already registered in `main.py`, so
    the outcome comes from wiring that already exists.

    401 is deliberate: it is what Core answers for the same missing header on
    its own protected routes, so a caller hears one story from both services.
    """

    def __init__(self, operation: str) -> None:
        super().__init__(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=(
                f"No admitted tenant authority for Core read {operation!r}. "
                "The caller's tenant must be carried to Core; this service does not mint or "
                "default one, because a defaulted tenant can return another tenant's data."
            ),
            error_code="TENANT_AUTHORITY_REQUIRED",
            retryable=False,
        )
        self.operation = operation


class MissingStatefulSubmissionTenantAuthorityError(TenantAuthorityError):
    """Raised before a durable stateful job can be accepted without authority."""

    def __init__(self) -> None:
        super().__init__(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=(
                "Stateful async submission requires X-Tenant-Id before durable execution is registered. "
                "This service does not accept a job that cannot perform its authorized Core reads."
            ),
            error_code="TENANT_AUTHORITY_REQUIRED",
            retryable=False,
        )


@dataclass(frozen=True)
class TenantAuthority:
    """A tenant admitted by the caller, carried to Core unchanged.

    Frozen because the authority governing a computation is decided once, at
    admission. Anything that would rewrite it mid-computation is changing whose
    data is being read.
    """

    tenant_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise ValueError(
                "tenant_id must be a non-empty string; a blank tenant is an absent tenant "
                "and must be represented by refusing the read, not by an empty header"
            )
        normalized = self.tenant_id.strip()
        if len(normalized) > MAX_TENANT_ID_LENGTH:
            raise ValueError(f"tenant_id must not exceed {MAX_TENANT_ID_LENGTH} characters")
        object.__setattr__(self, "tenant_id", normalized)

    def headers(self) -> dict[str, str]:
        return {TENANT_HEADER: self.tenant_id}


class MalformedTenantAuthorityError(TenantAuthorityError):
    """The normalized caller tenant exceeds Core's canonical identity bound."""

    def __init__(self) -> None:
        super().__init__(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"X-Tenant-Id must not exceed {MAX_TENANT_ID_LENGTH} characters after trimming.",
            error_code="TENANT_AUTHORITY_MALFORMED",
            retryable=False,
        )


def admitted_tenant_authority(presented: str) -> TenantAuthority | None:
    """Turn the presented header into authority, absence, or a refusal.

    The value is normalized exactly as Core's canonical ``TenantId`` does.
    Absence reaches the Core boundary so the refusal can name the operation;
    an overlong normalized value is refused locally with the published typed
    malformed-authority outcome.
    """

    normalized = presented.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_TENANT_ID_LENGTH:
        raise MalformedTenantAuthorityError()
    return TenantAuthority(tenant_id=normalized)


def require_tenant_authority(authority: TenantAuthority | None, *, operation: str) -> TenantAuthority:
    """Return the authority, or refuse the read.

    Callers pass whatever they hold. This function is the only place that turns
    "nothing" into an error rather than into a request Core will reject -- or
    worse, into a request carrying someone else's tenant.
    """

    if authority is None:
        raise MissingTenantAuthorityError(operation)
    return authority
