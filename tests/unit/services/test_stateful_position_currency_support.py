from __future__ import annotations

import pytest

from app.services.stateful_position_currency_support import (
    stateful_both_currency_requires_fx,
    stateful_position_currencies,
    validate_stateful_both_currency_support,
)
from core.envelope import FXRequestBlock
from core.errors import APIError


def test_validate_stateful_both_currency_support_uses_workflow_specific_error_text() -> None:
    with pytest.raises(APIError, match="Stateful contribution input requires report_ccy"):
        validate_stateful_both_currency_support(
            rows=[],
            reporting_currency=None,
            fx=None,
            workflow_name="contribution",
        )

    with pytest.raises(APIError, match="Stateful attribution input requires position_currency"):
        validate_stateful_both_currency_support(
            rows=[{"position_id": "POS_1"}],
            reporting_currency="USD",
            fx=None,
            workflow_name="attribution",
        )

    with pytest.raises(APIError, match="Stateful attribution input requires fx.rates"):
        validate_stateful_both_currency_support(
            rows=[{"position_id": "POS_1", "position_currency": "EUR"}],
            reporting_currency="USD",
            fx=None,
            workflow_name="attribution",
        )


def test_stateful_both_currency_support_accepts_normalized_reporting_currency_rows_without_fx() -> None:
    validate_stateful_both_currency_support(
        rows=[
            {"position_id": "POS_1", "position_currency": " usd "},
            {"position_id": "POS_2", "position_currency": "Usd"},
        ],
        reporting_currency=" usd ",
        fx=None,
        workflow_name="contribution",
    )


def test_stateful_position_currency_helpers_normalize_codes_and_ignore_blank_values() -> None:
    rows = [
        {"position_id": "POS_1", "position_currency": " eur "},
        {"position_id": "POS_2", "position_currency": " "},
        {"position_id": "POS_3", "position_currency": ""},
        {"position_id": "POS_4", "position_currency": None},
        {"position_id": "POS_5", "position_currency": 123},
        {"position_id": "POS_6", "position_currency": "usd"},
        {"position_id": "POS_7", "position_currency": "UsD"},
    ]

    assert stateful_position_currencies(rows) == {"EUR", "USD"}
    assert (
        stateful_both_currency_requires_fx(
            position_currencies={" usd ", "Usd"},
            reporting_currency="USD",
        )
        is False
    )
    assert (
        stateful_both_currency_requires_fx(
            position_currencies={"usd", "EUR"},
            reporting_currency=" usd ",
        )
        is True
    )


def test_validate_stateful_both_currency_support_treats_blank_source_currency_as_missing() -> None:
    with pytest.raises(APIError, match="requires position_currency"):
        validate_stateful_both_currency_support(
            rows=[
                {"position_id": "POS_1", "position_currency": ""},
                {"position_id": "POS_2", "position_currency": " "},
            ],
            reporting_currency="USD",
            fx=None,
            workflow_name="contribution",
        )


def test_stateful_both_currency_support_refuses_empty_and_partial_fx_coverage_with_pairs_and_dates() -> None:
    rows = [
        {"position_currency": "EUR", "valuation_date": "2025-01-02"},
        {"position_currency": "JPY", "valuation_date": "2025-01-02"},
    ]
    with pytest.raises(APIError, match=r"EUR/USD dates 2025-01-01, 2025-01-02.*JPY/USD dates"):
        validate_stateful_both_currency_support(
            rows=rows,
            reporting_currency="USD",
            fx=FXRequestBlock(rates=[]),
            workflow_name="contribution",
        )

    partial = FXRequestBlock.model_validate(
        {
            "rates": [
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.1},
                {"date": "2025-01-02", "ccy": "EUR", "rate": 1.2},
            ]
        }
    )
    with pytest.raises(APIError, match=r"JPY/USD dates 2025-01-01, 2025-01-02"):
        validate_stateful_both_currency_support(
            rows=rows,
            reporting_currency="USD",
            fx=partial,
            workflow_name="attribution",
        )


def test_stateful_both_currency_support_accepts_complete_multi_currency_exact_eod_coverage() -> None:
    rows = [
        {"position_currency": "EUR", "valuation_date": "2025-01-02"},
        {"position_currency": "JPY", "valuation_date": "2025-01-02"},
    ]
    fx = FXRequestBlock.model_validate(
        {
            "rates": [
                {"date": rate_date, "ccy": currency, "rate": rate}
                for currency, rates in {"EUR": (1.1, 1.2), "JPY": (0.006, 0.0061)}.items()
                for rate_date, rate in zip(("2025-01-01", "2025-01-02"), rates)
            ]
        }
    )

    validate_stateful_both_currency_support(
        rows=rows,
        reporting_currency="USD",
        fx=fx,
        workflow_name="contribution",
    )
