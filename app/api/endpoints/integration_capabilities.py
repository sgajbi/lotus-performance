import os
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["Integration"])

ConsumerSystem = Literal["lotus-gateway", "lotus-performance", "lotus-manage", "UI", "UNKNOWN"]


class FeatureCapability(BaseModel):
    key: str = Field(description="Canonical feature key.")
    enabled: bool = Field(description="Whether this feature is enabled.")
    owner_service: str = Field(description="Owning service for this feature.")
    description: str = Field(description="Human-readable capability summary.")


class WorkflowCapability(BaseModel):
    workflow_key: str = Field(description="Workflow key for feature orchestration.")
    enabled: bool = Field(description="Whether workflow is enabled.")
    required_features: list[str] = Field(
        default_factory=list,
        description="Feature keys required for this workflow.",
    )


class IntegrationCapabilitiesResponse(BaseModel):
    contract_version: str
    source_service: str
    consumer_system: ConsumerSystem
    tenant_id: str
    generated_at: datetime
    as_of_date: date
    policy_version: str
    supported_input_modes: list[str] = Field(
        description="Supported execution input modes: stateful and stateless.",
    )
    features: list[FeatureCapability]
    workflows: list[WorkflowCapability]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@router.get(
    "/capabilities",
    response_model=IntegrationCapabilitiesResponse,
    summary="Get lotus-performance Integration Capabilities",
    description=(
        "Returns backend-governed lotus-performance capability/workflow controls for lotus-gateway, lotus-core, and lotus-manage integration."
    ),
)
async def get_integration_capabilities(
    consumer_system: ConsumerSystem = Query("lotus-gateway"),
    tenant_id: str = Query("default"),
    feature_limit: int = Query(default=100, ge=1, le=500),
    workflow_limit: int = Query(default=50, ge=1, le=200),
) -> IntegrationCapabilitiesResponse:
    twr_enabled = _env_bool("PA_CAP_TWR_ENABLED", True)
    mwr_enabled = _env_bool("PA_CAP_MWR_ENABLED", True)
    contribution_enabled = _env_bool("PA_CAP_CONTRIBUTION_ENABLED", True)
    attribution_enabled = _env_bool("PA_CAP_ATTRIBUTION_ENABLED", True)
    stateful_mode_enabled = _env_bool("PLATFORM_INPUT_MODE_STATEFUL_ENABLED", True)
    stateless_mode_enabled = _env_bool("PLATFORM_INPUT_MODE_STATELESS_ENABLED", True)

    features = [
        FeatureCapability(
            key="pa.analytics.twr",
            enabled=twr_enabled,
            owner_service="lotus-performance",
            description="Time-weighted return analytics APIs.",
        ),
        FeatureCapability(
            key="pa.analytics.mwr",
            enabled=mwr_enabled,
            owner_service="lotus-performance",
            description="Money-weighted return analytics APIs.",
        ),
        FeatureCapability(
            key="pa.analytics.contribution",
            enabled=contribution_enabled,
            owner_service="lotus-performance",
            description="Contribution analytics APIs.",
        ),
        FeatureCapability(
            key="pa.analytics.attribution",
            enabled=attribution_enabled,
            owner_service="lotus-performance",
            description="Attribution analytics APIs.",
        ),
        FeatureCapability(
            key="pa.execution.stateful",
            enabled=stateful_mode_enabled,
            owner_service="lotus-performance",
            description="lotus-performance executes using platform-managed stateful input retrieval.",
        ),
        FeatureCapability(
            key="pa.execution.stateless",
            enabled=stateless_mode_enabled,
            owner_service="lotus-performance",
            description="lotus-performance executes analytics from request-supplied stateless input data.",
        ),
    ]

    workflows = [
        WorkflowCapability(
            workflow_key="performance_snapshot",
            enabled=twr_enabled and mwr_enabled,
            required_features=["pa.analytics.twr", "pa.analytics.mwr"],
        ),
        WorkflowCapability(
            workflow_key="performance_explainability",
            enabled=contribution_enabled and attribution_enabled,
            required_features=["pa.analytics.contribution", "pa.analytics.attribution"],
        ),
        WorkflowCapability(
            workflow_key="execution_stateful",
            enabled=stateful_mode_enabled,
            required_features=["pa.execution.stateful"],
        ),
        WorkflowCapability(
            workflow_key="execution_stateless",
            enabled=stateless_mode_enabled,
            required_features=["pa.execution.stateless"],
        ),
    ]

    supported_input_modes: list[str] = []
    if stateful_mode_enabled:
        supported_input_modes.append("stateful")
    if stateless_mode_enabled:
        supported_input_modes.append("stateless")

    return IntegrationCapabilitiesResponse(
        contract_version="v1",
        source_service="lotus-performance",
        consumer_system=consumer_system,
        tenant_id=tenant_id,
        generated_at=datetime.now(UTC),
        as_of_date=date.today(),
        policy_version=os.getenv("PA_POLICY_VERSION", "tenant-default-v1"),
        supported_input_modes=supported_input_modes,
        features=features[:feature_limit],
        workflows=workflows[:workflow_limit],
    )
