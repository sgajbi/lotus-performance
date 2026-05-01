import os
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["Integration"])

ConsumerSystem = Literal[
    "lotus-gateway",
    "lotus-performance",
    "lotus-risk",
    "lotus-manage",
    "lotus-workbench",
    "lotus-report",
    "lotus-advise",
    "UI",
    "UNKNOWN",
]

CALCULATION_SUPPORTABILITY_SURFACE_KEYS = ("twr", "mwr", "contribution", "attribution")
CALCULATION_SUPPORTABILITY_DESCRIPTION = (
    "Bounded TWR, MWR, contribution, and attribution calculation supportability response metadata "
    "and Prometheus posture metrics."
)

INTEGRATION_CAPABILITIES_RESPONSE_EXAMPLES = [
    {
        "contract_version": "v1",
        "source_service": "lotus-performance",
        "consumer_system": "lotus-gateway",
        "tenant_id": "default",
        "generated_at": "2026-04-10T12:00:00Z",
        "as_of_date": "2026-04-10",
        "policy_version": "tenant-default-v1",
        "supported_input_modes": ["stateful", "stateless"],
        "analytics_surfaces": [
            {
                "key": "twr",
                "path": "/performance/twr",
                "enabled": True,
                "supported_input_modes": ["stateful", "stateless"],
                "supports_async": True,
                "poll_path_template": "/performance/executions/{calculation_id}",
                "result_path_template": "/performance/twr/results/{calculation_id}",
                "stateful_restrictions": [],
                "contract_notes": [],
                "options": [],
            },
            {
                "key": "twr_inspection",
                "path": "/performance/inspections/twr",
                "enabled": True,
                "supported_input_modes": [],
                "supports_async": True,
                "poll_path_template": "/performance/executions/{calculation_id}",
                "result_path_template": "/performance/inspections/{inspection_id}",
                "stateful_restrictions": [],
                "contract_notes": [
                    "supports inspection of an existing TWR calculation or a proposed TWR request payload",
                    "inspection profiles expose bounded support_triage, canonical_validation, and deep_reconciliation behavior",
                    "artifact retrieval includes inspection_summary.json, findings.json, and source_quality_summary.json, plus reconciliation_summary.json and source_economics_summary.json when stateful source-economics checks run",
                ],
                "options": [
                    {
                        "key": "subject_type",
                        "supported_values": ["twr_calculation", "twr_request"],
                        "required_when": "always",
                        "notes": [
                            "twr_calculation inspects an existing durable TWR execution identity",
                            "twr_request inspects a proposed TWR request payload without mutating the normal TWR contract",
                        ],
                    },
                    {
                        "key": "inspection_profile",
                        "supported_values": ["support_triage", "canonical_validation", "deep_reconciliation"],
                        "required_when": "always",
                        "notes": [
                            "support_triage is the default bounded supportability workflow",
                            "canonical_validation is the governed profile for canonical portfolio validation",
                            "deep_reconciliation adds heavier stateful reconciliation evidence for upstream escalation",
                        ],
                    },
                ],
            },
            {
                "key": "mwr",
                "path": "/performance/mwr",
                "enabled": True,
                "supported_input_modes": ["stateful", "stateless"],
                "supports_async": False,
                "poll_path_template": None,
                "result_path_template": None,
                "stateful_restrictions": [],
                "contract_notes": [],
                "options": [],
            },
            {
                "key": "benchmark",
                "path": "/performance/benchmark",
                "enabled": True,
                "supported_input_modes": ["stateful", "stateless"],
                "supports_async": True,
                "poll_path_template": "/performance/executions/{calculation_id}",
                "result_path_template": "/performance/benchmark/results/{calculation_id}",
                "stateful_restrictions": [],
                "contract_notes": [],
                "options": [],
            },
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
            },
            {
                "key": "contribution",
                "path": "/performance/contribution",
                "enabled": True,
                "supported_input_modes": ["stateful", "stateless"],
                "supports_async": True,
                "poll_path_template": "/performance/executions/{calculation_id}",
                "result_path_template": "/performance/contribution/results/{calculation_id}",
                "stateful_restrictions": [],
                "contract_notes": [],
                "options": [],
            },
            {
                "key": "attribution",
                "path": "/performance/attribution",
                "enabled": True,
                "supported_input_modes": ["stateful", "stateless"],
                "supports_async": True,
                "poll_path_template": "/performance/executions/{calculation_id}",
                "result_path_template": "/performance/attribution/results/{calculation_id}",
                "stateful_restrictions": [
                    "mode=by_instrument only",
                    "group_by limited to asset_class, sector, country, currency",
                    "currency_mode=BOTH requires report_ccy and fx.rates for mixed-currency positions",
                ],
                "contract_notes": [],
                "options": [],
            },
            {
                "key": "returns_series",
                "path": "/integration/returns/series",
                "enabled": True,
                "supported_input_modes": ["stateful", "stateless"],
                "supports_async": True,
                "poll_path_template": "/performance/executions/{calculation_id}",
                "result_path_template": "/integration/returns/series/results/{calculation_id}",
                "stateful_restrictions": [],
                "contract_notes": [],
                "options": [],
            },
            {
                "key": "benchmark_exposure_context",
                "path": "/integration/benchmarks/exposure-context",
                "enabled": True,
                "supported_input_modes": ["stateful"],
                "supports_async": False,
                "poll_path_template": None,
                "result_path_template": None,
                "stateful_restrictions": [
                    "lotus-core remains the benchmark composition system of record",
                    "POSITION, SECTOR, and ASSET_CLASS grouping dimensions are supported",
                    "ISSUER remains gated until benchmark issuer exposure semantics are approved",
                ],
                "contract_notes": [
                    "returns a lineage-backed benchmark exposure view aligned to benchmark performance context",
                    "intended for lotus-risk stateful ACTIVE_RISK attribution integration",
                ],
                "options": [],
            },
        ],
        "features": [
            {
                "key": "performance.analytics.twr",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Time-weighted return analytics APIs.",
            },
            {
                "key": "performance.analytics.mwr",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Money-weighted return analytics APIs.",
            },
            {
                "key": "performance.analytics.contribution",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Contribution analytics APIs.",
            },
            {
                "key": "performance.analytics.attribution",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Attribution analytics APIs.",
            },
            {
                "key": "performance.analytics.benchmark",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Benchmark performance analytics APIs.",
            },
            {
                "key": "performance.integration.benchmark_exposure_context",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Performance-aligned benchmark exposure context derived from lotus-core benchmark lineage.",
            },
            {
                "key": "performance.analytics.workspace_summary",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Interaction-efficient workspace summary analytics API.",
            },
            {
                "key": "performance.support.twr_inspection",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "Durable TWR supportability inspection and artifact-backed triage API.",
            },
            {
                "key": "performance.observability.calculation_supportability",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": CALCULATION_SUPPORTABILITY_DESCRIPTION,
            },
            {
                "key": "performance.execution.stateful",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "lotus-performance executes using platform-managed stateful input retrieval.",
            },
            {
                "key": "performance.execution.stateless",
                "enabled": True,
                "owner_service": "lotus-performance",
                "description": "lotus-performance executes analytics from request-supplied stateless input data.",
            },
        ],
        "workflows": [
            {
                "workflow_key": "performance_snapshot",
                "enabled": True,
                "required_features": [
                    "performance.analytics.twr",
                    "performance.analytics.mwr",
                    "performance.analytics.benchmark",
                ],
            },
            {
                "workflow_key": "performance_explainability",
                "enabled": True,
                "required_features": ["performance.analytics.contribution", "performance.analytics.attribution"],
            },
            {
                "workflow_key": "performance_workspace",
                "enabled": True,
                "required_features": [
                    "performance.analytics.workspace_summary",
                    "performance.analytics.twr",
                    "performance.analytics.mwr",
                ],
            },
            {
                "workflow_key": "performance_support_triage",
                "enabled": True,
                "required_features": ["performance.analytics.twr", "performance.support.twr_inspection"],
            },
            {
                "workflow_key": "execution_stateful",
                "enabled": True,
                "required_features": ["performance.execution.stateful"],
            },
            {
                "workflow_key": "execution_stateless",
                "enabled": True,
                "required_features": ["performance.execution.stateless"],
            },
        ],
    }
]


