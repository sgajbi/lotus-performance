import os
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["Integration"])

ConsumerSystem = Literal["lotus-gateway", "lotus-performance", "lotus-manage", "UI", "UNKNOWN"]

INTEGRATION_CAPABILITIES_RESPONSE_EXAMPLES = [
    {
        "contract_version": "v1",
        "source_service": "lotus-performance",
        "consumer_system": "lotus-gateway",
        "tenant_id": "default",
        "generated_at": "2026-03-27T12:00:00Z",
        "as_of_date": "2026-03-27",
        "policy_version": "tenant-default-v1",
        "supported_input_modes": ["stateful", "stateless"],
        "analytics_surfaces": [
            {
                "key": "workspace_summary",
                "path": "/performance/workspace-summary",
                "enabled": True,
                "supported_input_modes": ["stateful", "stateless"],
                "supports_async": True,
                "poll_path_template": "/performance/executions/{calculation_id}",
                "result_path_template": "/performance/workspace-summary/results/{calculation_id}",
                "stateful_restrictions": [],
                "contract_notes": [
                    "supports multi-horizon workspace periods including 1D, 2D, 5D, 10D, 1M, 3M, 6M, YTD, 1Y, 2Y, 5Y, 10Y, SI, and EXPLICIT",
                    "summary and breakdown rows emit period_return, cumulative_return, and annualized_return; for periods up to one year annualized_return equals cumulative_return",
                    "resolves the longest requested window once and derives shorter requested periods from the same sourced data",
                ],
                "options": [
                    {
                        "key": "benchmark_mode",
                        "supported_values": ["user_input_stateless", "linked_stateful"],
                        "required_when": "benchmark or benchmark-aware blocks are requested",
                        "notes": [
                            "stateless workspace summary requires an explicit benchmark payload when include_benchmark=true",
                            "stateful workspace summary can resolve the linked benchmark from lotus-core assignment",
                        ],
                    },
                ],
            }
        ],
        "features": [
            {
                "key": "pa.analytics.workspace_summary",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Interaction-efficient workspace summary analytics API.",
            }
        ],
        "workflows": [
            {
                "workflow_key": "performance_workspace",
                "enabled": True,
                "required_features": ["pa.analytics.workspace_summary", "pa.analytics.twr", "pa.analytics.mwr"],
            }
        ],
    }
]


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


