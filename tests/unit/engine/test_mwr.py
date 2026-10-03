# tests/unit/engine/test_mwr.py
from datetime import date
from decimal import Decimal

import numpy as np
import pytest
from pydantic import ValidationError

import engine.mwr as mwr_module
from app.models.mwr_requests import CashFlow, Solver
from core.envelope import Annualization, Calendar
from engine.mwr import (
    _annualized_dietz_rate,
    _bisect_root,
    _build_xirr_base_convergence,
    _calculate_dietz_mwr_result,
    _calculate_xirr_mwr_attempt,
    _calculate_xirr_solver_result,
    _calculated_dietz_mwr_result,
    _cash_flows_outside_bounds,
    _day_count_denominator,
    _dietz_denominator,
    _dietz_fallback_metadata,
    _dietz_method_for_calculation,
    _dietz_return_components,
    _mwr_no_economic_content_result,
    _net_cash_flow_amounts_by_date,
    _net_same_day_flows,
    _resolve_mwr_period_bounds,
    _RootCandidate,
    _RootScan,
    _scan_xirr_roots,
    _simple_dietz_denominator,
    _successful_xirr_mwr_result,
    _xirr,
    _xirr_failure,
    _xirr_initial_failure,
    _xirr_initial_failure_reason,
    _xirr_result_from_roots,
    _xirr_time_diffs,
    _zero_denominator_dietz_mwr_result,
    calculate_money_weighted_return,
)
from engine.mwr_controls import XIRR_MAX_WORK_UNITS, xirr_solver_work_is_admitted, xirr_solver_work_units


def _annual_polynomial_values(*roots: float, scale: float = -100.0) -> np.ndarray:
    """Build dated solver values from independently factored roots in ``x = 1 + r``."""
    return scale * np.poly([1.0 + root for root in roots])


@pytest.mark.parametrize(
    "control",
    [
        {"tolerance": float("inf")},
        {"tolerance": float("nan")},
        {"rate_lower_bound": -1.0},
        {"rate_lower_bound": 2.0, "rate_upper_bound": 1.0},
        {"max_iter": 513},
        {"root_scan_steps": 2_049},
        {"max_iter": 201, "root_scan_steps": 2_048},
        {"method": "newton"},
    ],
)
def test_solver_rejects_non_finite_or_out_of_domain_controls(control):
    with pytest.raises(ValidationError):
        Solver.model_validate(control)


def test_solver_combined_work_budget_is_deterministic_and_admits_the_documented_boundary():
    assert xirr_solver_work_units(root_scan_steps=2_048, max_iter=200) == XIRR_MAX_WORK_UNITS
    assert xirr_solver_work_is_admitted(root_scan_steps=2_048, max_iter=200) is True
    assert xirr_solver_work_is_admitted(root_scan_steps=2_048, max_iter=201) is False


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


def test_xirr_rejects_invalid_direct_solver_controls():
    result = _xirr(
        values=np.array([-100.0, 110.0]),
        dates=np.array([date(2025, 1, 1), date(2026, 1, 1)]),
        tolerance=0.0,
    )

    assert result["rate"] is None
    assert result["converged"] is False
    assert result["reason_code"] == "INVALID_SOLVER_CONTROLS"


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
    assert _day_count_denominator(Annualization(enabled=True, basis="BUS/252")) == pytest.approx(252.0)
    assert _day_count_denominator(Annualization(enabled=True, basis="ACT/ACT")) == pytest.approx(365.25)


def test_bisect_root_qualifies_final_midpoint_after_last_allowed_bracket_update():
    candidate = _bisect_root(
        lambda candidate: candidate - 0.25,
        0.0,
        1.0,
        value_tolerance=0.0,
        rate_tolerance=0.0,
        max_iter=1,
    )

    assert candidate.value == pytest.approx(0.25)
    assert candidate.iterations == 1
    assert candidate.converged is True
    assert candidate.termination_reason == "residual_tolerance"

    residual_failure = _bisect_root(
        lambda value: value - 0.3,
        0.0,
        1.0,
        value_tolerance=0.0,
        rate_tolerance=1.0,
        max_iter=10,
    )
    assert residual_failure.converged is False
    assert residual_failure.termination_reason == "rate_tolerance_without_residual"
    assert residual_failure.residual != 0.0


