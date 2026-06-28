# tests/unit/engine/test_mwr.py
from datetime import date

import numpy as np
import pytest

import engine.mwr as mwr_module
from app.models.mwr_requests import CashFlow
from core.envelope import Annualization
from engine.mwr import (
    _annualized_dietz_rate,
    _bisect_root,
    _build_xirr_base_convergence,
    _calculate_dietz_mwr_result,
    _calculate_xirr_mwr_attempt,
    _calculate_xirr_solver_result,
    _day_count_denominator,
    _dietz_denominator,
    _dietz_fallback_metadata,
    _dietz_method_for_calculation,
    _dietz_return_components,
    _mwr_no_economic_content_result,
    _net_cash_flow_amounts_by_date,
    _net_same_day_flows,
    _resolve_mwr_period_bounds,
    _scan_xirr_roots,
    _simple_dietz_denominator,
    _successful_xirr_mwr_result,
    _xirr,
    _xirr_failure,
    _xirr_initial_failure,
    _xirr_initial_failure_reason,
    _xirr_result_from_roots,
    _xirr_root_candidate,
    _xirr_time_diffs,
    calculate_money_weighted_return,
)


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


def test_xirr_failure_preserves_convergence_context():
    base_convergence = _build_xirr_base_convergence(
        annualization=Annualization(enabled=False, basis="ACT/365"),
        lower_bound=-0.5,
        upper_bound=2.0,
        anchor_date=date(2026, 1, 1),
        normalized_flow_count=2,
        gross_cash_flow_scale=200.0,
    )

    result = _xirr_failure(
        base_convergence=base_convergence,
        notes="Invalid XIRR search bounds.",
        reason_code="INVALID_SOLVER_BOUNDS",
    )

    assert result["converged"] is False
    assert result["rate"] is None
    assert result["reason_code"] == "INVALID_SOLVER_BOUNDS"
    assert result["convergence"]["algorithm"] == "log_rate_bracket_scan_bisection"
    assert result["convergence"]["root_count_detected"] == 0
    assert result["convergence"]["gross_cash_flow_scale"] == 200.0


def test_xirr_initial_failure_maps_invalid_solver_bounds():
    base_convergence = _build_xirr_base_convergence(
        annualization=Annualization(enabled=False, basis="ACT/365"),
        lower_bound=-1.0,
        upper_bound=2.0,
        anchor_date=date(2026, 1, 1),
        normalized_flow_count=2,
        gross_cash_flow_scale=200.0,
    )

    result = _xirr_initial_failure(
        values=np.array([-100.0, 100.0]),
        gross_cash_flow_scale=200.0,
        rate_lower_bound=-1.0,
        rate_upper_bound=2.0,
        base_convergence=base_convergence,
    )

    assert result is not None
    assert result["reason_code"] == "INVALID_SOLVER_BOUNDS"
    assert result["notes"] == "Invalid XIRR search bounds."
    assert result["convergence"]["converged"] is False


def test_xirr_initial_failure_reason_maps_empty_and_one_sided_vectors():
    assert _xirr_initial_failure_reason(
        values=np.array([]),
        gross_cash_flow_scale=0.0,
        rate_lower_bound=-0.999999999,
        rate_upper_bound=1000.0,
    ) == ("No economic content in cash-flow vector.", "NO_ECONOMIC_CONTENT")

    assert _xirr_initial_failure_reason(
        values=np.array([100.0, 50.0]),
        gross_cash_flow_scale=150.0,
        rate_lower_bound=-0.999999999,
        rate_upper_bound=1000.0,
    ) == ("No positive and negative cash flows in solver vector.", "NO_POSITIVE_AND_NEGATIVE_CASH_FLOW")


def test_net_cash_flow_amounts_by_date_preserves_zero_net_dates():
    amounts_by_date = _net_cash_flow_amounts_by_date(
        values=[100.0, -100.0, 25.5],
        dates=[date(2026, 1, 2), date(2026, 1, 2), date(2026, 1, 3)],
    )

    assert amounts_by_date == {
        date(2026, 1, 2): 0.0,
        date(2026, 1, 3): 25.5,
    }