class AnalyticsSurfaceOptionCapability(BaseModel):
    key: str = Field(description="Canonical request-option key for this analytics surface.")
    supported_values: list[str] = Field(
        default_factory=list,
        description="Supported values or named options for this request capability.",
    )
    required_when: str | None = Field(
        default=None,
        description="Condition under which this option or companion input becomes required.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional contract notes for this request option.",
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
    poll_path_template: str | None = Field(
        default=None,
        description="Execution polling path template for async-capable surfaces.",
    )
    result_path_template: str | None = Field(
        default=None,
        description="Endpoint-specific async result path template for async-capable surfaces.",
    )
    stateful_restrictions: list[str] = Field(
        default_factory=list,
        description="Current stateful-mode fences or restrictions for this analytics surface.",
    )
    contract_notes: list[str] = Field(
        default_factory=list,
        description="Surface-specific contract notes that downstream consumers should treat as part of the supported behavior.",
    )
    options: list[AnalyticsSurfaceOptionCapability] = Field(
        default_factory=list,
        description="Machine-readable request-option capabilities for this analytics surface.",
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

    model_config = {
        "json_schema_extra": {"examples": INTEGRATION_CAPABILITIES_RESPONSE_EXAMPLES},
    }


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
    workspace_summary_enabled = _env_bool("PA_CAP_WORKSPACE_SUMMARY_ENABLED", True)
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
            key="pa.integration.benchmark_exposure_context",
            enabled=benchmark_enabled and stateful_mode_enabled,
            owner_service="lotus-performance",
            description="Performance-aligned benchmark exposure context derived from lotus-core benchmark lineage.",
        ),
        FeatureCapability(
            key="pa.analytics.workspace_summary",
            enabled=workspace_summary_enabled,
            owner_service="lotus-performance",
            description="Interaction-efficient workspace summary analytics API.",
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
            workflow_key="performance_workspace",
            enabled=workspace_summary_enabled and twr_enabled and mwr_enabled,
            required_features=["pa.analytics.workspace_summary", "pa.analytics.twr", "pa.analytics.mwr"],
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
            supports_async=True,
            poll_path_template="/performance/executions/{calculation_id}",
            result_path_template="/performance/twr/results/{calculation_id}",
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
            supports_async=True,
            poll_path_template="/performance/executions/{calculation_id}",
            result_path_template="/performance/benchmark/results/{calculation_id}",
        ),
        AnalyticsSurfaceCapability(
            key="workspace_summary",
            path="/performance/workspace-summary",
            enabled=workspace_summary_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=True,
            poll_path_template="/performance/executions/{calculation_id}",
            result_path_template="/performance/workspace-summary/results/{calculation_id}",
            stateful_restrictions=[],
            contract_notes=(
                [
                    "supports multi-horizon workspace periods including 1D, 2D, 5D, 10D, 1M, 3M, 6M, YTD, 1Y, 2Y, 5Y, 10Y, SI, and EXPLICIT",
                    "summary and breakdown rows emit period_return, cumulative_return, and annualized_return; for periods up to one year annualized_return equals cumulative_return",
                    "resolves the longest requested window once and derives shorter requested periods from the same sourced data",
                ]
                if workspace_summary_enabled
                else []
            ),
            options=(
                [
                    AnalyticsSurfaceOptionCapability(
                        key="benchmark_mode",
                        supported_values=["user_input_stateless", "linked_stateful"],
                        required_when="benchmark or benchmark-aware blocks are requested",
                        notes=[
                            "stateless workspace summary requires an explicit benchmark payload when include_benchmark=true",
                            "stateful workspace summary can resolve the linked benchmark from lotus-core assignment",
                        ],
                    ),
                ]
                if workspace_summary_enabled
                else []
            ),
        ),
        AnalyticsSurfaceCapability(
            key="contribution",
            path="/performance/contribution",
            enabled=contribution_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=True,
            poll_path_template="/performance/executions/{calculation_id}",
            result_path_template="/performance/contribution/results/{calculation_id}",
        ),
        AnalyticsSurfaceCapability(
            key="attribution",
            path="/performance/attribution",
            enabled=attribution_enabled,
            supported_input_modes=supported_input_modes,
            supports_async=True,
            poll_path_template="/performance/executions/{calculation_id}",
            result_path_template="/performance/attribution/results/{calculation_id}",
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
            poll_path_template="/performance/executions/{calculation_id}",
            result_path_template="/integration/returns/series/results/{calculation_id}",
        ),
        AnalyticsSurfaceCapability(
            key="benchmark_exposure_context",
            path="/integration/benchmarks/exposure-context",
            enabled=benchmark_enabled and stateful_mode_enabled,
            supported_input_modes=["stateful"] if stateful_mode_enabled else [],
            supports_async=False,
            stateful_restrictions=(
                [
                    "lotus-core remains the benchmark composition system of record",
                    "POSITION, SECTOR, and ASSET_CLASS grouping dimensions are supported",
                    "ISSUER remains gated until benchmark issuer exposure semantics are approved",
                ]
                if benchmark_enabled and stateful_mode_enabled
                else []
            ),
            contract_notes=(
                [
                    "returns a lineage-backed benchmark exposure view aligned to benchmark performance context",
                    "intended for lotus-risk stateful ACTIVE_RISK attribution integration",
                ]
                if benchmark_enabled and stateful_mode_enabled
                else []
            ),
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