def test_scan_xirr_roots_returns_single_residual_for_bracketed_schedule():
    values = np.array([-100.0, 110.0])
    dates = np.array([date(2026, 1, 1), date(2027, 1, 1)])
    time_diffs = _xirr_time_diffs(
        dates=dates,
        anchor_date=date(2026, 1, 1),
        annualization=Annualization(enabled=False, basis="ACT/365"),
    )

    roots = _scan_xirr_roots(
        values=values,
        time_diffs=time_diffs,
        lower_bound=-0.999999999,
        upper_bound=1000.0,
        root_scan_steps=512,
        tolerance=1e-10,
        max_iter=200,
    )

    assert len(roots.candidates) == 1
    candidate = roots.candidates[0]
    assert candidate.value == pytest.approx(0.1, abs=1e-8)
    assert candidate.iterations > 0
    assert candidate.residual == pytest.approx(0.0, abs=1e-6)
    assert candidate.converged is True
    assert roots.uniqueness_supported is True


def test_scan_xirr_roots_suppresses_duplicate_grid_root_candidates():
    roots = _scan_xirr_roots(
        values=np.array([-100.0, 100.0]),
        time_diffs=np.array([0.0, 1.0]),
        lower_bound=0.0,
        upper_bound=0.5,
        root_scan_steps=32,
        tolerance=1e-10,
        max_iter=10,
    )

    assert len(roots.candidates) == 1
    assert roots.candidates[0].value == pytest.approx(0.0)


def test_scan_xirr_roots_detects_exact_upper_bound_root():
    values = np.array([-100.0, 110.0])
    dates = np.array([date(2026, 1, 1), date(2027, 1, 1)])
    time_diffs = _xirr_time_diffs(
        dates=dates,
        anchor_date=date(2026, 1, 1),
        annualization=Annualization(enabled=False, basis="ACT/365"),
    )

    roots = _scan_xirr_roots(
        values=values,
        time_diffs=time_diffs,
        lower_bound=0.0,
        upper_bound=0.1,
        root_scan_steps=32,
        tolerance=1e-10,
        max_iter=200,
    )

    assert len(roots.candidates) == 1
    assert roots.candidates[0].value == pytest.approx(0.1)
    assert roots.candidates[0].iterations == 0


def test_xirr_result_from_roots_preserves_success_convergence_payload():
    base_convergence = _build_xirr_base_convergence(
        annualization=Annualization(enabled=False, basis="ACT/365"),
        lower_bound=-0.999999999,
        upper_bound=1000.0,
        anchor_date=date(2026, 1, 1),
        normalized_flow_count=2,
        gross_cash_flow_scale=210.0,
    )

    result = _xirr_result_from_roots(
        roots=_RootScan(
            candidates=(
                _RootCandidate(
                    value=0.1,
                    iterations=17,
                    residual=0.000001,
                    termination_reason="residual_tolerance",
                    converged=True,
                ),
            ),
            uniqueness_supported=True,
        ),
        base_convergence=base_convergence,
    )

    assert result["converged"] is True
    assert result["rate"] == pytest.approx(0.1)
    assert result["notes"] == "XIRR calculation successful."
    assert result["convergence"]["root_count_detected"] == 1
    assert result["convergence"]["iterations"] == 17
    assert result["convergence"]["residual"] == pytest.approx(0.000001)
    assert result["convergence"]["residual_npv"] == pytest.approx(0.000001)

    unqualified = _xirr_result_from_roots(
        roots=_RootScan(
            candidates=(
                _RootCandidate(
                    value=0.1,
                    iterations=4,
                    residual=0.25,
                    termination_reason="rate_tolerance_without_residual",
                    converged=False,
                ),
            ),
            uniqueness_supported=True,
            failure_reason="SOLVER_RESIDUAL_OUT_OF_TOLERANCE",
        ),
        base_convergence=base_convergence,
    )
    assert unqualified["rate"] is None
    assert unqualified["reason_code"] == "SOLVER_RESIDUAL_OUT_OF_TOLERANCE"
    assert unqualified["convergence"]["converged"] is False


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


