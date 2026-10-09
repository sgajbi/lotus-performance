"""Application admission before reading retained numerical inputs."""

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_candidate_scope import require_candidate_member_scope
from app.adapters.composite_result_candidate_storage import require_release_build, require_same_result_database
from app.services.async_result_store import get_async_result_store
from app.services.composite_metadata_store import get_composite_metadata_store
from core.errors import APIError


def admit_candidate_calculation(request, principal):
    require_release_build()
    store, results = get_composite_metadata_store(), get_async_result_store()
    require_same_result_database(store, results)
    require_candidate_member_scope(store, request=request, principal=principal)
    return store, results


def require_verified_candidate_principal(principal):
    if not isinstance(principal, VerifiedCompositePrincipal):
        raise APIError(
            status_code=403, detail="Verified principal is required.", error_code="PRINCIPAL_ADMISSION_DENIED"
        )
    return principal


def read_result_candidate(candidate_id, principal):
    retained = get_composite_metadata_store().get_result_candidate(
        candidate_id=candidate_id,
        tenant_id=principal.tenant_id,
        result_store=get_async_result_store(),
        principal=principal,
    )
    if retained is None:
        raise APIError(
            status_code=404,
            detail="Candidate is absent in the verified tenant.",
            error_code="COMPOSITE_RESULT_CANDIDATE_NOT_FOUND",
        )
    return retained
