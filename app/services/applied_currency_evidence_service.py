from collections.abc import Iterable
from decimal import Decimal
from math import isfinite
from numbers import Real
from typing import cast

from app.models.currency_evidence import AppliedCurrencyEvidence
from app.services.currency_code_normalization import normalized_currency_code
from core.envelope import FXRequestBlock
from core.errors import APIUnprocessableEntityError


def build_applied_currency_evidence(
    *,
    portfolio_base_currency: str,
    requested_report_ccy: str | None,
    currency_mode: str | None,
    fx: FXRequestBlock | None,
    source_currencies: Iterable[object] = (),
) -> AppliedCurrencyEvidence:
    base_currency = _required_currency(portfolio_base_currency, field_name="portfolio base currency")
    report_currency = normalized_currency_code(requested_report_ccy)
    mode = currency_mode or "BASE_ONLY"
    normalized_sources = _normalized_source_currencies(source_currencies) or {base_currency}
    require_reporting_currency_for_both(currency_mode=mode, requested_report_ccy=report_currency)

    if mode == "LOCAL_ONLY":
        return _currency_evidence(
            base_currency=base_currency,
            report_currency=report_currency,
            applied_report_ccy=None,
            mode="LOCAL_ONLY",
            reason="LOCAL_CURRENCY_OUTPUT_APPLIED",
        )

    if mode != "BOTH":
        return _currency_evidence(
            base_currency=base_currency,
            report_currency=report_currency,
            applied_report_ccy=base_currency,
            mode="BASE_ONLY",
            reason="PORTFOLIO_BASE_CURRENCY_APPLIED",
        )

    report_currency = cast(str, report_currency)
    required_sources = normalized_sources - {report_currency}
    if not required_sources:
        return _currency_evidence(
            base_currency=base_currency,
            report_currency=report_currency,
            applied_report_ccy=report_currency,
            mode="BOTH",
            reason="REPORTING_CURRENCY_ALREADY_APPLIED",
        )

    _require_supplied_source_rates(required_sources=required_sources, report_currency=report_currency, fx=fx)
    return _currency_evidence(
        base_currency=base_currency,
        report_currency=report_currency,
        applied_report_ccy=report_currency,
        mode="BOTH",
        reason="CALLER_SUPPLIED_FX_APPLIED",
        required_sources=required_sources,
    )


def build_source_preconverted_currency_evidence(
    *,
    portfolio_base_currency: str,
    requested_report_ccy: str | None,
    currency_mode: str | None,
    source_currencies: Iterable[object],
    portfolio_observations: Iterable[object],
    benchmark_observations: Iterable[object],
) -> AppliedCurrencyEvidence:
    """Describe by-group returns, whose FX components are supplied rather than calculated here."""
    mode = currency_mode or "BASE_ONLY"
    if mode != "BOTH":
        return build_applied_currency_evidence(
            portfolio_base_currency=portfolio_base_currency,
            requested_report_ccy=requested_report_ccy,
            currency_mode=mode,
            fx=None,
            source_currencies=source_currencies,
        )

    base_currency, report_currency, normalized_sources = _source_preconverted_currency_context(
        portfolio_base_currency=portfolio_base_currency,
        requested_report_ccy=requested_report_ccy,
        source_currencies=source_currencies,
    )
    _require_preconverted_return_components(portfolio_observations, source_name="portfolio_groups_data")
    _require_preconverted_return_components(benchmark_observations, source_name="benchmark_groups_data")
    required_sources = normalized_sources - {base_currency}
    return AppliedCurrencyEvidence(
        portfolio_base_currency=base_currency,
        requested_report_ccy=report_currency,
        applied_report_ccy=base_currency,
        restated=bool(required_sources),
        currency_mode_applied="BOTH",
        fx_source="source_preconverted",
        fx_coverage="complete",
        fixing_policy="SOURCE_PRECONVERTED_RETURN_COMPONENTS",
        applied_pairs=[f"{currency}/{base_currency}" for currency in sorted(required_sources)],
        reason="SOURCE_PRECONVERTED_GROUP_RETURNS_APPLIED",
    )


def _source_preconverted_currency_context(
    *,
    portfolio_base_currency: str,
    requested_report_ccy: str | None,
    source_currencies: Iterable[object],
) -> tuple[str, str, set[str]]:
    base_currency = _required_currency(portfolio_base_currency, field_name="portfolio base currency")
    report_currency = normalized_currency_code(requested_report_ccy)
    require_reporting_currency_for_both(currency_mode="BOTH", requested_report_ccy=report_currency)
    report_currency = cast(str, report_currency)
    _require_source_preconverted_report_currency(base_currency=base_currency, report_currency=report_currency)
    return base_currency, report_currency, _required_source_currencies(source_currencies)


def _require_source_preconverted_report_currency(*, base_currency: str, report_currency: str) -> None:
    if report_currency == base_currency:
        return
    raise APIUnprocessableEntityError(
        detail=(
            "by_group currency_mode=BOTH consumes source-provided return_base, return_local, and return_fx "
            f"components in portfolio base currency {base_currency}; report_ccy={report_currency} cannot be "
            "used as evidence that an additional conversion was applied."
        ),
        error_code="FX_SOURCE_PRECONVERTED_REPORT_CURRENCY_MISMATCH",
    )