def test_calculate_xirr_mwr_attempt_projects_solver_failure_for_dietz_fallback(monkeypatch):
    def solver_failure(**_kwargs):
        return {
            "rate": None,
            "converged": False,
            "notes": "No XIRR root found in configured bounds.",
            "reason_code": "NO_ROOT_FOUND",
            "convergence": {"root_count_detected": 0},
        }

    monkeypatch.setattr(mwr_module, "_calculate_xirr_solver_result", solver_failure)

    attempt = _calculate_xirr_mwr_attempt(
        begin_mv=1000.0,
        end_mv=-100.0,
        cash_flows=[CashFlow(amount=50.0, date=date(2026, 3, 1))],
        annualization=Annualization(enabled=False, basis="ACT/365"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        period_days=364,
    )

    assert attempt.result is None
    assert attempt.reason_code == "NO_ROOT_FOUND"
    assert attempt.notes == [
        "No XIRR root found in configured bounds.",
        "XIRR failed, falling back to Modified Dietz.",
    ]


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


def test_zero_denominator_dietz_mwr_result_preserves_not_calculable_contract():
    components = _dietz_return_components(
        begin_mv=-50.0,
        end_mv=50.0,
        cash_flows=[CashFlow(amount=100.0, date=date(2025, 1, 1))],
        calculation_method="DIETZ",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    notes: list[str] = []

    result = _zero_denominator_dietz_mwr_result(
        components=components,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        notes=notes,
    )

    assert result.method == "DIETZ"
    assert result.status == "NOT_CALCULABLE"
    assert result.reason_codes == ["ZERO_DENOMINATOR"]
    assert result.mwr == 0.0
    assert result.notes == ["Calculation resulted in a zero denominator."]
    assert notes is result.notes


def test_calculated_dietz_mwr_result_requires_periodic_rate():
    components = _dietz_return_components(
        begin_mv=-50.0,
        end_mv=50.0,
        cash_flows=[CashFlow(amount=100.0, date=date(2025, 1, 1))],
        calculation_method="DIETZ",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )

    with pytest.raises(ValueError, match="Dietz periodic rate is required"):
        _calculated_dietz_mwr_result(
            components=components,
            fallback_metadata=_dietz_fallback_metadata(calculation_method="DIETZ"),
            annualization=Annualization(enabled=False),
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            period_days=364,
            notes=[],
        )


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
    assert components.numerator == Decimal("25")
    assert components.denominator == Decimal("1000") + Decimal("100") * Decimal("91") / Decimal("181")
    assert components.periodic_rate == pytest.approx(float(components.numerator / components.denominator))


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
    bus_252_rate = _annualized_dietz_rate(
        periodic_rate=0.01,
        annualization=Annualization(enabled=True, basis="BUS/252"),
        period_days=126,
    )
    explicit_periods_rate = _annualized_dietz_rate(
        periodic_rate=0.01,
        annualization=Annualization(enabled=True, basis="ACT/365", periods_per_year=12),
        period_days=1,
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
    assert bus_252_rate == pytest.approx(((1.01) ** (252.0 / 126) - 1) * 100)
    assert explicit_periods_rate == pytest.approx(((1.01) ** 12 - 1) * 100)


def test_bus_252_dietz_uses_fixed_weekday_calendar_and_explicit_period_override():
    start_date = date(2025, 1, 1)
    end_date = date(2025, 7, 1)
    calendar = Calendar(type="BUSINESS", trading_calendar="WEEKDAY")

    governed = _annualized_dietz_rate(
        periodic_rate=0.02,
        annualization=Annualization(enabled=True, basis="BUS/252"),
        calendar=calendar,
        start_date=start_date,
        end_date=end_date,
    )
    explicit = _annualized_dietz_rate(
        periodic_rate=0.02,
        annualization=Annualization(enabled=True, basis="BUS/252", periods_per_year=360),
        calendar=calendar,
        start_date=start_date,
        end_date=end_date,
    )

    assert governed == pytest.approx(((1.02) ** (252 / 129) - 1) * 100)
    assert explicit == pytest.approx(((1.02) ** (360 / 129) - 1) * 100)


def test_bus_252_preserves_non_business_flow_dates_in_xirr_and_weighted_dietz():
    calendar = Calendar(type="BUSINESS", trading_calendar="WEEKDAY")
    dates = np.array(
        [
            date(2025, 1, 3),
            date(2025, 1, 4),
            date(2025, 1, 5),
            date(2025, 1, 6),
        ]
    )

    time_diffs = _xirr_time_diffs(
        dates=dates,
        anchor_date=date(2025, 1, 3),
        annualization=Annualization(enabled=False, basis="BUS/252"),
        calendar=calendar,
    )

    assert time_diffs.tolist() == pytest.approx([0.0, 0.0, 0.0, 1 / 252])

    weighted_dietz = calculate_money_weighted_return(
        begin_mv=1000.0,
        end_mv=1110.0,
        cash_flows=[CashFlow(amount=100.0, date=date(2025, 1, 4))],
        calculation_method="MODIFIED_DIETZ",
        annualization=Annualization(enabled=True, basis="BUS/252"),
        as_of=date(2025, 1, 6),
        start_date=date(2025, 1, 3),
        calendar=calendar,
    )

    # The Saturday flow retains its actual-day 2/3 Dietz weight. BUS/252 governs only
    # annualization, with one session in (Friday, Monday].
    assert weighted_dietz.mwr == pytest.approx(0.9375)
    assert weighted_dietz.mwr_annualized == pytest.approx(((1.009375) ** 252 - 1) * 100)


def test_bus_252_xirr_and_dietz_share_weekday_elapsed_measure():
    calendar = Calendar(type="BUSINESS", trading_calendar="WEEKDAY")
    annualization = Annualization(enabled=True, basis="BUS/252")
    expected = ((1.02) ** (252 / 129) - 1) * 100

    xirr = calculate_money_weighted_return(
        begin_mv=1000.0,
        end_mv=1020.0,
        cash_flows=[],
        calculation_method="XIRR",
        annualization=annualization,
        as_of=date(2025, 7, 1),
        start_date=date(2025, 1, 1),
        calendar=calendar,
    )
    dietz = calculate_money_weighted_return(
        begin_mv=1000.0,
        end_mv=1020.0,
        cash_flows=[],
        calculation_method="DIETZ",
        annualization=annualization,
        as_of=date(2025, 7, 1),
        start_date=date(2025, 1, 1),
        calendar=calendar,
    )

    assert xirr.mwr == pytest.approx(expected, abs=5e-8)
    assert xirr.holding_period_return == pytest.approx(2.0, abs=5e-8)
    assert xirr.convergence is not None
    assert xirr.convergence.business_day_count == 129
    assert xirr.convergence.calendar_version == "WEEKDAY:v1"
    assert dietz.mwr == pytest.approx(2.0)
    assert dietz.mwr_annualized == pytest.approx(expected)


def test_calculate_mwr_rejects_cash_flows_outside_resolved_window_before_dietz_weights():
    cash_flows = [
        CashFlow(amount=10.0, date=date(2025, 12, 31)),
        CashFlow(amount=20.0, date=date(2027, 1, 1)),
    ]
    out_of_window = _cash_flows_outside_bounds(
        cash_flows=cash_flows,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )

    assert [cash_flow.date for cash_flow in out_of_window] == [date(2025, 12, 31), date(2027, 1, 1)]
    with pytest.raises(ValueError, match="outside the resolved measurement window"):
        calculate_money_weighted_return(
            begin_mv=1000.0,
            end_mv=1100.0,
            cash_flows=cash_flows,
            calculation_method="MODIFIED_DIETZ",
            annualization=Annualization(enabled=False),
            as_of=date(2026, 12, 31),
            start_date=date(2026, 1, 1),
        )


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


def test_calculate_mwr_returns_xirr_when_root_equals_solver_upper_bound():
    result = calculate_money_weighted_return(
        begin_mv=100.0,
        end_mv=110.0,
        cash_flows=[],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2027, 1, 1),
        start_date=date(2026, 1, 1),
        solver=Solver(rate_lower_bound=0.0, rate_upper_bound=0.1, root_scan_steps=32),
    )

    assert result.method == "XIRR"
    assert result.status == "CALCULATED"
    assert result.mwr == pytest.approx(10.0)
    assert result.reason_codes == []
    assert "DIETZ_FALLBACK_USED" not in result.reason_codes


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


@pytest.mark.parametrize(
    "roots",
    [
        (0.12, 0.121, 0.5),
        (0.10, 0.101, 0.5),
        (0.10, 0.10, 0.5),
    ],
)
def test_xirr_does_not_qualify_close_or_repeated_polynomial_roots_as_unique(roots):
    values = _annual_polynomial_values(*roots)
    for root_scan_steps in (32, 512, 2048):
        result = _xirr(
            values=values,
            dates=np.array([date(2025 + offset, 1, 1) for offset in range(len(values))]),
            annualization=Annualization(enabled=False, basis="ACT/365"),
            root_scan_steps=root_scan_steps,
        )

        assert result["rate"] is None
        assert result["converged"] is False
        assert result["reason_code"] == "MULTIPLE_IRR_ROOTS_DETECTED"
        assert result["convergence"]["root_count_detected"] >= 2


def test_xirr_reports_one_unique_non_simple_root_without_claiming_multiple_roots():
    values = np.array([-100.0, 220.0, -121.0])
    result = _xirr(
        values=values,
        dates=np.array([date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1)]),
        annualization=Annualization(enabled=False, basis="ACT/365"),
    )

    # -100*x^2 + 220*x - 121 = -100*(x - 1.1)^2: one unique double root at r=10%.
    assert np.polyval(values, 1.1) == pytest.approx(0.0, abs=1e-12)
    assert result["rate"] is None
    assert result["converged"] is False
    assert result["reason_code"] == "NON_SIMPLE_IRR_ROOT_DETECTED"
    assert result["convergence"]["root_count_detected"] == 1
    assert result["convergence"]["non_simple_root_detected"] is True


def test_xirr_rejects_excessive_combined_work_before_root_scanning(monkeypatch):
    roots = tuple(index / 100 for index in range(1, 21))
    values = _annual_polynomial_values(*roots)
    dates = np.array([date(2000 + offset, 1, 1) for offset in range(len(values))])

    monkeypatch.setattr(
        mwr_module,
        "_scan_xirr_roots",
        lambda **_kwargs: pytest.fail("root scanning must not start for an excessive work budget"),
    )
    result = _xirr(
        values=values,
        dates=dates,
        annualization=Annualization(enabled=False, basis="ACT/365"),
        root_scan_steps=2_048,
        max_iter=201,
    )

    assert result["reason_code"] == "INVALID_SOLVER_CONTROLS"
    assert result["convergence"]["solver_work_units"] == 411_648


def test_calculate_mwr_close_root_schedule_uses_independently_derived_labeled_fallback():
    result = calculate_money_weighted_return(
        begin_mv=100.0,
        end_mv=188.328,
        cash_flows=[
            CashFlow(amount=-374.1, date=date(2026, 1, 1)),
            CashFlow(amount=461.702, date=date(2027, 1, 1)),
        ],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2028, 1, 1),
        start_date=date(2025, 1, 1),
    )

    # Independent Modified Dietz oracle:
    # numerator = 188.328 - 100 - (-374.1 + 461.702) = 0.726
    # denominator = 100 - 374.1*(2/3) + 461.702*(1/3) = 4.500666...
    assert result.mwr == pytest.approx(16.130943563916456)
    assert result.method == "MODIFIED_DIETZ"
    assert result.status == "FALLBACK_USED"
    assert result.fallback_reason == "MULTIPLE_IRR_ROOTS_DETECTED"
    assert result.warnings == ["FALLBACK_METHOD_USED"]
    assert result.reason_codes == ["MULTIPLE_IRR_ROOTS_DETECTED", "DIETZ_FALLBACK_USED"]
    assert result.is_approximation is True
    assert result.convergence is not None
    assert result.convergence.root_count_detected == 3
    assert result.convergence.uniqueness_supported is True


