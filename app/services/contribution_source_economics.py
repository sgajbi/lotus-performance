from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import ContributionSourceEconomicsEvidence
from app.services.execution_registry import UpstreamSnapshotRecord

_COMPONENT_PNL_FIELDS = (
    "price_pnl",
    "income_pnl",
    "fee_pnl",
    "tax_pnl",
    "fx_pnl",
    "corporate_action_pnl",
    "derivative_pnl",
    "cash_pnl",
    "residual_pnl",
)
_CLASSIFICATION_DIMENSIONS = ("asset_class", "sector", "country", "currency")
_PERFORMANCE_COMPONENT_ECONOMICS_CONTRACT = "PerformanceComponentEconomics:v1"
_PERFORMANCE_COMPONENT_AVAILABLE_ECONOMICS = {
    "cashflow": "source_component_cashflows",
    "fee": "source_component_fees",
    "income": "source_component_income",
    "tax": "source_component_tax",
    "realized_capital_pnl": "source_realized_capital_pnl",
    "realized_fx_pnl": "source_realized_fx_pnl",
    "realized_total_pnl": "source_realized_total_pnl",
    "fx_context": "source_fx_context",
}
_PERFORMANCE_COMPONENT_PNL_FIELD_SUPPORT = {
    "fee": "fee_pnl",
    "income": "income_pnl",
    "tax": "tax_pnl",
}


def build_contribution_source_economics_evidence(
    *,
    request: ContributionRequest,
    input_mode: ContributionInputMode,
    upstream_snapshots: list[UpstreamSnapshotRecord],
) -> ContributionSourceEconomicsEvidence:
    """Summarizes source-economics coverage without inventing unavailable upstream facts."""
    if input_mode == ContributionInputMode.STATELESS:
        return ContributionSourceEconomicsEvidence(
            input_mode="stateless",
            source_owner="caller",
            status="CALLER_SUPPLIED",
            reason_codes=["STATELESS_CALLER_SUPPLIED_SOURCE_ECONOMICS"],
            source_contracts=["ContributionRequest"],
            available_economics=_available_stateless_economics(request),
            unsupported_economics=_unsupported_component_pnl_fields(request),
            degraded_economics=[],
            cash_flow_type_counts={},
            source_snapshot_count=0,
            source_snapshot_endpoints=[],
            classification_dimensions=_classification_dimensions(request),
            lineage_policy="caller-supplied stateless payload; no upstream source snapshot is available",
        )

    return _stateful_source_economics_evidence(
        request=request,
        upstream_snapshots=upstream_snapshots,
    )


def _stateful_source_economics_evidence(
    *,
    request: ContributionRequest,
    upstream_snapshots: list[UpstreamSnapshotRecord],
) -> ContributionSourceEconomicsEvidence:
    cash_flow_type_counts = _cash_flow_type_counts(request)
    component_contexts = _performance_component_economics_contexts(request)
    available_economics = _available_stateful_economics(
        request,
        cash_flow_type_counts,
        component_contexts=component_contexts,
    )
    unsupported_economics = _unsupported_component_pnl_fields(
        request,
        component_contexts=component_contexts,
    )
    degraded_economics = _degraded_stateful_economics(
        request=request,
        cash_flow_type_counts=cash_flow_type_counts,
        upstream_snapshots=upstream_snapshots,
        component_contexts=component_contexts,
    )
    reason_codes = _stateful_reason_codes(
        unsupported_economics=unsupported_economics,
        degraded_economics=degraded_economics,
        upstream_snapshots=upstream_snapshots,
        component_contexts=component_contexts,
    )
    status: Literal["SOURCE_BACKED", "SOURCE_LIMITED"]
    status = "SOURCE_LIMITED" if degraded_economics or unsupported_economics else "SOURCE_BACKED"
    return ContributionSourceEconomicsEvidence(
        input_mode="stateful",
        source_owner="lotus-core",
        status=status,
        reason_codes=reason_codes,
        source_contracts=_stateful_source_contracts(component_contexts),
        available_economics=available_economics,
        unsupported_economics=unsupported_economics,
        degraded_economics=degraded_economics,
        cash_flow_type_counts=dict(sorted(cash_flow_type_counts.items())),
        source_snapshot_count=len(upstream_snapshots),
        source_snapshot_endpoints=sorted({snapshot.upstream_endpoint for snapshot in upstream_snapshots}),
        classification_dimensions=_classification_dimensions(request),
        lineage_policy=(
            "stateful contribution preserves lotus-core analytics-input snapshot evidence through "
            "/performance/executions/{calculation_id}.upstream_snapshots when retrieval is not mocked"
        ),
    )


