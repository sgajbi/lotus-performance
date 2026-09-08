from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.currency_code_normalization import normalized_currency_code
from core.errors import APIUnprocessableEntityError


def validate_stateful_both_currency_support(
    *,
    rows: list[dict[str, object]],
    reporting_currency: str | None,
    fx: object,
    workflow_name: str,
) -> None:
    if not reporting_currency:
        raise APIUnprocessableEntityError(
            detail=f"Stateful {workflow_name} input requires report_ccy when currency_mode=BOTH.",
        )

    position_currencies = stateful_position_currencies(rows)
    if not position_currencies:
        raise APIUnprocessableEntityError(
            detail=(
                f"Stateful {workflow_name} input requires position_currency on "
                "lotus-core position-timeseries rows when currency_mode=BOTH."
            ),
        )

    required_currencies = _required_fx_currencies(
        position_currencies=position_currencies,
        reporting_currency=reporting_currency,
    )
    if not required_currencies:
        return

    missing_coverage = _missing_fx_coverage(
        rows=rows,
        required_currencies=required_currencies,
        reporting_currency=reporting_currency,
        fx=fx,
    )
    if missing_coverage:
        raise APIUnprocessableEntityError(
            detail=(
                f"Stateful {workflow_name} input requires fx.rates with complete positive finite EOD "
                "coverage when currency_mode=BOTH; missing " + "; ".join(missing_coverage) + "."
            ),
            error_code="FX_RATES_REQUIRED",
        )


def stateful_both_currency_requires_fx(
    *,
    position_currencies: set[str],
    reporting_currency: str,
) -> bool:
    return bool(
        _required_fx_currencies(
            position_currencies=position_currencies,
            reporting_currency=reporting_currency,
        )
    )


def _required_fx_currencies(*, position_currencies: set[str], reporting_currency: str) -> set[str]:
    normalized_reporting_currency = normalized_currency_code(reporting_currency)
    normalized_position_currencies = {
        normalized_position_currency
        for position_currency in position_currencies
        for normalized_position_currency in [normalized_currency_code(position_currency)]
        if normalized_position_currency is not None
    }
    return {
        normalized_position_currency
        for normalized_position_currency in normalized_position_currencies
        if normalized_position_currency != normalized_reporting_currency
    }


def _missing_fx_coverage(
    *,
    rows: list[dict[str, object]],
    required_currencies: set[str],
    reporting_currency: str,
    fx: object,
) -> list[str]:
    normalized_reporting_currency = normalized_currency_code(reporting_currency) or reporting_currency
    supplied_rates = _usable_fx_rates(fx)
    required_dates_by_currency = _required_fx_dates_by_currency(rows, required_currencies)
    missing: list[str] = []
    for currency in sorted(required_currencies):
        supplied_dates = supplied_rates.get(currency, set())
        required_dates = required_dates_by_currency.get(currency, set())
        if not required_dates and not supplied_dates:
            missing.append(f"{currency}/{normalized_reporting_currency}")
            continue
        missing_dates = sorted(required_dates - supplied_dates)
        if missing_dates:
            missing.append(
                f"{currency}/{normalized_reporting_currency} dates "
                + ", ".join(value.isoformat() for value in missing_dates)
            )
    return missing


def _usable_fx_rates(fx: object) -> dict[str, set[date]]:
    rates = fx.get("rates") if isinstance(fx, dict) else getattr(fx, "rates", None)
    if not isinstance(rates, list):
        return {}
    result: dict[str, set[date]] = {}
    for rate in rates:
        currency = normalized_currency_code(_rate_field(rate, "ccy"))
        rate_date = _date_value(_rate_field(rate, "date"))
        rate_value = _rate_field(rate, "rate")
        if currency is None or not isinstance(rate_date, date) or not _is_positive_finite_number(rate_value):
            continue
        result.setdefault(currency, set()).add(rate_date)
    return result


def _rate_field(rate: object, field_name: str) -> object:
    if isinstance(rate, dict):
        return rate.get(field_name)
    return getattr(rate, field_name, None)


def _required_fx_dates_by_currency(
    rows: list[dict[str, object]], required_currencies: set[str]
) -> dict[str, set[date]]:
    result: dict[str, set[date]] = {currency: set() for currency in required_currencies}
    for row in rows:
        currency = normalized_currency_code(row.get("position_currency"))
        valuation_date = _date_value(row.get("valuation_date"))
        if currency not in required_currencies or valuation_date is None:
            continue
        result[currency].update({valuation_date - timedelta(days=1), valuation_date})
    return result


def _date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_positive_finite_number(value: Any) -> bool:
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return numeric > 0 and numeric.is_finite()


def stateful_position_currencies(rows: list[dict[str, object]]) -> set[str]:
    return {
        normalized_position_currency
        for row in rows
        for normalized_position_currency in [normalized_currency_code(row.get("position_currency"))]
        if normalized_position_currency is not None
    }