def test_net_same_day_flows_sorts_dates_and_drops_zero_net_dates():
    values, dates = _net_same_day_flows(
        values=[25.5, 100.0, -100.0, -10.0],
        dates=[date(2026, 1, 3), date(2026, 1, 2), date(2026, 1, 2), date(2026, 1, 1)],
    )

    assert values.tolist() == [-10.0, 25.5]
    assert dates.tolist() == [date(2026, 1, 1), date(2026, 1, 3)]


def test_day_count_denominator_prefers_explicit_period_frequency_and_act_act_basis():
    assert _day_count_denominator(Annualization(enabled=True, basis="ACT/365", periods_per_year=12)) == pytest.approx(
        12.0
    )
    assert _day_count_denominator(Annualization(enabled=True, basis="ACT/ACT")) == pytest.approx(365.25)


def test_bisect_root_returns_midpoint_after_iteration_budget_is_exhausted():
    root, iterations = _bisect_root(
        lambda candidate: candidate - 0.25,
        0.0,
        1.0,
        value_tolerance=0.0,
        rate_tolerance=0.0,
        max_iter=1,
    )

    assert root == pytest.approx(0.25)
    assert iterations == 1


def test_scan_xirr_roots_returns_single_residual_for_bracketed_schedule():
    values = np.array([-100.0, 110.0])
    dates = np.array([date(2026, 1, 1), date(2027, 1, 1)])
    time_diffs = _xirr_time_diffs(
        dates=dates,
        anchor_date=date(2026, 1, 1),
        annualization=Annualization(enabled=False, basis="ACT/365"),
    )

    def log_npv(log_rate: float) -> float:
        return float(np.sum(values * np.exp(-log_rate * time_diffs)))

    roots = _scan_xirr_roots(
        values=values,
        time_diffs=time_diffs,
        lower_bound=-0.999999999,
        upper_bound=1000.0,
        root_scan_steps=512,
        tolerance=1e-10,
        max_iter=200,
        gross_cash_flow_scale=float(np.sum(np.abs(values))),
        log_npv=log_npv,
    )

    assert len(roots) == 1
    root_rate, iterations, residual = roots[0]
    assert root_rate == pytest.approx(0.1, abs=1e-8)
    assert iterations > 0
    assert residual == pytest.approx(0.0, abs=1e-6)


def test_scan_xirr_roots_suppresses_duplicate_grid_root_candidates(monkeypatch):
    monkeypatch.setattr(mwr_module, "_xirr_root_candidate", lambda **_kwargs: (0.1, 3))

    roots = _scan_xirr_roots(
        values=np.array([-100.0, 100.0]),
        time_diffs=np.array([0.0, 1.0]),
        lower_bound=0.0,
        upper_bound=0.5,
        root_scan_steps=32,
        tolerance=1e-10,
        max_iter=10,
        gross_cash_flow_scale=200.0,
        log_npv=lambda _log_rate: 0.0,
    )

    assert len(roots) == 1
    assert roots[0][0] == pytest.approx(0.1)
    assert roots[0][1] == 3


def test_xirr_root_candidate_ignores_non_finite_intervals():
    candidate = _xirr_root_candidate(
        previous_x=0.0,
        previous_y=float("nan"),
        current_x=1.0,
        current_y=-1.0,
        tolerance=1e-10,
        max_iter=100,
        gross_cash_flow_scale=1.0,
        log_npv=lambda _rate: 0.0,
    )

    assert candidate is None


def test_xirr_root_candidate_projects_exact_grid_root_without_bisection():
    candidate = _xirr_root_candidate(
        previous_x=0.0,
        previous_y=0.0,
        current_x=1.0,
        current_y=-1.0,
        tolerance=1e-10,
        max_iter=100,
        gross_cash_flow_scale=1.0,
        log_npv=lambda _rate: 0.0,
    )

    assert candidate is not None
    solver_value, iterations = candidate
    assert solver_value == pytest.approx(0.0)
    assert iterations == 0


