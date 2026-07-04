from __future__ import annotations

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

    if (
        stateful_both_currency_requires_fx(
            position_currencies=position_currencies,
            reporting_currency=reporting_currency,
        )
        and fx is None
    ):
        raise APIUnprocessableEntityError(
            detail=(
                f"Stateful {workflow_name} input requires fx.rates when currency_mode=BOTH and "
                "sourced positions include currencies different from report_ccy."
            ),
        )


def stateful_both_currency_requires_fx(
    *,
    position_currencies: set[str],
    reporting_currency: str,
) -> bool:
    normalized_reporting_currency = normalized_currency_code(reporting_currency)
    normalized_position_currencies = {
        normalized_position_currency
        for position_currency in position_currencies
        for normalized_position_currency in [normalized_currency_code(position_currency)]
        if normalized_position_currency is not None
    }
    return any(
        normalized_position_currency != normalized_reporting_currency
        for normalized_position_currency in normalized_position_currencies
    )


def stateful_position_currencies(rows: list[dict[str, object]]) -> set[str]:
    return {
        normalized_position_currency
        for row in rows
        for normalized_position_currency in [normalized_currency_code(row.get("position_currency"))]
        if normalized_position_currency is not None
    }
