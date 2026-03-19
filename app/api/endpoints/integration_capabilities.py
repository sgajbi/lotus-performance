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


class AnalyticsSurfaceCapability(BaseModel):
    key: str = Field(description="Canonical analytics surface key.")
    path: str = Field(description="HTTP path for this analytics surface.")
    enabled: bool = Field(description="Whether this analytics surface is enabled.")
    supported_input_modes: list[str] = Field(
        default_factory=list,
        description="Supported execution input modes for this specific analytics surface.",
    )
    supports_async: bool = Field(description="Whether this analytics surface can return 202 async accepted responses.")
    stateful_restrictions: list[str] = Field(
        default_factory=list,
        description="Current stateful-mode fences or restrictions for this analytics surface.",
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
    analytics_surfaces: list[AnalyticsSurfaceCapability] = Field(
        default_factory=list,
        description="Endpoint-level analytics capability details for downstream service integration.",
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
    benchmark_enabled = _env_bool("PA_CAP_BENCHMARK_ENABLED", True)
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
            key="pa.analytics.benchmark",
            enabled=benchmark_enabled,
            owner_service="lotus-performance",
            description="Benchmark performance analytics APIs.",
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
            enabled=twr_enabled and mwr_enabled and benchmark_enabled,
            required_features=["pa.analytics.twr", "pa.analytics.mwr", "pa.analytics.benchmark"],
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

    analytics_surfaces = [
        AnalyticsSurfaceCapability(
            key="twr",
            path="/performance/twr",
            enabled=twr_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=False,
        ),
        AnalyticsSurfaceCapability(
            key="mwr",
            path="/performance/mwr",
            enabled=mwr_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=False,
        ),
        AnalyticsSurfaceCapability(
            key="benchmark",
            path="/performance/benchmark",
            enabled=benchmark_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=False,
        ),
        AnalyticsSurfaceCapability(
            key="contribution",
            path="/performance/contribution",
            enabled=contribution_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=True,
        ),
        AnalyticsSurfaceCapability(
            key="attribution",
            path="/performance/attribution",
            enabled=attribution_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=True,
            stateful_restrictions=(
                [
                    "mode=by_instrument only",
                    "group_by limited to asset_class, sector, country, currency",
                    "currency_mode=BOTH requires report_ccy and fx.rates for mixed-currency positions",
                ]
                if stateful_mode_enabled and attribution_enabled
                else []
            ),
        ),
        AnalyticsSurfaceCapability(
            key="returns_series",
            path="/integration/returns/series",
            enabled=stateful_mode_enabled or stateless_mode_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=True,
        ),
    ]

    return IntegrationCapabilitiesResponse(
        contract_version="v1",
        source_service="lotus-performance",
        consumer_system=consumer_system,
        tenant_id=tenant_id,
        generated_at=datetime.now(UTC),
        as_of_date=date.today(),
        policy_version=os.getenv("PA_POLICY_VERSION", "tenant-default-v1"),
        supported_input_modes=supported_input_modes,
        analytics_surfaces=analytics_surfaces,
        features=features[:feature_limit],
        workflows=workflows[:workflow_limit],
    )
