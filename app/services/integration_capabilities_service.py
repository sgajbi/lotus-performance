from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final

CALCULATION_SUPPORTABILITY_SURFACE_KEYS: Final[tuple[str, ...]] = ("twr", "mwr", "contribution", "attribution")
CALCULATION_SUPPORTABILITY_DESCRIPTION: Final[str] = (
    "Bounded TWR, MWR, contribution, and attribution calculation supportability response metadata "
    "and Prometheus posture metrics."
)
PERFORMANCE_EXECUTION_POLL_PATH_TEMPLATE: Final[str] = "/performance/executions/{calculation_id}"


@dataclass(frozen=True)
class IntegrationCapabilityFlags:
    twr_enabled: bool
    mwr_enabled: bool
    contribution_enabled: bool
    attribution_enabled: bool
    benchmark_enabled: bool
    workspace_summary_enabled: bool
    composite_twr_enabled: bool
    stateful_mode_enabled: bool
    stateless_mode_enabled: bool
    policy_version: str


@dataclass(frozen=True)
class IntegrationCapabilitiesReport:
    supported_input_modes: list[str]
    features: list[dict[str, object]]
    workflows: list[dict[str, object]]
    analytics_surfaces: list[dict[str, object]]
    generated_at: datetime
    as_of_date: date
    policy_version: str


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def _env_nonblank(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def read_capability_flags() -> IntegrationCapabilityFlags:
    return IntegrationCapabilityFlags(
        twr_enabled=_env_bool("PA_CAP_TWR_ENABLED", True),
        mwr_enabled=_env_bool("PA_CAP_MWR_ENABLED", True),
        contribution_enabled=_env_bool("PA_CAP_CONTRIBUTION_ENABLED", True),
        attribution_enabled=_env_bool("PA_CAP_ATTRIBUTION_ENABLED", True),
        benchmark_enabled=_env_bool("PA_CAP_BENCHMARK_ENABLED", True),
        workspace_summary_enabled=_env_bool("PA_CAP_WORKSPACE_SUMMARY_ENABLED", True),
        composite_twr_enabled=_env_bool("PA_CAP_COMPOSITE_TWR_ENABLED", True),
        stateful_mode_enabled=_env_bool("PLATFORM_INPUT_MODE_STATEFUL_ENABLED", True),
        stateless_mode_enabled=_env_bool("PLATFORM_INPUT_MODE_STATELESS_ENABLED", True),
        policy_version=_env_nonblank("PA_POLICY_VERSION", "tenant-default-v1"),
    )


def _supported_input_modes(flags: IntegrationCapabilityFlags) -> list[str]:
    supported_modes: list[str] = []
    if flags.stateful_mode_enabled:
        supported_modes.append("stateful")
    if flags.stateless_mode_enabled:
        supported_modes.append("stateless")
    return supported_modes


def _calculation_supportability_enabled(flags: IntegrationCapabilityFlags) -> bool:
    calculation_supportability_surface_enabled = {
        "twr": flags.twr_enabled,
        "mwr": flags.mwr_enabled,
        "contribution": flags.contribution_enabled,
        "attribution": flags.attribution_enabled,
    }
    return any(
        calculation_supportability_surface_enabled[surface_key]
        for surface_key in CALCULATION_SUPPORTABILITY_SURFACE_KEYS
    )


def _build_feature_capabilities(flags: IntegrationCapabilityFlags) -> list[dict[str, object]]:
    return [
        {
            "key": "performance.analytics.twr",
            "enabled": flags.twr_enabled,
            "owner_service": "lotus-performance",
            "description": "Portfolio-level time-weighted return analytics APIs.",
        },
        {
            "key": "performance.analytics.mwr",
            "enabled": flags.mwr_enabled,
            "owner_service": "lotus-performance",
            "description": "Money-weighted return analytics APIs.",
        },
        {
            "key": "performance.analytics.contribution",
            "enabled": flags.contribution_enabled,
            "owner_service": "lotus-performance",
            "description": "Contribution analytics APIs.",
        },
        {
            "key": "performance.analytics.attribution",
            "enabled": flags.attribution_enabled,
            "owner_service": "lotus-performance",
            "description": "Attribution analytics APIs.",
        },
        {
            "key": "performance.analytics.benchmark",
            "enabled": flags.benchmark_enabled,
            "owner_service": "lotus-performance",
            "description": "Benchmark performance analytics APIs.",
        },
        {
            "key": "performance.integration.benchmark_exposure_context",
            "enabled": flags.benchmark_enabled and flags.stateful_mode_enabled,
            "owner_service": "lotus-performance",
            "description": "Performance-aligned benchmark exposure context derived from lotus-core benchmark lineage.",
        },
        {
            "key": "performance.analytics.workspace_summary",
            "enabled": flags.workspace_summary_enabled,
            "owner_service": "lotus-performance",
            "description": "Interaction-efficient workspace summary analytics API.",
        },
        {
            "key": "performance.analytics.composite_twr",
            "enabled": flags.composite_twr_enabled,
            "owner_service": "lotus-performance",
            "description": "Persisted-fact composite TWR analytics API.",
        },
        {
            "key": "performance.support.twr_inspection",
            "enabled": flags.twr_enabled,
            "owner_service": "lotus-performance",
            "description": "Durable TWR supportability inspection and artifact-backed triage API.",
        },
        {
            "key": "performance.observability.calculation_supportability",
            "enabled": _calculation_supportability_enabled(flags),
            "owner_service": "lotus-performance",
            "description": CALCULATION_SUPPORTABILITY_DESCRIPTION,
        },
        {
            "key": "performance.integration.mandate_performance_health_context",
            "enabled": flags.twr_enabled,
            "owner_service": "lotus-performance",
            "description": "Bounded source-owned mandate performance health context for DPM supportability.",
        },
        {
            "key": "performance.execution.stateful",
            "enabled": flags.stateful_mode_enabled,
            "owner_service": "lotus-performance",
            "description": "lotus-performance executes using platform-managed stateful input retrieval.",
        },
        {
            "key": "performance.execution.stateless",
            "enabled": flags.stateless_mode_enabled,
            "owner_service": "lotus-performance",
            "description": "lotus-performance executes analytics from request-supplied stateless input data.",
        },
    ]


def _build_workflow_capabilities(flags: IntegrationCapabilityFlags) -> list[dict[str, object]]:
    return [
        {
            "workflow_key": "performance_snapshot",
            "enabled": _workflow_enabled(flags.twr_enabled, flags.mwr_enabled, flags.benchmark_enabled),
            "required_features": [
                "performance.analytics.twr",
                "performance.analytics.mwr",
                "performance.analytics.benchmark",
            ],
        },
        {
            "workflow_key": "performance_explainability",
            "enabled": _workflow_enabled(flags.contribution_enabled, flags.attribution_enabled),
            "required_features": ["performance.analytics.contribution", "performance.analytics.attribution"],
        },
        {
            "workflow_key": "performance_workspace",
            "enabled": _workflow_enabled(flags.workspace_summary_enabled, flags.twr_enabled, flags.mwr_enabled),
            "required_features": [
                "performance.analytics.workspace_summary",
                "performance.analytics.twr",
                "performance.analytics.mwr",
            ],
        },
        {
            "workflow_key": "composite_performance_publication",
            "enabled": flags.composite_twr_enabled,
            "required_features": ["performance.analytics.composite_twr"],
        },
        {
            "workflow_key": "performance_support_triage",
            "enabled": flags.twr_enabled,
            "required_features": ["performance.analytics.twr", "performance.support.twr_inspection"],
        },
        {
            "workflow_key": "mandate_performance_health_context",
            "enabled": flags.twr_enabled,
            "required_features": [
                "performance.analytics.twr",
                "performance.integration.mandate_performance_health_context",
            ],
        },
        {
            "workflow_key": "execution_stateful",
            "enabled": flags.stateful_mode_enabled,
            "required_features": ["performance.execution.stateful"],
        },
        {
            "workflow_key": "execution_stateless",
            "enabled": flags.stateless_mode_enabled,
            "required_features": ["performance.execution.stateless"],
        },
    ]


def _workflow_enabled(*feature_flags: bool) -> bool:
    return all(feature_flags)


def _twr_inspection_contract_notes(flags: IntegrationCapabilityFlags) -> list[str]:
    if not flags.twr_enabled:
        return []
    return [
        "supports inspection of an existing TWR calculation or a proposed TWR request payload",
        "inspection profiles expose bounded support_triage, canonical_validation, and deep_reconciliation behavior",
        "artifact retrieval includes inspection_summary.json, findings.json, and source_quality_summary.json, plus reconciliation_summary.json and source_economics_summary.json when stateful source-economics checks run",
        "stateful reconciliation inspection covers portfolio-position tie-out and unexplained position begin-value carry-forward breaks",
        'stateful portfolio and position valuation normalization share the source cash-flow taxonomy used by inspection; operational expenses must arrive as canonical cash_flow_type="fee" with source_classification="EXPENSE"',
        "source-economics inspection now covers fee and external cash-flow classification and normalization mismatches, duplicate source signals, positive fee sign anomalies, fee or external source-total mismatches, external timing-bucket contradictions, governed alias cash_flow_type labels, unsupported cash_flow_type labels, and non-canonical cash_flow_type labels",
    ]


def _twr_inspection_options(flags: IntegrationCapabilityFlags) -> list[dict[str, object]]:
    if not flags.twr_enabled:
        return []
    return [
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
    ]


def _workspace_summary_contract_notes(flags: IntegrationCapabilityFlags) -> list[str]:
    if not flags.workspace_summary_enabled:
        return []
    return [
        "supports multi-horizon workspace periods including 1D, 2D, 5D, 10D, 1M, 3M, 6M, YTD, 1Y, 2Y, 5Y, 10Y, SI, and EXPLICIT",
        "summary and breakdown rows emit period_return, cumulative_return, and annualized_return; for periods up to one year annualized_return equals cumulative_return",
        "resolves the longest requested window once and derives shorter requested periods from the same sourced data",
    ]


def _workspace_summary_options(flags: IntegrationCapabilityFlags) -> list[dict[str, object]]:
    if not flags.workspace_summary_enabled:
        return []
    return [
        {
            "key": "benchmark_mode",
            "supported_values": ["user_input_stateless", "linked_stateful"],
            "required_when": "benchmark or benchmark-aware blocks are requested",
            "notes": [
                "stateless workspace summary requires an explicit benchmark payload when include_benchmark=true",
                "stateful workspace summary can resolve the linked benchmark from lotus-core assignment",
            ],
        }
    ]


def _attribution_stateful_restrictions(flags: IntegrationCapabilityFlags) -> list[str]:
    if not flags.stateful_mode_enabled or not flags.attribution_enabled:
        return []
    return [
        "mode=by_instrument only",
        "group_by limited to asset_class, sector, country, currency",
        "currency_mode=BOTH requires report_ccy and fx.rates for mixed-currency positions",
    ]


def _mandate_performance_health_contract_notes(flags: IntegrationCapabilityFlags) -> list[str]:
    if not flags.twr_enabled:
        return []
    return [
        "emits bounded lotus-performance-owned active-return health posture for lotus-manage DPM supportability.",
        "does not create mandate actions, rebalance waves, client communications, orders, OMS, or execution instructions",
    ]


def _composite_twr_contract_notes(flags: IntegrationCapabilityFlags) -> list[str]:
    if not flags.composite_twr_enabled:
        return []
    return [
        "calculates composite TWR only from persisted member-return facts",
        "does not accept ad hoc member returns or hidden request-time portfolio TWR fan-out",
        "does not advertise composite contribution, attribution, MWR, benchmark active return, or special composite structures",
    ]


def _benchmark_exposure_context_enabled(flags: IntegrationCapabilityFlags) -> bool:
    return flags.benchmark_enabled and flags.stateful_mode_enabled


def _benchmark_exposure_stateful_restrictions(flags: IntegrationCapabilityFlags) -> list[str]:
    if not _benchmark_exposure_context_enabled(flags):
        return []
    return [
        "lotus-core remains the benchmark composition system of record",
        "POSITION, SECTOR, ASSET_CLASS, and ISSUER grouping dimensions are supported",
        "ISSUER groups use lotus-core index-catalog issuer_id and issuer_name classification labels",
    ]


def _benchmark_exposure_contract_notes(flags: IntegrationCapabilityFlags) -> list[str]:
    if not _benchmark_exposure_context_enabled(flags):
        return []
    return [
        "returns a lineage-backed benchmark exposure view aligned to benchmark performance context",
        "intended for lotus-risk stateful ACTIVE_RISK attribution integration",
    ]


def _async_analytics_surface(
    *,
    key: str,
    path: str,
    enabled: bool,
    supported_input_modes: Sequence[str],
    result_path_template: str,
    stateful_restrictions: Sequence[str] = (),
    contract_notes: Sequence[str] = (),
    options: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    return {
        "key": key,
        "path": path,
        "enabled": enabled,
        "supported_input_modes": list(supported_input_modes),
        "supports_async": True,
        "poll_path_template": PERFORMANCE_EXECUTION_POLL_PATH_TEMPLATE,
        "result_path_template": result_path_template,
        "stateful_restrictions": list(stateful_restrictions),
        "contract_notes": list(contract_notes),
        "options": list(options),
    }


def _sync_analytics_surface(
    *,
    key: str,
    path: str,
    enabled: bool,
    supported_input_modes: Sequence[str],
    stateful_restrictions: Sequence[str] = (),
    contract_notes: Sequence[str] = (),
    options: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    return {
        "key": key,
        "path": path,
        "enabled": enabled,
        "supported_input_modes": list(supported_input_modes),
        "supports_async": False,
        "poll_path_template": None,
        "result_path_template": None,
        "stateful_restrictions": list(stateful_restrictions),
        "contract_notes": list(contract_notes),
        "options": list(options),
    }


def _build_analytics_surfaces(
    *,
    flags: IntegrationCapabilityFlags,
    supported_input_modes: list[str],
) -> list[dict[str, object]]:
    return [
        *_portfolio_analytics_surfaces(flags=flags, supported_input_modes=supported_input_modes),
        _async_analytics_surface(
            key="contribution",
            path="/performance/contribution",
            enabled=flags.contribution_enabled,
            supported_input_modes=supported_input_modes,
            result_path_template="/performance/contribution/results/{calculation_id}",
        ),
        _async_analytics_surface(
            key="attribution",
            path="/performance/attribution",
            enabled=flags.attribution_enabled,
            supported_input_modes=supported_input_modes,
            result_path_template="/performance/attribution/results/{calculation_id}",
            stateful_restrictions=_attribution_stateful_restrictions(flags),
        ),
        _sync_analytics_surface(
            key="composite_twr",
            path="/performance/composites/twr",
            enabled=flags.composite_twr_enabled,
            supported_input_modes=["persisted_member_facts"],
            contract_notes=_composite_twr_contract_notes(flags),
        ),
        _sync_analytics_surface(
            key="mandate_performance_health_context",
            path="/performance/mandate-health-context",
            enabled=flags.twr_enabled,
            supported_input_modes=["stateless"],
            contract_notes=_mandate_performance_health_contract_notes(flags),
        ),
        _async_analytics_surface(
            key="returns_series",
            path="/integration/returns/series",
            enabled=bool(flags.stateful_mode_enabled or flags.stateless_mode_enabled),
            supported_input_modes=supported_input_modes,
            result_path_template="/integration/returns/series/results/{calculation_id}",
        ),
        _sync_analytics_surface(
            key="benchmark_exposure_context",
            path="/integration/benchmarks/exposure-context",
            enabled=_benchmark_exposure_context_enabled(flags),
            supported_input_modes=["stateful"] if flags.stateful_mode_enabled else [],
            stateful_restrictions=_benchmark_exposure_stateful_restrictions(flags),
            contract_notes=_benchmark_exposure_contract_notes(flags),
        ),
    ]


def _portfolio_analytics_surfaces(
    *,
    flags: IntegrationCapabilityFlags,
    supported_input_modes: list[str],
) -> list[dict[str, object]]:
    return [
        _async_analytics_surface(
            key="twr",
            path="/performance/twr",
            enabled=flags.twr_enabled,
            supported_input_modes=supported_input_modes,
            result_path_template="/performance/twr/results/{calculation_id}",
            contract_notes=[
                "supports portfolio-level TWR only",
                "does not advertise composite, group, or sleeve TWR calculation support",
            ],
        ),
        _async_analytics_surface(
            key="twr_inspection",
            path="/performance/inspections/twr",
            enabled=flags.twr_enabled,
            supported_input_modes=[],
            result_path_template="/performance/inspections/{inspection_id}",
            contract_notes=_twr_inspection_contract_notes(flags),
            options=_twr_inspection_options(flags),
        ),
        _sync_analytics_surface(
            key="mwr",
            path="/performance/mwr",
            enabled=flags.mwr_enabled,
            supported_input_modes=supported_input_modes,
        ),
        _async_analytics_surface(
            key="benchmark",
            path="/performance/benchmark",
            enabled=flags.benchmark_enabled,
            supported_input_modes=supported_input_modes,
            result_path_template="/performance/benchmark/results/{calculation_id}",
        ),
        _async_analytics_surface(
            key="workspace_summary",
            path="/performance/workspace-summary",
            enabled=flags.workspace_summary_enabled,
            supported_input_modes=supported_input_modes,
            result_path_template="/performance/workspace-summary/results/{calculation_id}",
            contract_notes=_workspace_summary_contract_notes(flags),
            options=_workspace_summary_options(flags),
        ),
    ]


def build_integration_capabilities_report(
    *,
    feature_limit: int = 100,
    workflow_limit: int = 50,
) -> IntegrationCapabilitiesReport:
    flags = read_capability_flags()
    supported_input_modes = _supported_input_modes(flags)

    return IntegrationCapabilitiesReport(
        supported_input_modes=supported_input_modes,
        features=_build_feature_capabilities(flags)[:feature_limit],
        workflows=_build_workflow_capabilities(flags)[:workflow_limit],
        analytics_surfaces=_build_analytics_surfaces(flags=flags, supported_input_modes=supported_input_modes),
        generated_at=datetime.now(UTC),
        as_of_date=date.today(),
        policy_version=flags.policy_version,
    )
