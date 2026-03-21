from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.stateful_position_row_service import split_position_cash_flows_in_value_basis


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
    ]

    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=cash_flows,
        row=row,
        value_basis="position",
    ) == (Decimal("5"), Decimal("-3"), Decimal("-1"))
    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=cash_flows,
        row=row,
        value_basis="portfolio",
    ) == (Decimal("6.00"), Decimal("-3.60"), Decimal("-1.20"))
    assert split_position_cash_flows_in_value_basis(
        cash_flows_raw=cash_flows,
        row=row,
        value_basis="reporting",
    ) == (Decimal("6.6000"), Decimal("-3.9600"), Decimal("-1.3200"))


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
