"""Tenant-scoped immutable method-input publication, independent of approval."""

from app.ports.composite_model_fees import model_fee_profile_repository
from app.services.composite_materialization.application import (
    admit_materialization_identity,
    admit_materialization_tenant,
)
from core.errors import APIError, APINotFoundError

PROFILE_PATH = "/performance/composites/model-fee-profiles"


def _publication_authority(headers, *, write):
    from app.enterprise_authorization import authorize_required_capability_request

    tenant_id = admit_materialization_tenant(headers.getlist("X-Tenant-Id"))
    actor_id = admit_materialization_identity(headers.getlist("X-Actor-Id"))
    admit_materialization_identity(headers.getlist("X-Role"))
    authority = dict(headers)
    allowed, _ = authorize_required_capability_request("POST" if write else "GET", PROFILE_PATH, authority)
    if not allowed:
        raise APIError(
            status_code=403,
            detail="Model-fee source publication requires admitted durable caller authority.",
            error_code="COMPOSITE_MODEL_FEE_PROFILE_AUTHORITY_REFUSED",
        )
    return tenant_id, actor_id


def publish_profile_input(profile, *, headers):
    tenant_id, actor_id = _publication_authority(headers, write=True)
    return model_fee_profile_repository().publish_model_fee_profile(profile, tenant_id=tenant_id, actor_id=actor_id)


def read_profile_input(profile_id, revision, *, headers):
    tenant_id, _ = _publication_authority(headers, write=False)
    receipt = model_fee_profile_repository().get_model_fee_profile(
        tenant_id=tenant_id, profile_id=profile_id, revision=revision
    )
    if receipt is None:
        raise APINotFoundError("The exact tenant-scoped model-fee profile revision was not found.")
    return receipt
