"""Server-owned authority composition; callers cannot configure financial trust."""

from fastapi import Request

from app.adapters.composite_result_authority.context import require_principal
from app.adapters.composite_result_authority.repository import CompositeAuthorityRepository
from app.composite_principal_admission import trusted_request_principal
from app.ports.composite_result_authority import UnavailableFinancialAuthority
from app.services.async_result_store import get_async_result_store
from app.services.composite_metadata_store import get_composite_metadata_store
from app.services.composite_result_authority.application import CompositeAuthorityApplication


def authority_application(request: Request) -> CompositeAuthorityApplication:
    return CompositeAuthorityApplication(
        CompositeAuthorityRepository(get_composite_metadata_store(), get_async_result_store()),
        getattr(request.app.state, "composite_financial_authority", UnavailableFinancialAuthority()),
    )


def authority_principal(request: Request):
    principal = trusted_request_principal(request)
    require_principal(principal, write=request.method not in {"GET", "HEAD"})
    return principal
