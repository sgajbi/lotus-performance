from __future__ import annotations

from app.models.attribution_responses import (
    AttributionGroupResult,
    AttributionLevelResult,
    AttributionLevelTotals,
    AttributionReason,
    AttributionResidualMateriality,
    AttributionSupportabilityEvidence,
    CurrencyAttributionEffects,
    CurrencyAttributionResult,
    CurrencyAttributionTotals,
    Reconciliation,
    SinglePeriodAttributionResult,
)
from engine import attribution_types


def build_single_period_attribution_response(
    result: attribution_types.SinglePeriodAttributionResult,
) -> SinglePeriodAttributionResult:
    currency_attribution, currency_attribution_totals = _build_currency_attribution_response(result)
    return SinglePeriodAttributionResult(
        status=result.status,
        reason_codes=result.reason_codes,
        reasons=[_build_reason_response(reason) for reason in result.reasons],
        supportability_evidence=_build_supportability_response(result.supportability_evidence),
        levels=[_build_level_response(level) for level in result.levels],
        reconciliation=_build_reconciliation_response(result.reconciliation),
        currency_attribution=currency_attribution,
        currency_attribution_totals=currency_attribution_totals,
    )


def _build_reason_response(reason: attribution_types.AttributionReason) -> AttributionReason:
    return AttributionReason(
        code=reason.code,
        severity=reason.severity,
        message=reason.message,
        affected_group_count=reason.affected_group_count,
    )


def _build_supportability_response(
    evidence: attribution_types.AttributionSupportabilityEvidence,
) -> AttributionSupportabilityEvidence:
    return AttributionSupportabilityEvidence(
        portfolio_only_group_count=evidence.portfolio_only_group_count,
        benchmark_only_group_count=evidence.benchmark_only_group_count,
        unclassified_group_count=evidence.unclassified_group_count,
        missing_benchmark_return_count=evidence.missing_benchmark_return_count,
        negative_weight_count=evidence.negative_weight_count,
        zero_portfolio_exposure_count=evidence.zero_portfolio_exposure_count,
        currency_attribution_status=evidence.currency_attribution_status,
        linking_status=evidence.linking_status,
    )


def _build_group_response(group: attribution_types.AttributionGroupResult) -> AttributionGroupResult:
    return AttributionGroupResult(
        key=group.key,
        portfolio_weight_avg=group.portfolio_weight_avg,
        benchmark_weight_avg=group.benchmark_weight_avg,
        portfolio_return=group.portfolio_return,
        benchmark_return=group.benchmark_return,
        allocation=group.allocation,
        selection=group.selection,
        interaction=group.interaction,
        total_effect=group.total_effect,
    )


def _build_totals_response(totals: attribution_types.AttributionLevelTotals) -> AttributionLevelTotals:
    return AttributionLevelTotals(
        allocation=totals.allocation,
        selection=totals.selection,
        interaction=totals.interaction,
        total_effect=totals.total_effect,
    )


def _build_level_response(level: attribution_types.AttributionLevelResult) -> AttributionLevelResult:
    return AttributionLevelResult(
        dimension=level.dimension,
        parent_key=level.parent_key,
        groups=[_build_group_response(group) for group in level.groups],
        totals=_build_totals_response(level.totals),
    )


def _build_residual_response(
    residual: attribution_types.AttributionResidualMateriality,
) -> AttributionResidualMateriality:
    return AttributionResidualMateriality(
        classification=residual.classification,
        treatment=residual.treatment,
        absolute_residual=residual.absolute_residual,
        warning_threshold=residual.warning_threshold,
        material_threshold=residual.material_threshold,
    )


def _build_reconciliation_response(reconciliation: attribution_types.Reconciliation) -> Reconciliation:
    return Reconciliation(
        total_active_return=reconciliation.total_active_return,
        sum_of_effects=reconciliation.sum_of_effects,
        residual=reconciliation.residual,
        residual_materiality=_build_residual_response(reconciliation.residual_materiality),
    )


def _build_currency_effects_response(
    effects: attribution_types.CurrencyAttributionEffects,
) -> CurrencyAttributionEffects:
    return CurrencyAttributionEffects(
        local_allocation=effects.local_allocation,
        local_selection=effects.local_selection,
        currency_allocation=effects.currency_allocation,
        currency_selection=effects.currency_selection,
        total_effect=effects.total_effect,
    )


def _build_currency_result_response(
    result: attribution_types.CurrencyAttributionResult,
) -> CurrencyAttributionResult:
    return CurrencyAttributionResult(
        currency=result.currency,
        weight_portfolio_avg=result.weight_portfolio_avg,
        weight_benchmark_avg=result.weight_benchmark_avg,
        effects=_build_currency_effects_response(result.effects),
    )


def _build_currency_totals_response(
    totals: attribution_types.CurrencyAttributionTotals,
) -> CurrencyAttributionTotals:
    return CurrencyAttributionTotals(
        local_allocation=totals.local_allocation,
        local_selection=totals.local_selection,
        currency_allocation=totals.currency_allocation,
        currency_selection=totals.currency_selection,
        total_effect=totals.total_effect,
        currency_count=totals.currency_count,
    )


def _build_currency_attribution_response(
    result: attribution_types.SinglePeriodAttributionResult,
) -> tuple[list[CurrencyAttributionResult] | None, CurrencyAttributionTotals | None]:
    currency_attribution = (
        [_build_currency_result_response(item) for item in result.currency_attribution]
        if result.currency_attribution is not None
        else None
    )
    currency_attribution_totals = (
        _build_currency_totals_response(result.currency_attribution_totals)
        if result.currency_attribution_totals is not None
        else None
    )
    return currency_attribution, currency_attribution_totals
