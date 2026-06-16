from app.services.attribution_response_service import (
    _build_currency_attribution_response,
    build_single_period_attribution_response,
)
from engine import attribution_types


def _single_period_result(
    *,
    currency_attribution: list[attribution_types.CurrencyAttributionResult] | None = None,
    currency_attribution_totals: attribution_types.CurrencyAttributionTotals | None = None,
) -> attribution_types.SinglePeriodAttributionResult:
    return attribution_types.SinglePeriodAttributionResult(
        status="valid",
        reason_codes=[],
        reasons=[],
        supportability_evidence=attribution_types.AttributionSupportabilityEvidence(),
        levels=[],
        reconciliation=attribution_types.Reconciliation(
            total_active_return=0.01,
            sum_of_effects=0.01,
            residual=0.0,
            residual_materiality=attribution_types.AttributionResidualMateriality(
                classification="immaterial",
                treatment="no_action",
                absolute_residual=0.0,
                warning_threshold=0.0001,
                material_threshold=0.001,
            ),
        ),
        currency_attribution=currency_attribution,
        currency_attribution_totals=currency_attribution_totals,
    )


def test_build_currency_attribution_response_preserves_omitted_currency_mode():
    assert _build_currency_attribution_response(_single_period_result()) == (None, None)


def test_build_currency_attribution_response_projects_results_and_totals():
    effects = attribution_types.CurrencyAttributionEffects(0.01, 0.02, 0.03, 0.04, 0.1)
    currency_result = attribution_types.CurrencyAttributionResult("USD", 0.6, 0.5, effects)
    totals = attribution_types.CurrencyAttributionTotals(0.01, 0.02, 0.03, 0.04, 0.1, 1)

    projected_results, projected_totals = _build_currency_attribution_response(
        _single_period_result(currency_attribution=[currency_result], currency_attribution_totals=totals)
    )

    assert projected_results is not None
    assert projected_results[0].currency == "USD"
    assert projected_results[0].effects.total_effect == 0.1
    assert projected_totals is not None
    assert projected_totals.currency_count == 1


def test_build_single_period_attribution_response_preserves_core_response_fields():
    response = build_single_period_attribution_response(_single_period_result())

    assert response.status == "valid"
    assert response.reconciliation.total_active_return == 0.01
    assert response.currency_attribution is None
    assert response.currency_attribution_totals is None
