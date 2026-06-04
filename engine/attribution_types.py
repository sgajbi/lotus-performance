from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Number = float


@dataclass
class AttributionResidualMateriality:
    classification: str
    treatment: str
    absolute_residual: Number
    warning_threshold: Number
    material_threshold: Number


@dataclass
class AttributionReason:
    code: str
    severity: str
    message: str
    affected_group_count: int = 0


@dataclass
class AttributionSupportabilityEvidence:
    portfolio_only_group_count: int = 0
    benchmark_only_group_count: int = 0
    unclassified_group_count: int = 0
    missing_benchmark_return_count: int = 0
    negative_weight_count: int = 0
    zero_portfolio_exposure_count: int = 0
    currency_attribution_status: str = "not_requested"
    linking_status: str = "not_requested"


@dataclass
class AttributionGroupResult:
    key: dict[str, Any]
    portfolio_weight_avg: Number
    benchmark_weight_avg: Number
    portfolio_return: Number
    benchmark_return: Number
    allocation: Number
    selection: Number
    interaction: Number
    total_effect: Number


@dataclass
class AttributionLevelTotals:
    allocation: Number
    selection: Number
    interaction: Number
    total_effect: Number


@dataclass
class AttributionLevelResult:
    dimension: str
    groups: list[AttributionGroupResult]
    totals: AttributionLevelTotals
    parent_key: dict[str, Any] | None = None


@dataclass
class Reconciliation:
    total_active_return: Number
    sum_of_effects: Number
    residual: Number
    residual_materiality: AttributionResidualMateriality


@dataclass
class CurrencyAttributionEffects:
    local_allocation: Number
    local_selection: Number
    currency_allocation: Number
    currency_selection: Number
    total_effect: Number


@dataclass
class CurrencyAttributionResult:
    currency: str
    weight_portfolio_avg: Number
    weight_benchmark_avg: Number
    effects: CurrencyAttributionEffects


@dataclass
class CurrencyAttributionTotals:
    local_allocation: Number
    local_selection: Number
    currency_allocation: Number
    currency_selection: Number
    total_effect: Number
    currency_count: int


@dataclass
class SinglePeriodAttributionResult:
    status: str
    reason_codes: list[str]
    reasons: list[AttributionReason]
    supportability_evidence: AttributionSupportabilityEvidence
    levels: list[AttributionLevelResult]
    reconciliation: Reconciliation
    currency_attribution: list[CurrencyAttributionResult] | None = None
    currency_attribution_totals: CurrencyAttributionTotals | None = None
