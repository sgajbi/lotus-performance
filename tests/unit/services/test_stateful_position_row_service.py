from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.stateful_position_row_service import (
    _cash_flow_conversion_factor,
    _decimal_or_one,
    _position_cash_flow_projection,
    split_position_cash_flows_in_value_basis,
)


def test_split_position_cash_flows_in_value_basis_converts_to_portfolio_and_reporting():
    row = {
        "position_currency": "EUR",
        "cash_flow_currency": "EUR",
        "position_to_portfolio_fx_rate": "1.20",
        "portfolio_to_reporting_fx_rate": "1.10",
    }
    cash_flows = [
        {"amount": "5", "timing": "bod"},
        {"amount": "-2", "timing": "eod"},
        {"amount": "-1", "timing": "eod", "cash_flow_type": "fee"},
        {"amount": "-0.5", "timing": "eod", "cash_flow_type": "management_fee"},
    ]

    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=cash_flows,
        row=row,
        value_basis="position",
    ) == (Decimal("5"), Decimal("-2"), Decimal("-1.5"))
    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=cash_flows,
        row=row,
        value_basis="portfolio",
    ) == (Decimal("6.00"), Decimal("-2.40"), Decimal("-1.80"))
    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=cash_flows,
        row=row,
        value_basis="reporting",
    ) == (Decimal("6.6000"), Decimal("-2.6400"), Decimal("-1.9800"))


def test_split_position_cash_flows_in_value_basis_rejects_unsupported_cash_flow_currency_mismatch():
    with pytest.raises(HTTPException, match="cash_flow_currency must match position_currency"):
        split_position_cash_flows_in_value_basis(
            cash_flows_raw=[{"amount": "5", "timing": "bod"}],
            row={
                "position_currency": "EUR",
                "cash_flow_currency": "USD",
                "position_to_portfolio_fx_rate": "1.20",
                "portfolio_to_reporting_fx_rate": "1.10",
            },
            value_basis="portfolio",
        )


def test_split_position_cash_flows_in_value_basis_ignores_non_list_and_non_usable_flows():
    row = {"position_to_portfolio_fx_rate": "1.5", "portfolio_to_reporting_fx_rate": "2.0"}

    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=None,
        row=row,
        value_basis="portfolio",
    ) == (Decimal("0"), Decimal("0"), Decimal("0"))

    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=[
            {"amount": None, "timing": "bod"},
            {"amount": "4", "timing": "mid"},
            "not-a-dict",
            {"amount": "3", "timing": "eod", "cash_flow_type": "dividend"},
        ],
        row=row,
        value_basis="position",
    ) == (Decimal("0"), Decimal("0"), Decimal("0"))


def test_split_position_cash_flows_in_value_basis_includes_internal_trade_flows():
    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=[
            {"amount": "10", "timing": "bod", "cash_flow_type": "internal_trade_flow"},
            {"amount": "-4", "timing": "eod", "cash_flow_type": "transfer"},
        ],
        row={},
        value_basis="position",
    ) == (Decimal("10"), Decimal("-4"), Decimal("0"))


def test_position_cash_flow_projection_normalizes_valid_flows_and_rejects_invalid_rows():
    fee_projection = _position_cash_flow_projection(
        {"amount": "-2", "timing": "eod", "cash_flow_type": "management_fee"},
        conversion_factor=Decimal("1.5"),
    )

    assert fee_projection is not None
    timing, amount, classification = fee_projection
    assert timing == "eod"
    assert amount == Decimal("-3.0")
    assert classification.economics_role == "fee"
    assert _position_cash_flow_projection("bad-row", conversion_factor=Decimal("1")) is None
    assert (
        _position_cash_flow_projection(
            {"amount": None, "timing": "bod"},
            conversion_factor=Decimal("1"),
        )
        is None
    )
    assert (
        _position_cash_flow_projection(
            {"amount": "1", "timing": "mid"},
            conversion_factor=Decimal("1"),
        )
        is None
    )


def test_cash_flow_conversion_factor_and_decimal_default_helpers_cover_missing_rates():
    assert _cash_flow_conversion_factor(row={}, value_basis="position") == Decimal("1")
    assert _cash_flow_conversion_factor(row={}, value_basis="portfolio") == Decimal("1")
    assert _cash_flow_conversion_factor(
        row={"position_to_portfolio_fx_rate": "1.25"},
        value_basis="portfolio",
    ) == Decimal("1.25")
    assert _cash_flow_conversion_factor(
        row={
            "position_to_portfolio_fx_rate": "1.25",
            "portfolio_to_reporting_fx_rate": "1.10",
        },
        value_basis="reporting",
    ) == Decimal("1.3750")
    assert _decimal_or_one(None) == Decimal("1")
    assert _decimal_or_one("1.125") == Decimal("1.125")


def test_cash_flow_conversion_factor_allows_missing_or_same_currency_metadata():
    row = {
        "cash_flow_currency": "USD",
        "position_currency": "USD",
        "position_to_portfolio_fx_rate": "0.80",
        "portfolio_to_reporting_fx_rate": "1.50",
    }

    assert _cash_flow_conversion_factor(row=row, value_basis="portfolio") == Decimal("0.80")
    assert _cash_flow_conversion_factor(row=row, value_basis="reporting") == Decimal("1.2000")