def test_xirr_result_from_roots_preserves_success_convergence_payload():
    base_convergence = _build_xirr_base_convergence(
        annualization=Annualization(enabled=False, basis="ACT/365"),
        lower_bound=-0.999999999,
        upper_bound=1000.0,
        anchor_date=date(2026, 1, 1),
        normalized_flow_count=2,
        gross_cash_flow_scale=210.0,
    )

    result = _xirr_result_from_roots(roots=[(0.1, 17, 0.000001)], base_convergence=base_convergence)

    assert result["converged"] is True
    assert result["rate"] == pytest.approx(0.1)
    assert result["notes"] == "XIRR calculation successful."
    assert result["convergence"]["root_count_detected"] == 1
    assert result["convergence"]["iterations"] == 17
    assert result["convergence"]["residual"] == pytest.approx(0.000001)
    assert result["convergence"]["residual_npv"] == pytest.approx(0.000001)


def test_calculate_xirr_mwr_attempt_returns_successful_xirr_result():
    attempt = _calculate_xirr_mwr_attempt(
        begin_mv=1000.0,
        end_mv=1300.0,
        cash_flows=[
            CashFlow(amount=100.0, date=date(2025, 2, 1)),
            CashFlow(amount=50.0, date=date(2025, 4, 1)),
            CashFlow(amount=-200.0, date=date(2025, 8, 1)),
        ],
        annualization=Annualization(enabled=False, basis="ACT/365"),
        start_date=date(2025, 2, 1),
        end_date=date(2025, 12, 31),
        period_days=333,
    )

    assert attempt.reason_code is None
    assert attempt.result is not None
    assert attempt.result.method == "XIRR"
    assert attempt.result.mwr == pytest.approx(36.86313651, abs=1e-6)


