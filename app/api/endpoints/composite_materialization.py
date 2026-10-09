from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request

from app.api.http_response_adapter import to_fastapi_response
from app.models.composite_authority import Identifier
from app.models.composite_materialization import (
    CompositeMaterializationAcceptedResponse,
    CompositeMaterializationCommand,
    CompositeMaterializationProgress,
)
from app.models.composite_model_fee_contract import CompositeModelFeeProfile
from app.models.composite_model_fee_profiles import CompositeModelFeeProfileReceipt
from app.services.composite_materialization.application import (
    admit_materialization_identity,
    admit_materialization_tenant,
    inspect_materialization,
    submit_materialization,
)
from app.services.composite_model_fee_profile_service import publish_profile_input, read_profile_input

router = APIRouter(tags=["Performance"])
_TENANT_PARAMETER = {
    "parameters": [
        {
            "name": "X-Tenant-Id",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "minLength": 1, "maxLength": 128, "example": "private-bank-sg"},
            "description": "Admitted tenant authority; duplicate or missing authority is refused before durable access.",
        }
    ]
}


def _tenant(request: Request) -> str:
    return admit_materialization_tenant(request.headers.getlist("X-Tenant-Id"))


def _identity(request: Request, *, header: str) -> str:
    return admit_materialization_identity(request.headers.getlist(header))


@router.post(
    "/composites/model-fee-profiles",
    response_model=CompositeModelFeeProfileReceipt,
    summary="Retain an immutable unapproved composite model-fee profile",
    description="Preserves canonical method input and original publisher custody. Same-content retry is idempotent; conflicting identity refuses. Publication grants no independent method approval or official activation.",
    openapi_extra=_TENANT_PARAMETER,
)
def publish_model_fee_profile(
    profile: CompositeModelFeeProfile,
    request: Request,
    x_actor_id: Annotated[str, Header(description="Original admitted publishing actor; never defaulted.")],
    x_role: Annotated[str, Header(description="Admitted role subject to publication capability checks.")],
):
    return publish_profile_input(profile, headers=request.headers)


@router.get(
    "/composites/model-fee-profiles/{profile_id}/{revision}",
    response_model=CompositeModelFeeProfileReceipt,
    summary="Read an exact retained composite model-fee profile revision",
    description="Returns original tenant-scoped canonical input and publisher custody by exact identity. Never selects latest or supplies independent approval.",
    openapi_extra=_TENANT_PARAMETER,
)
def read_model_fee_profile(
    profile_id: Identifier,
    revision: Identifier,
    request: Request,
    x_actor_id: Annotated[str, Header(description="Admitted read actor; never defaulted.")],
    x_role: Annotated[str, Header(description="Admitted role subject to privileged read capability checks.")],
):
    return read_profile_input(profile_id, revision, headers=request.headers)


@router.post(
    "/composites/materializations",
    status_code=202,
    response_model=CompositeMaterializationAcceptedResponse,
    summary="Queue governed composite member-fact materialization",
    description=(
        "Pins Manage definition, effective membership and universe attestation plus retained Performance TWR results. "
        "A fresh calculation_id resumes the same immutable materialization; changed content requires a new chronology. "
        "No member calculations or source fan-out run inside interactive composite reads. Trusted headers are not production IdP certification."
    ),
    openapi_extra=_TENANT_PARAMETER,
)
def materialize_composite(
    command: CompositeMaterializationCommand,
    request: Request,
    x_actor_id: Annotated[str, Header(description="Admitted caller actor; never defaulted.")],
    x_role: Annotated[str, Header(description="Admitted caller role forwarded unchanged to Manage.")],
):
    tenant_id = _tenant(request)
    actor_id = _identity(request, header="X-Actor-Id")
    role = _identity(request, header="X-Role")
    return to_fastapi_response(
        submit_materialization(
            command,
            tenant_id=tenant_id,
            actor_id=actor_id,
            role=role,
            request_headers=request.headers,
        )
    )


@router.get(
    "/composites/materializations/{materialization_id}",
    response_model=CompositeMaterializationProgress,
    summary="Inspect durable composite materialization progress",
    description=(
        "Returns a sorted page of ready, excluded, waiting and blocked member outcomes. "
        "Continuation requires the first page's revision; changed progress refuses stale paging. "
        "Only COMPLETE releases immutable facts; executor completion alone does not establish completeness."
    ),
    openapi_extra=_TENANT_PARAMETER,
)
def inspect_composite_materialization(
    materialization_id: UUID,
    request: Request,
    offset: Annotated[int, Query(ge=0, description="Stable member-page offset.")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum returned member outcomes.")] = 100,
    expected_revision: Annotated[
        int | None, Query(ge=0, description="First-page revision, required for every nonzero continuation offset.")
    ] = None,
) -> CompositeMaterializationProgress:
    return inspect_materialization(
        materialization_id, tenant_id=_tenant(request), offset=offset, limit=limit, expected_revision=expected_revision
    )
