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
        if self.tenant_id != self.tenant_id.strip():
            raise ValueError(
                f"tenant_id {self.tenant_id!r} has surrounding whitespace; Core compares the "
                "header exactly, so a padded value is a different tenant to it"
            )

    def headers(self) -> dict[str, str]:
        return {TENANT_HEADER: self.tenant_id}


class PaddedTenantAuthorityError(TenantAuthorityError):
    """The caller presented a tenant we must neither use nor quietly repair.

    Core compares `X-Tenant-Id` exactly, so `"tenant-a "` and `"tenant-a"` are
    different tenants to it. Trimming would substitute a tenant the caller did
    not present, which is the one thing this module exists to prevent; refusing
    tells the caller their header is malformed and leaves the choice with them.

    400 rather than 401: the caller did present authority, and the problem is
    the shape of what they sent.
    """

    def __init__(self, presented: str) -> None:
        super().__init__(
            status_code=HTTP_400_BAD_REQUEST,
            detail=(
                f"X-Tenant-Id {presented!r} has surrounding whitespace. Core compares the "
                "header exactly, so a padded value names a different tenant; this service "
                "refuses rather than trimming, because trimming would read as a tenant the "
                "caller did not present."
            ),
            error_code="TENANT_AUTHORITY_MALFORMED",
            retryable=False,
        )
        self.presented = presented


def admitted_tenant_authority(presented: str) -> TenantAuthority | None:
    """Turn the presented header into authority, absence, or a refusal.

    The three cases are decided here rather than left to fall through, because
    each has a different correct outcome: absence must reach the Core boundary
    so the refusal can name the operation, padding must be refused before any
    read, and only an exact value becomes authority.
    """

    if not presented.strip():
        return None
    if presented != presented.strip():
        raise PaddedTenantAuthorityError(presented)
    return TenantAuthority(tenant_id=presented)


def require_tenant_authority(authority: TenantAuthority | None, *, operation: str) -> TenantAuthority:
    """Return the authority, or refuse the read.

    Callers pass whatever they hold. This function is the only place that turns
    "nothing" into an error rather than into a request Core will reject -- or
    worse, into a request carrying someone else's tenant.
    """

    if authority is None:
        raise MissingTenantAuthorityError(operation)
    return authority
