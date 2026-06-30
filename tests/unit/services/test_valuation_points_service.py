from decimal import Decimal

import pytest

from app.services.valuation_points_service import (
    _valuation_cashflow_component_for_role,
    _valuation_cashflow_total_component,
    _valuation_cashflow_totals,
    _valuation_point_from_observation,
    portfolio_timeseries_to_valuation_points,
)
from core.errors import APIError


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
    with pytest.raises(APIError) as exc:
        portfolio_timeseries_to_valuation_points(observations=[{"valuation_date": None}])

    assert exc.value.status_code == 422
    assert exc.value.detail == {
        "code": "INSUFFICIENT_DATA",
        "message": "No valid valuation observations after canonical normalization.",
    }


def test_valuation_point_from_observation_projects_decimal_values_and_cashflows():
    assert _valuation_point_from_observation(
        {
            "valuation_date": "2026-03-12",
            "beginning_market_value": "1200",
            "ending_market_value": "925",
            "cash_flows": [
                {"amount": "100", "timing": "bod", "cash_flow_type": "external_flow"},
                {"amount": "-10", "timing": "eod", "cash_flow_type": "fee"},
            ],
        }
    ) == {
        "perf_date": "2026-03-12",
        "begin_mv": Decimal("1200"),
        "end_mv": Decimal("925"),
        "bod_cf": Decimal("100"),
        "eod_cf": Decimal("0"),
        "mgmt_fees": Decimal("-10"),
    }


def test_valuation_point_from_observation_suppresses_incomplete_rows():
    assert _valuation_point_from_observation({"valuation_date": "2026-03-12", "beginning_market_value": "1200"}) is None
    assert (
        _valuation_point_from_observation(
            {"valuation_date": None, "beginning_market_value": "1200", "ending_market_value": "925"}
        )
        is None
    )


def test_valuation_cashflow_totals_classifies_fee_external_and_unsupported_flows():
    assert _valuation_cashflow_totals(
        [
            {"amount": "100", "timing": "bod", "cash_flow_type": "external_flow"},
            {"amount": "-25", "timing": "eod", "cash_flow_type": "withdrawal"},
            {"amount": "-3", "timing": "eod", "cash_flow_type": "fee"},
            {"amount": "2", "timing": "eod", "cash_flow_type": "dividend"},
        ]
    ) == (Decimal("100"), Decimal("-25"), Decimal("-3"))
    assert _valuation_cashflow_totals("not-a-list") == (Decimal("0"), Decimal("0"), Decimal("0"))


def test_valuation_cashflow_total_component_projects_supported_roles():
    assert _valuation_cashflow_total_component({"amount": "5", "timing": "bod"}) == (
        Decimal("5"),
        Decimal("0"),
        Decimal("0"),
    )
    assert _valuation_cashflow_total_component({"amount": "-4", "timing": "eod", "cash_flow_type": "withdrawal"}) == (
        Decimal("0"),
        Decimal("-4"),
        Decimal("0"),
    )
    assert _valuation_cashflow_total_component({"amount": "-2", "timing": "eod", "cash_flow_type": "fee"}) == (
        Decimal("0"),
        Decimal("0"),
        Decimal("-2"),
    )
    assert _valuation_cashflow_total_component({"amount": "3", "timing": "eod", "cash_flow_type": "dividend"}) == (
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
    )
    assert _valuation_cashflow_total_component({"amount": "3", "timing": "intraday"}) == (
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
    )
    assert _valuation_cashflow_total_component("not-a-flow") == (Decimal("0"), Decimal("0"), Decimal("0"))


def test_valuation_cashflow_component_for_role_routes_amounts_by_economics_role_and_timing():
    assert _valuation_cashflow_component_for_role(
        amount=Decimal("5"),
        timing="bod",
        economics_role="external",
    ) == (Decimal("5"), Decimal("0"), Decimal("0"))
    assert _valuation_cashflow_component_for_role(
        amount=Decimal("-4"),
        timing="eod",
        economics_role="external",
    ) == (Decimal("0"), Decimal("-4"), Decimal("0"))
    assert _valuation_cashflow_component_for_role(
        amount=Decimal("-2"),
        timing="eod",
        economics_role="fee",
    ) == (Decimal("0"), Decimal("0"), Decimal("-2"))
    assert _valuation_cashflow_component_for_role(
        amount=Decimal("3"),
        timing="eod",
        economics_role="unsupported",
    ) == (Decimal("0"), Decimal("0"), Decimal("0"))