def test_calculate_xirr_mwr_attempt_maps_no_economic_content_to_not_applicable():
    attempt = _calculate_xirr_mwr_attempt(
        begin_mv=0.0,
        end_mv=0.0,
        cash_flows=[],
        annualization=Annualization(enabled=False, basis="ACT/365"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        period_days=364,
    )

    assert attempt.reason_code == "NO_ECONOMIC_CONTENT"
    assert attempt.result is not None
    assert attempt.result.status == "NOT_APPLICABLE"
    assert attempt.result.reason_codes == ["NO_ECONOMIC_CONTENT"]


def test_calculate_xirr_solver_result_projects_signed_cash_flow_vector(monkeypatch):
    captured = {}

    class Solver:
        rate_lower_bound = -0.5
        rate_upper_bound = 5.0
        root_scan_steps = 64
        tolerance = 1e-8
        max_iter = 25

    def capture_xirr(values, dates, **kwargs):
        captured["values"] = values.tolist()
        captured["dates"] = dates.tolist()
        captured["kwargs"] = kwargs
        return {
            "rate": 0.1,
            "converged": True,
            "notes": "XIRR calculation successful.",
            "convergence": {},
        }

    monkeypatch.setattr(mwr_module, "_xirr", capture_xirr)

    result = _calculate_xirr_solver_result(
        begin_mv=1000.0,
        end_mv=1200.0,
        cash_flows=[CashFlow(amount=50.0, date=date(2026, 3, 1))],
        annualization=Annualization(enabled=False, basis="ACT/365"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        solver=Solver(),
    )

    assert result["rate"] == pytest.approx(0.1)
    assert captured["values"] == [-1000.0, -50.0, 1200.0]
    assert captured["dates"] == [date(2026, 1, 1), date(2026, 3, 1), date(2026, 12, 31)]
    assert captured["kwargs"]["rate_lower_bound"] == pytest.approx(-0.5)
    assert captured["kwargs"]["rate_upper_bound"] == pytest.approx(5.0)
    assert captured["kwargs"]["root_scan_steps"] == 64
    assert captured["kwargs"]["tolerance"] == pytest.approx(1e-8)
    assert captured["kwargs"]["max_iter"] == 25


def test_successful_xirr_mwr_result_projects_annualized_and_holding_period_returns():
    convergence = _build_xirr_base_convergence(
        annualization=Annualization(enabled=False, basis="ACT/365"),
        lower_bound=-0.999999999,
        upper_bound=1000.0,
        anchor_date=date(2026, 1, 1),
        normalized_flow_count=2,
        gross_cash_flow_scale=210.0,
    )

    result = _successful_xirr_mwr_result(
        rate=0.1,
        annualization=Annualization(enabled=False, basis="ACT/365"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 2),
        period_days=182,
        notes=["XIRR calculation successful."],
        convergence=convergence,
    )

    assert result.method == "XIRR"
    assert result.mwr == pytest.approx(10.0)
    assert result.mwr_annualized == pytest.approx(10.0)
    assert result.holding_period_return == pytest.approx(((1.1) ** (182 / 365.0) - 1) * 100)
    assert result.is_annualized_primary is True
    assert result.is_approximation is False


def test_successful_xirr_mwr_result_keeps_holding_period_absent_for_non_positive_period():
    result = _successful_xirr_mwr_result(
        rate=0.1,
        annualization=Annualization(enabled=False, basis="ACT/365"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        period_days=0,
        notes=["XIRR calculation successful."],
        convergence=None,
    )

    assert result.holding_period_return is None


def test_calculate_dietz_mwr_result_preserves_xirr_fallback_metadata():
    result = _calculate_dietz_mwr_result(
        begin_mv=1000.0,
        end_mv=-200.0,
        cash_flows=[CashFlow(amount=100.0, date=date(2025, 3, 15))],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False),
        start_date=date(2025, 3, 15),
        end_date=date(2025, 12, 31),
        period_days=291,
        notes=["No positive and negative cash flows in solver vector."],
        xirr_fallback_reason_code="NO_POSITIVE_AND_NEGATIVE_CASH_FLOW",
    )

    assert result.method == "MODIFIED_DIETZ"
    assert result.status == "FALLBACK_USED"
    assert result.reason_codes == ["NO_POSITIVE_AND_NEGATIVE_CASH_FLOW", "DIETZ_FALLBACK_USED"]
    assert result.warnings == ["FALLBACK_METHOD_USED"]
    assert result.fallback_from == "XIRR"
    assert result.fallback_reason == "NO_POSITIVE_AND_NEGATIVE_CASH_FLOW"


def test_dietz_policy_helpers_preserve_method_and_fallback_metadata():
    assert _dietz_method_for_calculation("XIRR") == "MODIFIED_DIETZ"
    assert _dietz_method_for_calculation("MODIFIED_DIETZ") == "MODIFIED_DIETZ"
    assert _dietz_method_for_calculation("DIETZ") == "DIETZ"

    calculated_metadata = _dietz_fallback_metadata(calculation_method="DIETZ")
    fallback_metadata = _dietz_fallback_metadata(
        calculation_method="XIRR",
        xirr_fallback_reason_code="MULTIPLE_IRR_ROOTS_DETECTED",
    )

    assert calculated_metadata.status == "CALCULATED"
    assert calculated_metadata.reason_codes == []
    assert calculated_metadata.warnings == []
    assert calculated_metadata.fallback_from is None
    assert calculated_metadata.fallback_reason is None
    assert fallback_metadata.status == "FALLBACK_USED"
    assert fallback_metadata.reason_codes == ["MULTIPLE_IRR_ROOTS_DETECTED", "DIETZ_FALLBACK_USED"]
    assert fallback_metadata.warnings == ["FALLBACK_METHOD_USED"]
    assert fallback_metadata.fallback_from == "XIRR"
    assert fallback_metadata.fallback_reason == "MULTIPLE_IRR_ROOTS_DETECTED"


def test_dietz_return_components_project_capital_base_and_periodic_rate():
    components = _dietz_return_components(
        begin_mv=1000.0,
        end_mv=1125.0,
        cash_flows=[CashFlow(amount=100.0, date=date(2026, 4, 1))],
        calculation_method="XIRR",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
    )

    assert components.method == "MODIFIED_DIETZ"
    assert components.numerator == pytest.approx(25.0)
    assert components.denominator == pytest.approx(1000.0 + (100.0 * 91 / 181))
    assert components.periodic_rate == pytest.approx(components.numerator / components.denominator)


def test_simple_dietz_denominator_uses_average_cash_flows():
    denominator = _simple_dietz_denominator(
        begin_mv=100.0,
        cash_flows=[
            CashFlow(amount=20.0, date=date(2026, 1, 1)),
            CashFlow(amount=-10.0, date=date(2026, 1, 2)),
        ],
    )

    assert denominator == pytest.approx(105.0)


def test_dietz_denominator_uses_simple_policy_for_non_positive_period_days():
    denominator = _dietz_denominator(
        begin_mv=100.0,
        cash_flows=[CashFlow(amount=20.0, date=date(2026, 1, 1))],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        method="MODIFIED_DIETZ",
    )

    assert denominator == pytest.approx(110.0)


def test_mwr_preflight_resolves_bounds_and_no_economic_content_result():
    bounds = _resolve_mwr_period_bounds(
        cash_flows=[CashFlow(amount=100.0, date=date(2026, 2, 1))],
        as_of=date(2026, 3, 1),
        start_date=None,
    )

    assert bounds.start_date == date(2026, 2, 1)
    assert bounds.end_date == date(2026, 3, 1)
    assert bounds.period_days == 28

    empty_bounds = _resolve_mwr_period_bounds(cash_flows=[], as_of=date(2026, 3, 1), start_date=None)
    result = _mwr_no_economic_content_result(
        begin_mv=0.0,
        end_mv=0.0,
        cash_flows=[],
        bounds=empty_bounds,
    )

    assert result is not None
    assert result.status == "NOT_APPLICABLE"
    assert result.reason_codes == ["NO_ECONOMIC_CONTENT"]
    assert result.start_date == date(2026, 3, 1)


def test_annualized_dietz_rate_uses_governed_day_count_basis():
    act_365_rate = _annualized_dietz_rate(
        periodic_rate=0.01,
        annualization=Annualization(enabled=True, basis="ACT/365"),
        period_days=182,
    )
    act_act_rate = _annualized_dietz_rate(
        periodic_rate=0.01,
        annualization=Annualization(enabled=True, basis="ACT/ACT"),
        period_days=182,
    )

    assert (
        _annualized_dietz_rate(
            periodic_rate=0.01,
            annualization=Annualization(enabled=False, basis="ACT/365"),
            period_days=182,
        )
        is None
    )
    assert (
        _annualized_dietz_rate(
            periodic_rate=0.01,
            annualization=Annualization(enabled=True, basis="ACT/365"),
            period_days=0,
        )
        is None
    )
    assert act_365_rate == pytest.approx(((1.01) ** (365.0 / 182) - 1) * 100)
    assert act_act_rate == pytest.approx(((1.01) ** (365.25 / 182) - 1) * 100)


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


def test_xirr_raises_when_anchor_date_is_missing_after_preflight(monkeypatch):
    monkeypatch.setattr(mwr_module, "_xirr_initial_failure", lambda **_kwargs: None)

    with pytest.raises(ValueError, match="XIRR anchor date is required"):
        _xirr(
            values=np.array([100.0, -100.0]),
            dates=np.array([date(2026, 1, 1), date(2026, 1, 1)]),
            annualization=Annualization(enabled=False, basis="ACT/365"),
        )