def _available_stateless_economics(request: ContributionRequest) -> list[str]:
    available = ["portfolio_market_values", "position_market_values"]
    if _has_caller_supplied_position_flows(request):
        available.append("caller_supplied_position_flows")
    if _has_position_currency_metadata(request):
        available.append("position_currency")
    return sorted(set(available))


def _has_caller_supplied_position_flows(request: ContributionRequest) -> bool:
    return any(
        _has_non_zero_flow(point.model_dump(mode="python"))
        for position in request.positions_data
        for point in position.valuation_points
    )


def _has_position_currency_metadata(request: ContributionRequest) -> bool:
    return any(position.meta.get("currency") for position in request.positions_data)


def _available_stateful_economics(
    request: ContributionRequest,
    cash_flow_type_counts: Counter[str],
    *,
    component_contexts: list[dict[str, Any]] | None = None,
) -> list[str]:
    available = ["portfolio_market_values", "position_market_values"]
    available.extend(_stateful_cash_flow_economics(cash_flow_type_counts))
    available.extend(_stateful_metadata_economics(request))
    available.extend(_performance_component_available_economics(component_contexts or []))
    return sorted(set(available))


def _stateful_cash_flow_economics(cash_flow_type_counts: Counter[str]) -> list[str]:
    available: list[str] = []
    if _has_stateful_external_flow_economics(cash_flow_type_counts):
        available.append("external_flows")
    if cash_flow_type_counts.get("internal_trade_flow", 0) > 0:
        available.append("internal_trade_flows")
    if cash_flow_type_counts.get("fee", 0) > 0:
        available.append("fees")
    return available


def _has_stateful_external_flow_economics(cash_flow_type_counts: Counter[str]) -> bool:
    return cash_flow_type_counts.get("external_flow", 0) > 0 or cash_flow_type_counts.get("transfer", 0) > 0


def _stateful_metadata_economics(request: ContributionRequest) -> list[str]:
    available: list[str] = []
    if any(_has_fx_metadata(position.meta) for position in request.positions_data):
        available.append("fx_rates")
    if _classification_dimensions(request):
        available.append("classification_dimensions")
    return available


def _unsupported_component_pnl_fields(
    request: ContributionRequest,
    component_contexts: list[dict[str, Any]] | None = None,
) -> list[str]:
    present_component_fields = _present_component_pnl_fields(request)
    present_component_fields.update(_component_pnl_fields_from_performance_economics(component_contexts or []))
    return [field_name for field_name in _COMPONENT_PNL_FIELDS if field_name not in present_component_fields]


def _present_component_pnl_fields(request: ContributionRequest) -> set[str]:
    return {
        field_name
        for position in request.positions_data
        for field_name in _COMPONENT_PNL_FIELDS
        if field_name in position.meta
    }


def _degraded_stateful_economics(
    *,
    request: ContributionRequest,
    cash_flow_type_counts: Counter[str],
    upstream_snapshots: list[UpstreamSnapshotRecord],
    component_contexts: list[dict[str, Any]],
) -> list[str]:
    degraded: set[str] = set()
    if _has_unsupported_cash_flow_types(cash_flow_type_counts):
        degraded.add("unsupported_cash_flow_types")
    if _has_unclassified_position_metadata(request):
        degraded.add("missing_classification")
    if not upstream_snapshots:
        degraded.add("upstream_snapshot_lineage_not_embedded")
    if _has_degraded_performance_component_economics(component_contexts):
        degraded.add("performance_component_economics_unavailable")
    return sorted(degraded)


def _has_unsupported_cash_flow_types(cash_flow_type_counts: Counter[str]) -> bool:
    return any(
        count > 0 and flow_type not in {"external_flow", "internal_trade_flow", "transfer", "fee", "missing"}
        for flow_type, count in cash_flow_type_counts.items()
    )


def _has_unclassified_position_metadata(request: ContributionRequest) -> bool:
    return any("Unclassified" in position.meta.values() for position in request.positions_data)


def _stateful_reason_codes(
    *,
    unsupported_economics: list[str],
    degraded_economics: list[str],
    upstream_snapshots: list[UpstreamSnapshotRecord],
    component_contexts: list[dict[str, Any]] | None = None,
) -> list[str]:
    reason_codes = ["LOTUS_CORE_ANALYTICS_INPUTS_USED"]
    if component_contexts:
        reason_codes.append("PERFORMANCE_COMPONENT_ECONOMICS_SOURCE_USED")
    if unsupported_economics:
        reason_codes.append("COMPONENT_PNL_NOT_SOURCE_AUTHORED")
    if "performance_component_economics_unavailable" in degraded_economics:
        reason_codes.append("PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE")
    if "unsupported_cash_flow_types" in degraded_economics:
        reason_codes.append("UNSUPPORTED_SOURCE_CASH_FLOW_TYPES_PRESENT")
    if "missing_classification" in degraded_economics:
        reason_codes.append("UNCLASSIFIED_POSITION_ECONOMICS_PRESENT")
    reason_codes.append(_upstream_snapshot_lineage_reason_code(upstream_snapshots))
    return sorted(set(reason_codes))


