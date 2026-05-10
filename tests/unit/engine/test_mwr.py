# tests/unit/engine/test_mwr.py
from datetime import date

import numpy as np
import pytest

from app.models.mwr_requests import CashFlow
from core.envelope import Annualization
from engine.mwr import _xirr, calculate_money_weighted_return


@pytest.mark.parametrize(
    "begin_mv, end_mv, cash_flows, as_of, expected_mwr",
    [
        (100.0, 110.0, [], date(2025, 12, 31), 10.0),
        (
            100000.0,
            115000.0,
            [
                CashFlow(amount=10000.0, date=date(2025, 3, 15)),
                CashFlow(amount=-5000.0, date=date(2025, 9, 20)),
            ],
            date(2025, 12, 31),
            9.756097,
        ),
        (100.0, 110.0, [CashFlow(amount=-100.0, date=date(2025, 1, 1))], date(2025, 12, 31), 220.0),
    ],
)
def test_calculate_mwr_dietz(begin_mv, end_mv, cash_flows, as_of, expected_mwr):
    """Tests the Simple Dietz calculation."""
    result = calculate_money_weighted_return(begin_mv, end_mv, cash_flows, "DIETZ", Annualization(enabled=False), as_of)
    assert result.mwr == pytest.approx(expected_mwr)
    assert result.method == "DIETZ"


def test_calculate_mwr_xirr():
    """Tests the XIRR calculation against a known example."""
    result = calculate_money_weighted_return(
        begin_mv=1000.0,
        end_mv=1300.0,
        cash_flows=[
            CashFlow(amount=100.0, date=date(2025, 2, 1)),
            CashFlow(amount=50.0, date=date(2025, 4, 1)),
            CashFlow(amount=-200.0, date=date(2025, 8, 1)),
        ],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2025, 12, 31),
    )
    assert result.method == "XIRR"
    assert result.mwr == pytest.approx(36.86313651, abs=1e-6)


def test_calculate_mwr_xirr_fallback_to_dietz():
    """Tests that XIRR correctly falls back to Modified Dietz when no sign change is present."""
    result = calculate_money_weighted_return(
        begin_mv=1000.0,
        end_mv=-200.0,
        cash_flows=[CashFlow(amount=100.0, date=date(2025, 3, 15))],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False),
        as_of=date(2025, 12, 31),
    )
    assert result.method == "MODIFIED_DIETZ"
    assert result.status == "FALLBACK_USED"
    assert result.fallback_from == "XIRR"
    assert result.fallback_reason == "NO_POSITIVE_AND_NEGATIVE_CASH_FLOW"
    assert "NO_POSITIVE_AND_NEGATIVE_CASH_FLOW" in result.reason_codes
    assert "No positive and negative cash flows in solver vector." in result.notes
    assert "XIRR failed, falling back to Modified Dietz." in result.notes
    assert result.mwr == pytest.approx(-118.1818, abs=1e-4)


def test_calculate_mwr_dietz_annualization():
    """Tests that the Dietz MWR is correctly annualized."""
    start_date = date(2025, 1, 1)
    end_date = date(2025, 6, 30)

    result = calculate_money_weighted_return(
        begin_mv=1000.0,
        end_mv=1060.0,
        cash_flows=[CashFlow(amount=50.0, date=start_date)],
        calculation_method="DIETZ",
        annualization=Annualization(enabled=True, basis="ACT/365"),
        as_of=end_date,
    )

    assert result.method == "DIETZ"
    assert result.mwr == pytest.approx(0.9756, abs=1e-4)
    assert result.mwr_annualized == pytest.approx(1.9882, abs=1e-4)


def test_calculate_mwr_modified_dietz_weights_cash_flows_by_time_remaining():
    result = calculate_money_weighted_return(
        begin_mv=100.0,
        end_mv=112.0,
        cash_flows=[CashFlow(amount=10.0, date=date(2026, 1, 1))],
        calculation_method="MODIFIED_DIETZ",
        annualization=Annualization(enabled=False),
        as_of=date(2026, 3, 31),
        start_date=date(2026, 1, 1),
    )

    assert result.method == "MODIFIED_DIETZ"
    assert result.status == "CALCULATED"
    assert result.mwr == pytest.approx(1.8181818, abs=1e-6)
    assert result.holding_period_return == pytest.approx(1.8181818, abs=1e-6)


def test_calculate_mwr_zero_denominator_returns_not_calculable():
    """Tests that MWR correctly handles a zero denominator."""
    result = calculate_money_weighted_return(
        begin_mv=-50.0,
        end_mv=50.0,
        cash_flows=[CashFlow(amount=100.0, date=date(2025, 1, 1))],
        calculation_method="DIETZ",
        annualization=Annualization(enabled=False),
        as_of=date(2025, 12, 31),
    )
    assert result.method == "DIETZ"
    assert result.mwr == 0.0
    assert result.status == "NOT_CALCULABLE"
    assert result.reason_codes == ["ZERO_DENOMINATOR"]
    assert "Calculation resulted in a zero denominator." in result.notes


