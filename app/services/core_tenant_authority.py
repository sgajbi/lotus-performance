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

#: Core's admission contract. `X-Actor-Id`, `X-Role` and `X-Service-Identity`
#: are optional there and are not minted here.
TENANT_HEADER = "X-Tenant-Id"


class MissingTenantAuthorityError(RuntimeError):
    """Raised when a Core-bound read has no admitted tenant to travel under.

    This is a refusal, not a failure to look one up. It carries the operation
    so an operator can see which read was refused rather than only that one
    was.
    """

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"No admitted tenant authority for Core read {operation!r}. "
            "The caller's tenant must be carried to Core; this service does not mint or "
            "default one, because a defaulted tenant can return another tenant's data."
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


def require_tenant_authority(authority: TenantAuthority | None, *, operation: str) -> TenantAuthority:
    """Return the authority, or refuse the read.

    Callers pass whatever they hold. This function is the only place that turns
    "nothing" into an error rather than into a request Core will reject -- or
    worse, into a request carrying someone else's tenant.
    """

    if authority is None:
        raise MissingTenantAuthorityError(operation)
    return authority
