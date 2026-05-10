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

    cash_flow_type_counts = _cash_flow_type_counts(request)
    available_economics = _available_stateful_economics(request, cash_flow_type_counts)
    unsupported_economics = _unsupported_component_pnl_fields(request)
    degraded_economics = _degraded_stateful_economics(
        request=request,
        cash_flow_type_counts=cash_flow_type_counts,
        upstream_snapshots=upstream_snapshots,
    )
    reason_codes = _stateful_reason_codes(
        unsupported_economics=unsupported_economics,
        degraded_economics=degraded_economics,
        upstream_snapshots=upstream_snapshots,
    )
    status: Literal["SOURCE_BACKED", "SOURCE_LIMITED"]
    status = "SOURCE_LIMITED" if degraded_economics or unsupported_economics else "SOURCE_BACKED"

    return ContributionSourceEconomicsEvidence(
        input_mode="stateful",
        source_owner="lotus-core",
        status=status,
        reason_codes=reason_codes,
        source_contracts=["PortfolioTimeseriesInput:v1", "PositionTimeseriesInput:v1"],
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
    if any(
        _has_non_zero_flow(point.model_dump(mode="python"))
        for position in request.positions_data
        for point in position.valuation_points
    ):
        available.append("caller_supplied_position_flows")
    if any(position.meta.get("currency") for position in request.positions_data):
        available.append("position_currency")
    return sorted(set(available))


def _available_stateful_economics(
    request: ContributionRequest,
    cash_flow_type_counts: Counter[str],
) -> list[str]:
    available = ["portfolio_market_values", "position_market_values"]
    if cash_flow_type_counts.get("external_flow", 0) > 0 or cash_flow_type_counts.get("transfer", 0) > 0:
        available.append("external_flows")
    if cash_flow_type_counts.get("internal_trade_flow", 0) > 0:
        available.append("internal_trade_flows")
    if cash_flow_type_counts.get("fee", 0) > 0:
        available.append("fees")
    if any(_has_fx_metadata(position.meta) for position in request.positions_data):
        available.append("fx_rates")
    if _classification_dimensions(request):
        available.append("classification_dimensions")
    return sorted(set(available))


def _unsupported_component_pnl_fields(request: ContributionRequest) -> list[str]:
    present_component_fields = {
        field_name
        for position in request.positions_data
        for field_name in _COMPONENT_PNL_FIELDS
        if field_name in position.meta
    }
    return [field_name for field_name in _COMPONENT_PNL_FIELDS if field_name not in present_component_fields]


def _degraded_stateful_economics(
    *,
    request: ContributionRequest,
    cash_flow_type_counts: Counter[str],
    upstream_snapshots: list[UpstreamSnapshotRecord],
) -> list[str]:
    degraded: set[str] = set()
    unsupported_flow_count = sum(
        count
        for flow_type, count in cash_flow_type_counts.items()
        if flow_type not in {"external_flow", "internal_trade_flow", "transfer", "fee", "missing"}
    )
    if unsupported_flow_count > 0:
        degraded.add("unsupported_cash_flow_types")
    if any("Unclassified" in position.meta.values() for position in request.positions_data):
        degraded.add("missing_classification")
    if not upstream_snapshots:
        degraded.add("upstream_snapshot_lineage_not_embedded")
    return sorted(degraded)


def _stateful_reason_codes(
    *,
    unsupported_economics: list[str],
    degraded_economics: list[str],
    upstream_snapshots: list[UpstreamSnapshotRecord],
) -> list[str]:
    reason_codes = ["LOTUS_CORE_ANALYTICS_INPUTS_USED"]
    if unsupported_economics:
        reason_codes.append("COMPONENT_PNL_NOT_SOURCE_AUTHORED")
    if "unsupported_cash_flow_types" in degraded_economics:
        reason_codes.append("UNSUPPORTED_SOURCE_CASH_FLOW_TYPES_PRESENT")
    if "missing_classification" in degraded_economics:
        reason_codes.append("UNCLASSIFIED_POSITION_ECONOMICS_PRESENT")
    if upstream_snapshots:
        reason_codes.append("UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE")
    else:
        reason_codes.append("UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE_VIA_EXECUTION_ONLY")
    return sorted(set(reason_codes))


def _cash_flow_type_counts(request: ContributionRequest) -> Counter[str]:
    counts: Counter[str] = Counter()
    for position in request.positions_data:
        source_economics = position.meta.get("_source_economics")
        if not isinstance(source_economics, dict):
            continue
        raw_counts = source_economics.get("cash_flow_type_counts")
        if not isinstance(raw_counts, dict):
            continue
        for key, value in raw_counts.items():
            if isinstance(key, str) and isinstance(value, int) and value > 0:
                counts[key] += value
    return counts


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
        try:
            if Decimal(str(point.get(field_name, 0) or 0)) != 0:
                return True
        except (InvalidOperation, TypeError, ValueError):
            continue
    return False