def _required_source_currencies(source_currencies: Iterable[object]) -> set[str]:
    normalized_source_values = [normalized_currency_code(value) for value in source_currencies]
    if normalized_source_values and all(currency is not None for currency in normalized_source_values):
        return {cast(str, currency) for currency in normalized_source_values}
    raise APIUnprocessableEntityError(
        detail="by_group currency_mode=BOTH requires a currency value in every portfolio and benchmark group key.",
        error_code="FX_SOURCE_CURRENCY_EVIDENCE_REQUIRED",
    )


def require_reporting_currency_for_both(*, currency_mode: str | None, requested_report_ccy: str | None) -> None:
    if currency_mode == "BOTH" and normalized_currency_code(requested_report_ccy) is None:
        raise APIUnprocessableEntityError(
            detail="currency_mode=BOTH requires report_ccy before currency conversion can be applied.",
            error_code="FX_REPORT_CURRENCY_REQUIRED",
        )


def _normalized_source_currencies(values: Iterable[object]) -> set[str]:
    return {currency for value in values for currency in [normalized_currency_code(value)] if currency is not None}


def _require_supplied_source_rates(
    *, required_sources: set[str], report_currency: str, fx: FXRequestBlock | None
) -> None:
    supplied_sources = {
        currency
        for rate in (fx.rates if fx is not None else [])
        for currency in [normalized_currency_code(rate.ccy)]
        if currency is not None
    }
    missing_sources = sorted(required_sources - supplied_sources)
    if missing_sources:
        missing_pairs = ", ".join(f"{currency}/{report_currency}" for currency in missing_sources)
        raise APIUnprocessableEntityError(
            detail=f"Applied currency evidence cannot be published because fx.rates lack {missing_pairs}.",
            error_code="FX_RATES_REQUIRED",
        )


def _require_preconverted_return_components(observations: Iterable[object], *, source_name: str) -> None:
    rows = list(observations)
    _require_complete_preconverted_return_components(rows, source_name=source_name)
    _require_reconciled_preconverted_return_components(rows, source_name=source_name)


def _require_complete_preconverted_return_components(rows: list[object], *, source_name: str) -> None:
    required_fields = ("return_base", "return_local", "return_fx")
    incomplete_rows = [
        index
        for index, observation in enumerate(rows)
        if any(not _is_finite_return(_observation_value(observation, field_name)) for field_name in required_fields)
    ]
    if not rows or incomplete_rows:
        detail = "no observations" if not rows else f"incomplete observations at indexes {incomplete_rows}"
        raise APIUnprocessableEntityError(
            detail=(
                f"by_group currency_mode=BOTH requires source-provided return_base, return_local, and return_fx "
                f"for every {source_name} observation; found {detail}."
            ),
            error_code="FX_SOURCE_PRECONVERTED_EVIDENCE_REQUIRED",
        )


def _require_reconciled_preconverted_return_components(rows: list[object], *, source_name: str) -> None:
    unreconciled_rows = [
        index for index, observation in enumerate(rows) if not _return_components_reconcile(observation)
    ]
    if unreconciled_rows:
        raise APIUnprocessableEntityError(
            detail=(
                "by_group currency_mode=BOTH requires return_base = "
                "(1 + return_local) * (1 + return_fx) - 1 within 1e-12 for every "
                f"{source_name} observation; inconsistent observations at indexes {unreconciled_rows}."
            ),
            error_code="FX_SOURCE_PRECONVERTED_EVIDENCE_INCONSISTENT",
        )


def _observation_value(observation: object, field_name: str) -> object:
    if isinstance(observation, dict):
        return observation.get(field_name)
    return getattr(observation, field_name, None)


def _is_finite_return(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def _return_components_reconcile(observation: object) -> bool:
    base = Decimal(str(_observation_value(observation, "return_base")))
    local = Decimal(str(_observation_value(observation, "return_local")))
    fx = Decimal(str(_observation_value(observation, "return_fx")))
    expected_base = (Decimal(1) + local) * (Decimal(1) + fx) - Decimal(1)
    return abs(base - expected_base) <= Decimal("0.000000000001")


def _currency_evidence(
    *,
    base_currency: str,
    report_currency: str | None,
    applied_report_ccy: str | None,
    mode: str,
    reason: str,
    required_sources: set[str] | None = None,
) -> AppliedCurrencyEvidence:
    restated = bool(required_sources)
    return AppliedCurrencyEvidence(
        portfolio_base_currency=base_currency,
        requested_report_ccy=report_currency,
        applied_report_ccy=applied_report_ccy,
        restated=restated,
        currency_mode_applied=mode,
        fx_source="caller_supplied" if restated else "none",
        fx_coverage="complete" if restated else "none",
        fixing_policy="EOD_EXACT_PRIOR_AND_CURRENT",
        applied_pairs=[f"{currency}/{report_currency}" for currency in sorted(required_sources or set())],
        reason=reason,
    )


def _required_currency(value: object, *, field_name: str) -> str:
    currency = normalized_currency_code(value)
    if currency is None:
        raise APIUnprocessableEntityError(detail=f"A valid {field_name} is required for applied currency evidence.")
    return currency