def test_xirr_budget_exhaustion_is_not_convergence_even_with_one_candidate():
    result = _xirr(
        values=np.array([-100.0, 110.0]),
        dates=np.array([date(2025, 1, 1), date(2026, 1, 1)]),
        annualization=Annualization(enabled=False, basis="ACT/365"),
        max_iter=1,
    )

    assert result["rate"] is None
    assert result["converged"] is False
    assert result["reason_code"] == "SOLVER_ITERATION_LIMIT_REACHED"
    assert result["convergence"]["root_count_detected"] == 1
    assert result["convergence"]["converged"] is False
    assert abs(result["convergence"]["residual_npv"]) > 1e-8


def test_calculate_mwr_budget_exhaustion_preserves_solver_diagnostics_on_labeled_fallback():
    result = calculate_money_weighted_return(
        begin_mv=100.0,
        end_mv=110.0,
        cash_flows=[],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2026, 1, 1),
        start_date=date(2025, 1, 1),
        solver=Solver(max_iter=1),
    )

    assert result.method == "MODIFIED_DIETZ"
    assert result.status == "FALLBACK_USED"
    assert result.fallback_reason == "SOLVER_ITERATION_LIMIT_REACHED"
    assert result.is_approximation is True
    assert result.convergence is not None
    assert result.convergence.converged is False
    assert result.convergence.root_count_detected == 1
    assert abs(result.convergence.residual_npv or 0.0) > 1e-8

    ordinary = calculate_money_weighted_return(
        begin_mv=100.0,
        end_mv=110.0,
        cash_flows=[],
        calculation_method="XIRR",
        annualization=Annualization(enabled=False, basis="ACT/365"),
        as_of=date(2026, 1, 1),
        start_date=date(2025, 1, 1),
        solver=Solver(max_iter=200),
    )
    assert ordinary.method == "XIRR"
    assert ordinary.status == "CALCULATED"
    assert ordinary.mwr == pytest.approx(10.0, abs=1e-8)
    assert ordinary.convergence is not None
    assert ordinary.convergence.converged is True
    assert ordinary.convergence.termination_reason == "residual_tolerance"


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
