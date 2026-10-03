"""Exact monetary request admission, distinct from numerical return solvers."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.mwr_requests import CashFlow, MoneyWeightedReturnRequest
from core.envelope import Annualization, FXRate
from engine.mwr import _compounded_percentage_return, _xirr, calculate_money_weighted_return
from engine.numerical_boundary import finite_float64_projection, monetary_arithmetic_context


def test_mwr_schedule_retains_exact_decimal_money():
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "DECIMAL_BOUNDARY_CONTROL",
            "start_date": "2024-01-01",
            "as_of": "2025-01-01",
            "begin_mv": "100.00",
            "end_mv": "9007199254741093.02",
            "cash_flows": [{"amount": "9007199254740993.01", "date": "2025-01-01"}],
        }
    )
    assert isinstance(request.begin_mv, Decimal)
    assert isinstance(request.end_mv, Decimal)
    assert isinstance(request.cash_flows[0].amount, Decimal)
    assert request.end_mv - request.begin_mv - request.cash_flows[0].amount == Decimal("0.01")
    assert request.model_dump(mode="json")["cash_flows"][0]["amount"] == "9007199254740993.01"


def test_xirr_refuses_overflowing_gross_solver_scale_from_finite_coefficients():
    import numpy as np

    with pytest.raises(ValueError, match="finite float64 numerical domain"):
        _xirr(np.array([-1e308, 1e308]), np.array([date(2025, 1, 1), date(2026, 1, 1)]))


def test_fx_request_preserves_exact_admitted_rate():
    rate = FXRate(date=date(2024, 1, 1), ccy="EUR", rate="1.123456789012")
    assert isinstance(rate.rate, Decimal)
    assert rate.rate == Decimal("1.123456789012")
    assert rate.model_dump(mode="json")["rate"] == "1.123456789012"


def test_modified_dietz_preserves_small_profit_beside_large_end_date_inflow():
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "DECIMAL_BOUNDARY_CONTROL",
            "start_date": "2024-01-01",
            "as_of": "2025-01-01",
            "begin_mv": "100.00",
            "end_mv": "9007199254741093.02",
            "mwr_method": "MODIFIED_DIETZ",
            "cash_flows": [{"amount": "9007199254740993.01", "date": "2025-01-01"}],
        }
    )
    result = calculate_money_weighted_return(
        begin_mv=request.begin_mv,
        end_mv=request.end_mv,
        cash_flows=request.cash_flows,
        calculation_method=request.mwr_method,
        annualization=request.annualization,
        as_of=request.as_of,
        start_date=request.start_date,
    )
    # Profit = end - begin - inflow = 0.01. End-date inflow weight is zero.
    # Modified Dietz return = 0.01 / 100 = 0.0001 = 0.01 percentage points.
    assert result.mwr == pytest.approx(0.01, rel=1e-12, abs=1e-14)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", True, False])
def test_cash_flow_rejects_nonfinancial_input(amount):
    with pytest.raises(ValidationError):
        CashFlow(amount=amount, date=date(2024, 1, 1))


@pytest.mark.parametrize("amount", ["0.1", 0.1, 1, "-12.34", Decimal("123.4500")])
def test_cash_flow_accepts_valid_signed_or_numeric_compatibility_input(amount):
    cash_flow = CashFlow(amount=amount, date=date(2024, 1, 1))
    assert cash_flow.amount == Decimal(str(amount))


@pytest.mark.parametrize("amount", [2**53 * 1.0, -(2**53 * 1.0), "0.000000001", None])
def test_cash_flow_refuses_unsafe_projection_or_excess_money_scale(amount):
    with pytest.raises(ValidationError):
        CashFlow(amount=amount, date=date(2024, 1, 1))


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", "Infinity", True, "1.0000000000001"])
def test_fx_request_refuses_invalid_rate_or_excess_scale(rate):
    with pytest.raises(ValidationError):
        FXRate(date=date(2024, 1, 1), ccy="EUR", rate=rate)


@pytest.mark.parametrize("value", [Decimal("1e1000"), Decimal("1e-1000"), Decimal("Infinity"), Decimal("NaN")])
def test_float64_numerical_boundary_refuses_overflow_underflow_and_nonfinite(value):
    with pytest.raises(ValueError):
        finite_float64_projection(value)


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1.25"), Decimal("1.125")])
def test_float64_numerical_boundary_accepts_valid_values(value):
    assert finite_float64_projection(value) == float(value)


def test_decimal_arithmetic_context_preserves_large_opposing_money_and_restores_ambient_precision():
    from decimal import getcontext

    original_precision = getcontext().prec
    positive = Decimal("9007199254740993000000000000000093.01")
    negative = Decimal("-9007199254740993000000000000000093.00")
    with monetary_arithmetic_context([positive, negative]):
        assert positive + negative == Decimal("0.01")
        assert getcontext().prec > original_precision
    assert getcontext().prec == original_precision


@pytest.mark.parametrize("value", [Decimal("1e1000000000"), Decimal("1e-1000000000"), Decimal("NaN")])
def test_decimal_arithmetic_context_refuses_unbounded_span_or_nonfinite(value):
    with pytest.raises(ValueError):
        with monetary_arithmetic_context([value]):
            raise AssertionError("Unbounded input reached arithmetic")


def test_dietz_refuses_percentage_overflow_even_when_ratio_is_finite():
    # Ratio is approximately1e307 (finite); percentage1e309 cannot be a finite JSON number.
    with pytest.raises(ValueError, match="finite float64 numerical domain"):
        calculate_money_weighted_return(
            begin_mv=Decimal("100"),
            end_mv=Decimal("1e309"),
            cash_flows=[],
            calculation_method="MODIFIED_DIETZ",
            annualization=Annualization(enabled=False),
            start_date=date(2025, 1, 1),
            as_of=date(2026, 1, 1),
        )


@pytest.mark.parametrize(("ratio", "scale"), [(99.0, 365.0), (-2.0, 0.5)])
def test_compounded_percentage_refuses_overflow_or_nonreal_domain(ratio, scale):
    with pytest.raises(ValueError, match="numerical domain"):
        _compounded_percentage_return(ratio, scale)


def test_compounded_percentage_accepts_independent_two_period_growth():
    assert _compounded_percentage_return(0.1, 2) == pytest.approx(21)


def test_raw_json_decimal_string_preserves_precision_and_unsafe_numeric_refuses():
    exact = CashFlow.model_validate_json('{"amount":"9007199254740993.01","date":"2024-01-01"}')
    assert exact.amount == Decimal("9007199254740993.01")
    with pytest.raises(ValidationError):
        CashFlow.model_validate_json('{"amount":9007199254740993.01,"date":"2024-01-01"}')


def test_decimal_conversion_retains_both_large_coefficients():
    amount = Decimal("1234567890123456789012345678901234567890.12")
    rate = Decimal("987654321098765432109876543210.123456789012")
    # Independent integer multiplication, then placement of the 2 + 12 decimal
    # digits. Decimal construction itself does not use ambient arithmetic precision.
    coefficient = int("123456789012345678901234567890123456789012") * int("987654321098765432109876543210123456789012")
    expected = Decimal((0, tuple(int(digit) for digit in str(coefficient)), -14))
    with monetary_arithmetic_context([amount, rate], products=True):
        assert amount * rate == expected


@pytest.mark.parametrize("positive", ["9007199254740993.01", "9007199254740993000000000000000093.01"])
def test_xirr_nets_signed_same_date_money_before_float64_projection(positive):
    negative = "-" + positive[:-2] + "00"
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "SIGNED_CANCELLATION_CONTROL",
            "start_date": "2025-01-01",
            "as_of": "2026-01-01",
            "begin_mv": "100.00",
            "end_mv": "110.01",
            "cash_flows": [
                {"amount": positive, "date": "2026-01-01"},
                {"amount": negative, "date": "2026-01-01"},
            ],
            "annualization": {"basis": "ACT/365"},
        }
    )
    result = calculate_money_weighted_return(
        begin_mv=request.begin_mv,
        end_mv=request.end_mv,
        cash_flows=request.cash_flows,
        calculation_method="XIRR",
        annualization=request.annualization,
        as_of=request.as_of,
        start_date=request.start_date,
    )
    # Exact end-date net investment is 0.01. Terminal economics = 110.01 - 0.01 = 110.
    # One natural year, no intervening net investment: 110 / 100 - 1 = 10%.
    assert result.method == "XIRR"
    assert result.status == "CALCULATED"
    assert result.mwr == pytest.approx(10, abs=1e-6)