def test_calculate_mwr_xirr_matches_industry_midyear_deposit_fixture():
    result = calculate_money_weighted_return(
        begin_mv=100000.0,
        end_mv=230000.0,
        cash_flows=[CashFlow(amount=100000.0, date=date(2026, 7, 1))],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2027, 1, 1),
        start_date=date(2026, 1, 1),
    )

    assert result.method == "XIRR"
    assert result.status == "CALCULATED"
    assert result.mwr == pytest.approx(20.25568893, abs=1e-6)
    assert result.holding_period_return == pytest.approx(20.25568893, abs=1e-6)
    assert result.convergence is not None
    assert result.convergence.converged is True
    assert result.convergence.root_count_detected == 1
    assert result.convergence.day_count_basis == "ACT/365"
    assert result.convergence.residual_npv == pytest.approx(0.0, abs=0.01)


def test_calculate_mwr_xirr_short_period_exposes_holding_period_return():
    result = calculate_money_weighted_return(
        begin_mv=100000.0,
        end_mv=101000.0,
        cash_flows=[],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2026, 1, 31),
        start_date=date(2026, 1, 1),
    )

    assert result.method == "XIRR"
    assert result.mwr == pytest.approx(12.86952942, abs=1e-6)
    assert result.holding_period_return == pytest.approx(1.0, abs=1e-8)
    assert result.is_annualized_primary is True
    assert result.is_approximation is False


def test_xirr_detects_multiple_roots_without_selecting_one():
    result = _xirr(
        values=np.array([-100.0, 230.0, -132.0]),
        dates=np.array([date(2026, 1, 1), date(2027, 1, 1), date(2028, 1, 1)]),
        annualization=Annualization(enabled=False, basis="ACT/365"),
    )

    assert result["converged"] is False
    assert result["rate"] is None
    assert result["reason_code"] == "MULTIPLE_IRR_ROOTS_DETECTED"
    assert result["convergence"]["root_count_detected"] == 2


def test_calculate_mwr_xirr_multiple_root_fallback_is_labeled():
    result = calculate_money_weighted_return(
        begin_mv=100.0,
        end_mv=-132.0,
        cash_flows=[CashFlow(amount=-230.0, date=date(2027, 1, 1))],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2028, 1, 1),
        start_date=date(2026, 1, 1),
    )

    assert result.status == "FALLBACK_USED"
    assert result.method == "MODIFIED_DIETZ"
    assert result.fallback_reason == "MULTIPLE_IRR_ROOTS_DETECTED"
    assert result.is_approximation is True
    assert "FALLBACK_METHOD_USED" in result.warnings


def test_calculate_mwr_xirr_same_day_netting_is_order_independent():
    first = calculate_money_weighted_return(
        begin_mv=100000.0,
        end_mv=125000.0,
        cash_flows=[
            CashFlow(amount=100000.0, date=date(2026, 4, 10)),
            CashFlow(amount=-30000.0, date=date(2026, 4, 10)),
        ],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2027, 1, 1),
        start_date=date(2026, 1, 1),
    )
    second = calculate_money_weighted_return(
        begin_mv=100000.0,
        end_mv=125000.0,
        cash_flows=[
            CashFlow(amount=-30000.0, date=date(2026, 4, 10)),
            CashFlow(amount=100000.0, date=date(2026, 4, 10)),
        ],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2027, 1, 1),
        start_date=date(2026, 1, 1),
    )

    assert first.method == "XIRR"
    assert second.method == "XIRR"
    assert first.mwr == pytest.approx(second.mwr, abs=1e-12)
    assert first.convergence is not None
    assert first.convergence.normalized_flow_count == 3


def test_calculate_mwr_zero_economic_content_is_not_applicable():
    result = calculate_money_weighted_return(
        begin_mv=0.0,
        end_mv=0.0,
        cash_flows=[],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2026, 12, 31),
        start_date=date(2026, 1, 1),
    )

    assert result.status == "NOT_APPLICABLE"
    assert result.reason_codes == ["NO_ECONOMIC_CONTENT"]
    assert result.mwr == 0.0


def test_xirr_reports_no_root_for_unbracketed_domain():
    result = _xirr(
        values=np.array([-100.0, 120.0]),
        dates=np.array([date(2025, 1, 1), date(2025, 12, 31)]),
        annualization=Annualization(enabled=False, basis="ACT/365"),
        rate_lower_bound=0.5,
        rate_upper_bound=1.0,
    )

    assert result["converged"] is False
    assert result["rate"] is None
    assert result["reason_code"] == "NO_ROOT_FOUND"