class FeatureCapability(BaseModel):
    key: str = Field(description="Canonical feature key.", examples=["performance.analytics.twr"])
    enabled: bool = Field(description="Whether this feature is enabled.", examples=[True])
    owner_service: str = Field(description="Owning service for this feature.", examples=["lotus-performance"])
    description: str = Field(description="Human-readable capability summary.", examples=["Time-weighted return APIs."])


class WorkflowCapability(BaseModel):
    workflow_key: str = Field(
        description="Workflow key for feature orchestration.",
        examples=["performance_workspace"],
    )
    enabled: bool = Field(description="Whether workflow is enabled.", examples=[True])
    required_features: list[str] = Field(
        default_factory=list,
        description="Feature keys required for this workflow.",
        examples=[
            ["performance.analytics.workspace_summary", "performance.analytics.twr", "performance.analytics.mwr"]
        ],
        json_schema_extra={
            "example": [
                "performance.analytics.workspace_summary",
                "performance.analytics.twr",
                "performance.analytics.mwr",
            ]
        },
    )


class AnalyticsSurfaceOptionCapability(BaseModel):
    key: str = Field(
        description="Canonical request-option key for this analytics surface.", examples=["benchmark_mode"]
    )
    supported_values: list[str] = Field(
        default_factory=list,
        description="Supported values or named options for this request capability.",
        examples=[["user_input_stateless", "linked_stateful"]],
        json_schema_extra={"example": ["user_input_stateless", "linked_stateful"]},
    )
    required_when: str | None = Field(
        default=None,
        description="Condition under which this option or companion input becomes required.",
        examples=["benchmark or benchmark-aware blocks are requested"],
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional contract notes for this request option.",
        examples=[["stateful workspace summary can resolve the linked benchmark from lotus-core assignment"]],
    )


