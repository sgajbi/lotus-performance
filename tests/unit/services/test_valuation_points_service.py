from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points


def test_portfolio_timeseries_to_valuation_points_preserves_fee_cashflows_as_mgmt_fees():
    points = portfolio_timeseries_to_valuation_points(
        observations=[
            {
                "valuation_date": "2026-03-12",
                "beginning_market_value": "1200",
                "ending_market_value": "925",
                "cash_flows": [
                    {"amount": "-10", "timing": "eod", "cash_flow_type": "fee"},
                    {
                        "amount": "-275",
                        "timing": "eod",
                        "cash_flow_type": "fee",
                        "flow_scope": "operational",
                        "source_classification": "EXPENSE",
                    },
                    {"amount": "100", "timing": "bod", "cash_flow_type": "external_flow"},
                    {"amount": "-25", "timing": "eod", "cash_flow_type": "withdrawal"},
                    {"amount": "3", "timing": "eod", "cash_flow_type": "dividend"},
                ],
            }
        ]
    )

    assert points == [
        {
            "perf_date": "2026-03-12",
            "begin_mv": Decimal("1200"),
            "end_mv": Decimal("925"),
            "bod_cf": Decimal("100"),
            "eod_cf": Decimal("-25"),
            "mgmt_fees": Decimal("-285"),
        }
    ]


def test_portfolio_timeseries_to_valuation_points_does_not_whitelist_expense_cashflow_type():
    points = portfolio_timeseries_to_valuation_points(
        observations=[
            {
                "valuation_date": "2026-03-12",
                "beginning_market_value": "1200",
                "ending_market_value": "925",
                "cash_flows": [
                    {"amount": "-275", "timing": "eod", "cash_flow_type": "expense"},
                ],
            }
        ]
    )

    assert points[0]["mgmt_fees"] == Decimal("0")
    assert points[0]["bod_cf"] == Decimal("0")
    assert points[0]["eod_cf"] == Decimal("0")


def test_portfolio_timeseries_to_valuation_points_keeps_unlabeled_cashflows_as_external_for_compatibility():
    points = portfolio_timeseries_to_valuation_points(
        observations=[
            {
                "valuation_date": "2026-03-13",
                "beginning_market_value": "100",
                "ending_market_value": "102",
                "cash_flows": [
                    {"amount": "1.2", "timing": "bod"},
                    {"amount": "0.3", "timing": "eod", "cash_flow_type": "   "},
                ],
            }
        ]
    )

    assert points[0]["bod_cf"] == Decimal("1.2")
    assert points[0]["eod_cf"] == Decimal("0.3")
    assert points[0]["mgmt_fees"] == Decimal("0")


def test_portfolio_timeseries_to_valuation_points_rejects_empty_valid_observations():
    with pytest.raises(HTTPException) as exc:
        portfolio_timeseries_to_valuation_points(observations=[{"valuation_date": None}])

    assert exc.value.status_code == 422
