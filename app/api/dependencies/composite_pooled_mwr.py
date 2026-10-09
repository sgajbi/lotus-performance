"""Reuse the outer verified outcome; public headers cannot mint pooled authority."""

from fastapi import Request

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.composite_principal_admission import trusted_request_principal
from core.errors import APIError


def require_pooled_principal(request: Request, *, tenant_id: str) -> VerifiedCompositePrincipal:
    principal = trusted_request_principal(request)
    if principal is None:
        raise APIError(
            status_code=403,
            detail="Verified principal is required.",
            error_code="PRINCIPAL_ADMISSION_DENIED",
        )
    if principal.tenant_id != tenant_id:
        raise APIError(
            status_code=403,
            detail="Principal tenant differs from admitted tenant.",
            error_code="PRINCIPAL_ADMISSION_DENIED",
        )
    return principal