class AnalyticsSurfaceCapability(BaseModel):
    key: str = Field(description="Canonical analytics surface key.", examples=["workspace_summary"])
    path: str = Field(description="HTTP path for this analytics surface.", examples=["/performance/workspace-summary"])
    enabled: bool = Field(description="Whether this analytics surface is enabled.", examples=[True])
    supported_input_modes: list[str] = Field(
        default_factory=list,
        description="Supported execution input modes for this specific analytics surface.",
        examples=[["stateful", "stateless"]],
    )
    supports_async: bool = Field(
        description="Whether this analytics surface can return 202 async accepted responses.",
        examples=[True],
    )
    poll_path_template: str | None = Field(
        default=None,
        description="Execution polling path template for async-capable surfaces.",
        examples=["/performance/executions/{calculation_id}"],
    )
    result_path_template: str | None = Field(
        default=None,
        description="Endpoint-specific async result path template for async-capable surfaces.",
        examples=["/performance/workspace-summary/results/{calculation_id}"],
    )
    stateful_restrictions: list[str] = Field(
        default_factory=list,
        description="Current stateful-mode fences or restrictions for this analytics surface.",
        examples=[["POSITION, SECTOR, and ASSET_CLASS grouping dimensions are supported"]],
        json_schema_extra={"example": ["POSITION, SECTOR, and ASSET_CLASS grouping dimensions are supported"]},
    )
    contract_notes: list[str] = Field(
        default_factory=list,
        description="Surface-specific contract notes that downstream consumers should treat as part of the supported behavior.",
        examples=[["returns a lineage-backed benchmark exposure view aligned to benchmark performance context"]],
        json_schema_extra={
            "example": ["returns a lineage-backed benchmark exposure view aligned to benchmark performance context"]
        },
    )
    options: list[AnalyticsSurfaceOptionCapability] = Field(
        default_factory=list,
        description="Machine-readable request-option capabilities for this analytics surface.",
    )