def _upstream_snapshot_lineage_reason_code(upstream_snapshots: list[UpstreamSnapshotRecord]) -> str:
    if upstream_snapshots:
        return "UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE"
    return "UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE_VIA_EXECUTION_ONLY"


def _cash_flow_type_counts(request: ContributionRequest) -> Counter[str]:
    counts: Counter[str] = Counter()
    for position in request.positions_data:
        counts.update(_source_cash_flow_type_counts(position.meta))
    return counts


def _source_cash_flow_type_counts(meta: dict[str, Any]) -> Counter[str]:
    raw_counts = _raw_source_cash_flow_type_counts(meta)
    if raw_counts is None:
        return Counter()

    counts: Counter[str] = Counter()
    for key, value in raw_counts.items():
        if _is_valid_source_cash_flow_type_count(key, value):
            counts[key] += value
    return counts


def _stateful_source_contracts(component_contexts: list[dict[str, Any]]) -> list[str]:
    contracts = ["PortfolioTimeseriesInput:v1", "PositionTimeseriesInput:v1"]
    if component_contexts:
        contracts.append(_PERFORMANCE_COMPONENT_ECONOMICS_CONTRACT)
    return contracts


def _performance_component_economics_contexts(request: ContributionRequest) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for position in request.positions_data:
        source_economics = position.meta.get("_source_economics")
        if not isinstance(source_economics, dict):
            continue
        context = source_economics.get("performance_component_economics")
        if not isinstance(context, dict):
            continue
        key = (
            context.get("retrieval_status"),
            context.get("supportability_state"),
            tuple(_source_string_list(context.get("observed_component_families"))),
            tuple(_source_string_list(context.get("missing_component_families"))),
        )
        if key in seen:
            continue
        seen.add(key)
        contexts.append(context)
    return contexts


def _performance_component_available_economics(component_contexts: list[dict[str, Any]]) -> list[str]:
    return [
        _PERFORMANCE_COMPONENT_AVAILABLE_ECONOMICS[family]
        for family in sorted(_observed_performance_component_families(component_contexts))
        if family in _PERFORMANCE_COMPONENT_AVAILABLE_ECONOMICS
    ]


def _component_pnl_fields_from_performance_economics(component_contexts: list[dict[str, Any]]) -> set[str]:
    return {
        _PERFORMANCE_COMPONENT_PNL_FIELD_SUPPORT[family]
        for family in _observed_performance_component_families(component_contexts)
        if family in _PERFORMANCE_COMPONENT_PNL_FIELD_SUPPORT
    }


def _observed_performance_component_families(component_contexts: list[dict[str, Any]]) -> set[str]:
    observed: set[str] = set()
    for context in component_contexts:
        if context.get("supportability_state") != "READY":
            continue
        observed.update(_source_string_list(context.get("observed_component_families")))
    return observed


def _has_degraded_performance_component_economics(component_contexts: list[dict[str, Any]]) -> bool:
    for context in component_contexts:
        retrieval_status = context.get("retrieval_status")
        if not isinstance(retrieval_status, int) or retrieval_status >= 400:
            return True
        if context.get("supportability_state") != "READY":
            return True
    return False


def _source_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _raw_source_cash_flow_type_counts(meta: dict[str, Any]) -> dict[Any, Any] | None:
    source_economics = meta.get("_source_economics")
    if not isinstance(source_economics, dict):
        return None
    raw_counts = source_economics.get("cash_flow_type_counts")
    if not isinstance(raw_counts, dict):
        return None
    return raw_counts


def _is_valid_source_cash_flow_type_count(key: Any, value: Any) -> bool:
    return isinstance(key, str) and type(value) is int and value > 0


def _classification_dimensions(request: ContributionRequest) -> list[str]:
    dimensions = {
        dimension
        for position in request.positions_data
        for dimension in _CLASSIFICATION_DIMENSIONS
        if position.meta.get(dimension) is not None
    }
    return sorted(dimensions)


def _has_fx_metadata(meta: dict[str, Any]) -> bool:
    return (
        meta.get("position_to_portfolio_fx_rate") is not None or meta.get("portfolio_to_reporting_fx_rate") is not None
    )


def _has_non_zero_flow(point: dict[str, Any]) -> bool:
    for field_name in ("bod_cf", "eod_cf", "mgmt_fees"):
        if _is_non_zero_flow_field(point, field_name):
            return True
    return False


def _is_non_zero_flow_field(point: dict[str, Any], field_name: str) -> bool:
    try:
        return Decimal(str(point.get(field_name, 0) or 0)) != 0
    except (InvalidOperation, TypeError, ValueError):
        return False