class IntegrationCapabilitiesResponse(BaseModel):
    contract_version: str = Field(description="Version of the integration-capabilities response contract.")
    source_service: str = Field(description="Service that owns and emitted this capability contract.")
    consumer_system: ConsumerSystem = Field(description="Downstream consumer system this response was shaped for.")
    tenant_id: str = Field(description="Tenant or policy scope used for capability evaluation.")
    generated_at: datetime = Field(description="UTC timestamp when the capability response was generated.")
    as_of_date: date = Field(description="Business date used for policy/capability context.")
    policy_version: str = Field(description="Capability policy version applied by lotus-performance.")
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
    consumer_system: ConsumerSystem = Query(
        "lotus-gateway",
        description="Canonical downstream consumer system. Use snake_case query name `consumer_system`.",
        examples=["lotus-gateway"],
    ),
    tenant_id: str = Query(
        "default",
        description="Tenant or policy scope. Use snake_case query name `tenant_id`.",
        examples=["default"],
    ),
    feature_limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of feature capability rows to return.",
        examples=[100],
    ),
    workflow_limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of workflow capability rows to return.",
        examples=[50],
    ),
) -> IntegrationCapabilitiesResponse:
    twr_enabled = _env_bool("PA_CAP_TWR_ENABLED", True)
    mwr_enabled = _env_bool("PA_CAP_MWR_ENABLED", True)
    contribution_enabled = _env_bool("PA_CAP_CONTRIBUTION_ENABLED", True)
    attribution_enabled = _env_bool("PA_CAP_ATTRIBUTION_ENABLED", True)
    benchmark_enabled = _env_bool("PA_CAP_BENCHMARK_ENABLED", True)
    workspace_summary_enabled = _env_bool("PA_CAP_WORKSPACE_SUMMARY_ENABLED", True)
    stateful_mode_enabled = _env_bool("PLATFORM_INPUT_MODE_STATEFUL_ENABLED", True)
    stateless_mode_enabled = _env_bool("PLATFORM_INPUT_MODE_STATELESS_ENABLED", True)
    calculation_supportability_surface_enabled = {
        "twr": twr_enabled,
        "mwr": mwr_enabled,
        "contribution": contribution_enabled,
        "attribution": attribution_enabled,
    }
    calculation_supportability_enabled = any(
        calculation_supportability_surface_enabled[key] for key in CALCULATION_SUPPORTABILITY_SURFACE_KEYS
    )

    features = [
        FeatureCapability(
            key="performance.analytics.twr",
            enabled=twr_enabled,
            owner_service="lotus-performance",
            description="Time-weighted return analytics APIs.",
        ),
        FeatureCapability(
            key="performance.analytics.mwr",
            enabled=mwr_enabled,
            owner_service="lotus-performance",
            description="Money-weighted return analytics APIs.",
        ),
        FeatureCapability(
            key="performance.analytics.contribution",
            enabled=contribution_enabled,
            owner_service="lotus-performance",
            description="Contribution analytics APIs.",
        ),
        FeatureCapability(
            key="performance.analytics.attribution",
            enabled=attribution_enabled,
            owner_service="lotus-performance",
            description="Attribution analytics APIs.",
        ),
        FeatureCapability(
            key="performance.analytics.benchmark",
            enabled=benchmark_enabled,
            owner_service="lotus-performance",
            description="Benchmark performance analytics APIs.",
        ),
        FeatureCapability(
            key="performance.integration.benchmark_exposure_context",
            enabled=benchmark_enabled and stateful_mode_enabled,
            owner_service="lotus-performance",
            description="Performance-aligned benchmark exposure context derived from lotus-core benchmark lineage.",
        ),
        FeatureCapability(
            key="performance.analytics.workspace_summary",
            enabled=workspace_summary_enabled,
            owner_service="lotus-performance",
            description="Interaction-efficient workspace summary analytics API.",
        ),
        FeatureCapability(
            key="performance.support.twr_inspection",
            enabled=twr_enabled,
            owner_service="lotus-performance",
            description="Durable TWR supportability inspection and artifact-backed triage API.",
        ),
        FeatureCapability(
            key="performance.observability.calculation_supportability",
            enabled=calculation_supportability_enabled,
            owner_service="lotus-performance",
            description=CALCULATION_SUPPORTABILITY_DESCRIPTION,
        ),
        FeatureCapability(
            key="performance.execution.stateful",
            enabled=stateful_mode_enabled,
            owner_service="lotus-performance",
            description="lotus-performance executes using platform-managed stateful input retrieval.",
        ),
        FeatureCapability(
            key="performance.execution.stateless",
            enabled=stateless_mode_enabled,
            owner_service="lotus-performance",
            description="lotus-performance executes analytics from request-supplied stateless input data.",
        ),
    ]

    workflows = [
        WorkflowCapability(
            workflow_key="performance_snapshot",
            enabled=twr_enabled and mwr_enabled and benchmark_enabled,
            required_features=[
                "performance.analytics.twr",
                "performance.analytics.mwr",
                "performance.analytics.benchmark",
            ],
        ),
        WorkflowCapability(
            workflow_key="performance_explainability",
            enabled=contribution_enabled and attribution_enabled,
            required_features=["performance.analytics.contribution", "performance.analytics.attribution"],
        ),
        WorkflowCapability(
            workflow_key="performance_workspace",
            enabled=workspace_summary_enabled and twr_enabled and mwr_enabled,
            required_features=[
                "performance.analytics.workspace_summary",
                "performance.analytics.twr",
                "performance.analytics.mwr",
            ],
        ),
        WorkflowCapability(
            workflow_key="performance_support_triage",
            enabled=twr_enabled,
            required_features=["performance.analytics.twr", "performance.support.twr_inspection"],
        ),
        WorkflowCapability(
            workflow_key="execution_stateful",
            enabled=stateful_mode_enabled,
            required_features=["performance.execution.stateful"],
        ),
        WorkflowCapability(
            workflow_key="execution_stateless",
            enabled=stateless_mode_enabled,
            required_features=["performance.execution.stateless"],
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
            key="twr_inspection",
            path="/performance/inspections/twr",
            enabled=twr_enabled,
            supported_input_modes=[],
            supports_async=True,
            poll_path_template="/performance/executions/{calculation_id}",
            result_path_template="/performance/inspections/{inspection_id}",
            contract_notes=(
                [
                    "supports inspection of an existing TWR calculation or a proposed TWR request payload",
                    "inspection profiles expose bounded support_triage, canonical_validation, and deep_reconciliation behavior",
                    "artifact retrieval includes inspection_summary.json, findings.json, and source_quality_summary.json, plus reconciliation_summary.json and source_economics_summary.json when stateful source-economics checks run",
                    "stateful reconciliation inspection covers portfolio-position tie-out and unexplained position begin-value carry-forward breaks",
                    'stateful portfolio and position valuation normalization share the source cash-flow taxonomy used by inspection; operational expenses must arrive as canonical cash_flow_type="fee" with source_classification="EXPENSE"',
                    "source-economics inspection now covers fee and external cash-flow classification and normalization mismatches, duplicate source signals, positive fee sign anomalies, fee or external source-total mismatches, external timing-bucket contradictions, governed alias cash_flow_type labels, unsupported cash_flow_type labels, and non-canonical cash_flow_type labels",
                ]
                if twr_enabled
                else []
            ),
            options=(
                [
                    AnalyticsSurfaceOptionCapability(
                        key="subject_type",
                        supported_values=["twr_calculation", "twr_request"],
                        required_when="always",
                        notes=[
                            "twr_calculation inspects an existing durable TWR execution identity",
                            "twr_request inspects a proposed TWR request payload without mutating the normal TWR contract",
                        ],
                    ),
                    AnalyticsSurfaceOptionCapability(
                        key="inspection_profile",
                        supported_values=["support_triage", "canonical_validation", "deep_reconciliation"],
                        required_when="always",
                        notes=[
                            "support_triage is the default bounded supportability workflow",
                            "canonical_validation is the governed profile for canonical portfolio validation",
                            "deep_reconciliation adds heavier stateful reconciliation evidence for upstream escalation",
                        ],
                    ),
                ]
                if twr_enabled
                else []
            ),
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
