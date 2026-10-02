# engine/mwr.py
from dataclasses import dataclass
from datetime import date
from math import exp, isfinite, log
from typing import Callable, Literal, Sequence

import numpy as np

from core.annualize import periods_per_year_for_basis
from core.business_calendar import BusinessDayEvidence, business_day_counts, business_day_evidence
from core.envelope import Annualization, Calendar
from engine.mwr_controls import (
    XIRR_MAX_ITERATIONS,
    XIRR_MAX_SCAN_STEPS,
    xirr_solver_work_is_admitted,
    xirr_solver_work_units,
)
from engine.mwr_types import CashFlowLike, MWRConvergence, MWRResult, Number

_XIRR_DISTINCT_ROOT_TOLERANCE = 1e-8
_XIRR_MAX_UNIQUENESS_TERMS = 64


@dataclass(frozen=True)
class _RootCandidate:
    value: float  # monetary-float-allow: dimensionless rate or log-rate candidate
    iterations: int
    residual: float
    termination_reason: Literal[
        "residual_tolerance",
        "rate_tolerance_without_residual",
        "iteration_limit",
    ]
    converged: bool


@dataclass(frozen=True)
class _RootScan:
    candidates: tuple[_RootCandidate, ...]
    uniqueness_supported: bool
    failure_reason: str | None = None
    non_simple_root_detected: bool = False


def _day_count_denominator(annualization: Annualization) -> float:
    return periods_per_year_for_basis(
        basis=annualization.basis,
        periods_per_year=annualization.periods_per_year,
    )


def _net_same_day_flows(values: list[float], dates: list[date]) -> tuple[np.ndarray, np.ndarray]:
    by_date = _net_cash_flow_amounts_by_date(values, dates)
    sorted_items = [(flow_date, amount) for flow_date, amount in sorted(by_date.items()) if amount != 0.0]
    return (
        np.array([amount for _, amount in sorted_items], dtype=float),
        np.array([flow_date for flow_date, _ in sorted_items]),
    )


def _net_cash_flow_amounts_by_date(values, dates):
    by_date = {}
    for value, flow_date in zip(values, dates):
        by_date[flow_date] = by_date.get(flow_date, 0) + value
    return by_date


def _npv_at_rate(values: np.ndarray, taus: np.ndarray, rate: float) -> float:
    return float(np.sum(values / ((1 + rate) ** taus)))


def _bisect_root(
    func, left: float, right: float, *, value_tolerance: float, rate_tolerance: float, max_iter: int
) -> _RootCandidate:
    left_value = func(left)
    if abs(left_value) <= value_tolerance:
        return _RootCandidate(left, 0, left_value, "residual_tolerance", True)
    right_value = func(right)
    if abs(right_value) <= value_tolerance:
        return _RootCandidate(right, 0, right_value, "residual_tolerance", True)
    for iteration in range(1, max_iter + 1):
        middle = (left + right) / 2
        middle_value = func(middle)
        if abs(middle_value) <= value_tolerance:
            return _RootCandidate(middle, iteration, middle_value, "residual_tolerance", True)
        if abs(right - left) <= rate_tolerance:
            return _RootCandidate(
                middle,
                iteration,
                middle_value,
                "rate_tolerance_without_residual",
                False,
            )
        if left_value * middle_value <= 0:
            right = middle
            right_value = middle_value
        else:
            left = middle
            left_value = middle_value
    middle = (left + right) / 2
    middle_value = func(middle)
    if abs(middle_value) <= value_tolerance:
        return _RootCandidate(middle, max_iter, middle_value, "residual_tolerance", True)
    return _RootCandidate(middle, max_iter, middle_value, "iteration_limit", False)


def _build_xirr_base_convergence(
    *,
    annualization: Annualization,
    lower_bound: float,
    upper_bound: float,
    anchor_date: date | None,
    normalized_flow_count: int,
    gross_cash_flow_scale: float,
    root_scan_steps: int | None = None,
    tolerance: float | None = None,
    max_iterations: int | None = None,
    solver_work_units: int | None = None,
) -> dict:
    return {
        "algorithm": "log_rate_bracket_scan_bisection",
        "rate_lower_bound": lower_bound,
        "rate_upper_bound": upper_bound,
        "day_count_basis": annualization.basis,
        "anchor_date": anchor_date,
        "normalized_flow_count": normalized_flow_count,
        "gross_cash_flow_scale": gross_cash_flow_scale,
        "root_scan_steps": root_scan_steps,
        "tolerance": tolerance,
        "max_iterations": max_iterations,
        "solver_work_units": solver_work_units,
    }


def _xirr_failure(
    *,
    base_convergence: dict,
    notes: str,
    reason_code: str,
    root_count_detected: int = 0,
) -> dict:
    return {
        "rate": None,
        "converged": False,
        "notes": notes,
        "reason_code": reason_code,
        "convergence": {
            **base_convergence,
            "root_count_detected": root_count_detected,
            "converged": False,
        },
    }


def _xirr_initial_failure(
    *,
    values: np.ndarray,
    gross_cash_flow_scale,
    rate_lower_bound,
    rate_upper_bound,
    base_convergence: dict,
) -> dict | None:
    failure_reason = _xirr_initial_failure_reason(
        values=values,
        gross_cash_flow_scale=gross_cash_flow_scale,
        rate_lower_bound=rate_lower_bound,
        rate_upper_bound=rate_upper_bound,
    )
    if failure_reason is None:
        return None
    notes, reason_code = failure_reason
    return _xirr_failure(
        base_convergence=base_convergence,
        notes=notes,
        reason_code=reason_code,
    )


def _xirr_initial_failure_reason(
    *,
    values: np.ndarray,
    gross_cash_flow_scale,
    rate_lower_bound,
    rate_upper_bound,
) -> tuple[str, str] | None:
    if _xirr_has_no_economic_content(values=values, gross_cash_flow_scale=gross_cash_flow_scale):
        return "No economic content in cash-flow vector.", "NO_ECONOMIC_CONTENT"
    if _xirr_has_one_sided_cash_flows(values):
        return "No positive and negative cash flows in solver vector.", "NO_POSITIVE_AND_NEGATIVE_CASH_FLOW"
    if _xirr_has_invalid_solver_bounds(rate_lower_bound=rate_lower_bound, rate_upper_bound=rate_upper_bound):
        return "Invalid XIRR search bounds.", "INVALID_SOLVER_BOUNDS"
    return None


def _xirr_has_no_economic_content(*, values: np.ndarray, gross_cash_flow_scale) -> bool:
    return len(values) == 0 or gross_cash_flow_scale == 0


def _xirr_has_one_sided_cash_flows(values: np.ndarray) -> bool:
    return bool(np.all(values >= 0) or np.all(values <= 0))


def _xirr_has_invalid_solver_bounds(*, rate_lower_bound, rate_upper_bound) -> bool:
    return (
        not isfinite(rate_lower_bound)
        or not isfinite(rate_upper_bound)
        or rate_lower_bound <= -1
        or rate_upper_bound <= rate_lower_bound
    )


def _xirr_has_invalid_solver_controls(*, root_scan_steps: int, tolerance: float, max_iter: int) -> bool:
    return (
        root_scan_steps < 2
        or root_scan_steps > XIRR_MAX_SCAN_STEPS
        or not isfinite(tolerance)
        or tolerance <= 0
        or max_iter < 1
        or max_iter > XIRR_MAX_ITERATIONS
        or not xirr_solver_work_is_admitted(root_scan_steps=root_scan_steps, max_iter=max_iter)
    )


def _elapsed_measure(
    *,
    start_date: date,
    end_date: date,
    annualization: Annualization,
    calendar: Calendar,
) -> int:
    if annualization.basis == "BUS/252":
        return business_day_evidence(
            calendar=calendar,
            start_date=start_date,
            end_date=end_date,
        ).business_day_count
    return max((end_date - start_date).days, 0)


def _xirr_time_diffs(
    *,
    dates: np.ndarray,
    anchor_date: date,
    annualization: Annualization,
    calendar: Calendar | None = None,
) -> np.ndarray:
    day_count = _day_count_denominator(annualization)
    applied_calendar = calendar or Calendar()
    if annualization.basis == "BUS/252":
        _, elapsed_measures = business_day_counts(
            calendar=applied_calendar,
            start_date=anchor_date,
            end_dates=list(dates),
        )
        return np.array([elapsed_measure / day_count for elapsed_measure in elapsed_measures])
    return np.array(
        [
            _elapsed_measure(
                start_date=anchor_date,
                end_date=d,
                annualization=annualization,
                calendar=applied_calendar,
            )
            / day_count
            for d in dates
        ]
    )


def _scan_xirr_roots(
    *,
    values: np.ndarray,
    time_diffs: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    root_scan_steps: int,
    tolerance: float,
    max_iter: int,
) -> _RootScan:
    x_min = log(1 + lower_bound)
    x_max = log(1 + upper_bound)
    log_scan = _isolate_exponential_roots(
        coefficients=values,
        exponents=time_diffs,
        lower_bound=x_min,
        upper_bound=x_max,
        root_scan_steps=max(root_scan_steps, 32),
        tolerance=tolerance,
        max_iter=max_iter,
    )
    candidates = tuple(
        _RootCandidate(
            value=exp(candidate.value) - 1,
            iterations=candidate.iterations,
            residual=_npv_at_rate(values, time_diffs, exp(candidate.value) - 1),
            termination_reason=candidate.termination_reason,
            converged=candidate.converged,
        )
        for candidate in log_scan.candidates
    )
    return _RootScan(
        candidates=candidates,
        uniqueness_supported=log_scan.uniqueness_supported,
        failure_reason=log_scan.failure_reason,
        non_simple_root_detected=log_scan.non_simple_root_detected,
    )


def _isolate_exponential_roots(
    *,
    coefficients: np.ndarray,
    exponents: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    root_scan_steps: int,
    tolerance: float,
    max_iter: int,
) -> _RootScan:
    coefficients, exponents = _normalized_exponential_terms(coefficients=coefficients, exponents=exponents)
    if len(coefficients) <= 1:
        return _RootScan(candidates=(), uniqueness_supported=True)

    value_tolerance = max(tolerance * max(float(np.sum(np.abs(coefficients))), 1.0), 1e-8)
    evaluate = _exponential_function(coefficients=coefficients, exponents=exponents)
    sign_changes = _coefficient_sign_changes(coefficients)
    if sign_changes > 1 and len(coefficients) > _XIRR_MAX_UNIQUENESS_TERMS:
        scan = _scan_monotonic_partitions(
            evaluate=evaluate,
            partition_points=np.linspace(lower_bound, upper_bound, root_scan_steps),
            value_tolerance=value_tolerance,
            rate_tolerance=tolerance,
            max_iter=max_iter,
        )
        return _RootScan(
            candidates=scan.candidates,
            uniqueness_supported=False,
            failure_reason="XIRR_UNIQUENESS_NOT_SUPPORTED",
        )

    stationary_scan = _stationary_point_scan(
        coefficients=coefficients,
        exponents=exponents,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        root_scan_steps=root_scan_steps,
        tolerance=tolerance,
        max_iter=max_iter,
        sign_changes=sign_changes,
    )
    partition_points = np.concatenate(
        (
            np.linspace(lower_bound, upper_bound, root_scan_steps),
            np.array([candidate.value for candidate in stationary_scan.candidates]),
        )
    )
    scan = _scan_monotonic_partitions(
        evaluate=evaluate,
        partition_points=partition_points,
        value_tolerance=value_tolerance,
        rate_tolerance=tolerance,
        max_iter=max_iter,
    )
    return _RootScan(
        candidates=scan.candidates,
        uniqueness_supported=stationary_scan.uniqueness_supported and scan.uniqueness_supported,
        failure_reason=stationary_scan.failure_reason or scan.failure_reason,
        non_simple_root_detected=_has_stationary_root(
            candidates=scan.candidates,
            stationary_candidates=stationary_scan.candidates,
        ),
    )


def _normalized_exponential_terms(*, coefficients: np.ndarray, exponents: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nonzero = coefficients != 0
    retained_coefficients = np.asarray(coefficients[nonzero], dtype=float)
    retained_exponents = np.asarray(exponents[nonzero], dtype=float)
    if len(retained_exponents) == 0:
        return retained_coefficients, retained_exponents
    return retained_coefficients, retained_exponents - float(  # monetary-float-allow: dimensionless year fraction
        np.min(retained_exponents)
    )


def _exponential_function(*, coefficients: np.ndarray, exponents: np.ndarray) -> Callable[[float], float]:
    def evaluate(log_rate: float) -> float:
        with np.errstate(over="ignore", invalid="ignore"):
            return float(np.sum(coefficients * np.exp(-log_rate * exponents)))

    return evaluate


def _coefficient_sign_changes(coefficients: np.ndarray) -> int:
    signs = np.sign(coefficients[coefficients != 0])
    return int(np.sum(signs[1:] != signs[:-1]))


def _stationary_point_scan(
    *,
    coefficients: np.ndarray,
    exponents: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    root_scan_steps: int,
    tolerance: float,
    max_iter: int,
    sign_changes: int,
) -> _RootScan:
    if sign_changes <= 1:
        return _RootScan(candidates=(), uniqueness_supported=True)
    derivative_coefficients = -exponents * coefficients
    derivative_terms = derivative_coefficients != 0
    return _isolate_exponential_roots(
        coefficients=derivative_coefficients[derivative_terms],
        exponents=exponents[derivative_terms],
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        root_scan_steps=root_scan_steps,
        tolerance=tolerance,
        max_iter=max_iter,
    )


def _scan_monotonic_partitions(
    *,
    evaluate: Callable[[float], float],
    partition_points: np.ndarray,
    value_tolerance: float,
    rate_tolerance: float,  # monetary-float-allow: dimensionless log-rate tolerance
    max_iter: int,
) -> _RootScan:
    points = sorted({float(point) for point in partition_points if isfinite(float(point))})
    roots = _exact_partition_roots(
        evaluate=evaluate,
        points=points,
        value_tolerance=value_tolerance,
    )
    for candidate in _bracketed_partition_roots(
        evaluate=evaluate,
        points=points,
        value_tolerance=value_tolerance,
        rate_tolerance=rate_tolerance,
        max_iter=max_iter,
    ):
        _append_distinct_root(roots, candidate)
    return _RootScan(
        candidates=tuple(sorted(roots, key=lambda candidate: candidate.value)),
        uniqueness_supported=True,
        failure_reason=_first_candidate_failure_reason(roots),
    )


def _exact_partition_roots(
    *,
    evaluate: Callable[[float], float],
    points: list[float],
    value_tolerance: float,
) -> list[_RootCandidate]:
    roots: list[_RootCandidate] = []
    for point in points:
        residual = evaluate(point)
        if isfinite(residual) and abs(residual) <= value_tolerance:
            _append_distinct_root(
                roots,
                _RootCandidate(point, 0, residual, "residual_tolerance", True),
            )
    return roots


def _bracketed_partition_roots(
    *,
    evaluate: Callable[[float], float],
    points: list[float],
    value_tolerance: float,
    rate_tolerance: float,  # monetary-float-allow: dimensionless log-rate tolerance
    max_iter: int,
) -> list[_RootCandidate]:
    roots: list[_RootCandidate] = []
    for left, right in zip(points, points[1:]):
        left_value = evaluate(left)
        right_value = evaluate(right)
        if not isfinite(left_value) or not isfinite(right_value) or left_value * right_value >= 0:
            continue
        candidate = _bisect_root(
            evaluate,
            left,
            right,
            value_tolerance=value_tolerance,
            rate_tolerance=rate_tolerance,
            max_iter=max_iter,
        )
        roots.append(candidate)
    return roots


def _first_candidate_failure_reason(candidates: Sequence[_RootCandidate]) -> str | None:
    return next(
        (_candidate_failure_reason(candidate) for candidate in candidates if not candidate.converged),
        None,
    )


def _has_stationary_root(
    *,
    candidates: Sequence[_RootCandidate],
    stationary_candidates: Sequence[_RootCandidate],
) -> bool:
    return any(
        stationary.converged
        and any(abs(candidate.value - stationary.value) <= _XIRR_DISTINCT_ROOT_TOLERANCE for candidate in candidates)
        for stationary in stationary_candidates
    )


def _append_distinct_root(roots: list[_RootCandidate], candidate: _RootCandidate) -> None:
    for index, existing in enumerate(roots):
        if abs(candidate.value - existing.value) <= _XIRR_DISTINCT_ROOT_TOLERANCE:
            if candidate.converged and not existing.converged:
                roots[index] = candidate
            return
    roots.append(candidate)


def _candidate_failure_reason(candidate: _RootCandidate) -> str:
    if candidate.termination_reason == "iteration_limit":
        return "SOLVER_ITERATION_LIMIT_REACHED"
    return "SOLVER_RESIDUAL_OUT_OF_TOLERANCE"


def _xirr_result_from_roots(*, roots: _RootScan, base_convergence: dict) -> dict:
    candidates = roots.candidates
    root_count_detected = len(candidates)
    convergence = {
        **base_convergence,
        "root_count_detected": root_count_detected,
        "converged": False,
        "uniqueness_supported": roots.uniqueness_supported,
        "non_simple_root_detected": roots.non_simple_root_detected,
    }
    unqualified = _unqualified_root_result(roots=roots, convergence=convergence)
    if unqualified is not None:
        return unqualified
    candidate = candidates[0]
    if not candidate.converged:
        return {
            "rate": None,
            "converged": False,
            "notes": "XIRR candidate residual did not satisfy the configured tolerance.",
            "reason_code": _candidate_failure_reason(candidate),
            "convergence": _candidate_convergence(convergence=convergence, candidate=candidate),
        }
    return _successful_root_result(candidate=candidate, convergence=convergence)


def _unqualified_root_result(*, roots: _RootScan, convergence: dict) -> dict | None:
    candidates = roots.candidates
    incomplete = _incomplete_qualification_result(roots=roots, convergence=convergence)
    if incomplete is not None:
        return incomplete
    if not candidates:
        return {
            "rate": None,
            "converged": False,
            "notes": "No XIRR root found in configured bounds.",
            "reason_code": "NO_ROOT_FOUND",
            "convergence": convergence,
        }
    if roots.non_simple_root_detected and len(candidates) == 1:
        return {
            "rate": None,
            "converged": False,
            "notes": "The only XIRR root is repeated or tangent and is not safely supportable.",
            "reason_code": "NON_SIMPLE_IRR_ROOT_DETECTED",
            "convergence": convergence,
        }
    if len(candidates) > 1:
        return {
            "rate": None,
            "converged": False,
            "notes": "Multiple XIRR roots detected.",
            "reason_code": "MULTIPLE_IRR_ROOTS_DETECTED",
            "convergence": convergence,
        }
    return None


def _incomplete_qualification_result(*, roots: _RootScan, convergence: dict) -> dict | None:
    if roots.failure_reason is None and roots.uniqueness_supported:
        return None
    candidate = roots.candidates[0] if len(roots.candidates) == 1 else None
    return {
        "rate": None,
        "converged": False,
        "notes": "XIRR candidate qualification did not complete within configured controls.",
        "reason_code": roots.failure_reason or "XIRR_UNIQUENESS_NOT_SUPPORTED",
        "convergence": _candidate_convergence(convergence=convergence, candidate=candidate),
    }


def _successful_root_result(*, candidate: _RootCandidate, convergence: dict) -> dict:
    return {
        "rate": candidate.value,
        "converged": True,
        "notes": "XIRR calculation successful.",
        "convergence": {
            **convergence,
            "iterations": candidate.iterations,
            "residual": candidate.residual,
            "residual_npv": candidate.residual,
            "termination_reason": candidate.termination_reason,
            "converged": True,
        },
    }


def _candidate_convergence(*, convergence: dict, candidate: _RootCandidate | None) -> dict:
    if candidate is None:
        return convergence
    return {
        **convergence,
        "iterations": candidate.iterations,
        "residual": candidate.residual,
        "residual_npv": candidate.residual,
        "termination_reason": candidate.termination_reason,
    }


def _xirr(
    values: np.ndarray,
    dates: np.ndarray,
    *,
    annualization: Annualization | None = None,
    calendar: Calendar | None = None,
    rate_lower_bound: float = -0.999999999,
    rate_upper_bound: float = 1000.0,
    root_scan_steps: int = 512,
    tolerance: float = 1e-10,
    max_iter: int = 200,
) -> dict:
    """Calculates XIRR using log-rate bracket scanning and bisection refinement."""
    annualization = annualization or Annualization(enabled=False, basis="ACT/365")
    calendar = calendar or Calendar()
    values, dates = _net_same_day_flows(list(values), list(dates))
    gross_cash_flow_scale = float(np.sum(np.abs(values)))
    anchor_date = dates.min() if len(dates) else None
    base_convergence = _build_xirr_base_convergence(
        annualization=annualization,
        lower_bound=rate_lower_bound,
        upper_bound=rate_upper_bound,
        anchor_date=anchor_date,
        normalized_flow_count=int(len(values)),
        gross_cash_flow_scale=gross_cash_flow_scale,
        root_scan_steps=root_scan_steps,
        tolerance=tolerance,
        max_iterations=max_iter,
        solver_work_units=xirr_solver_work_units(root_scan_steps=root_scan_steps, max_iter=max_iter),
    )
    base_convergence.update(
        _xirr_calendar_metadata(
            anchor_date=anchor_date,
            dates=dates,
            annualization=annualization,
            calendar=calendar,
        )
    )
    if _xirr_has_invalid_solver_controls(
        root_scan_steps=root_scan_steps,
        tolerance=tolerance,
        max_iter=max_iter,
    ):
        return _xirr_failure(
            base_convergence=base_convergence,
            notes="Invalid XIRR solver controls.",
            reason_code="INVALID_SOLVER_CONTROLS",
        )
    initial_failure = _xirr_initial_failure(
        values=values,
        gross_cash_flow_scale=gross_cash_flow_scale,
        rate_lower_bound=rate_lower_bound,
        rate_upper_bound=rate_upper_bound,
        base_convergence=base_convergence,
    )
    if initial_failure is not None:
        return initial_failure

    if anchor_date is None:
        raise ValueError("XIRR anchor date is required after preflight validation.")
    time_diffs = _xirr_time_diffs(
        dates=dates,
        anchor_date=anchor_date,
        annualization=annualization,
        calendar=calendar,
    )

    roots = _scan_xirr_roots(
        values=values,
        time_diffs=time_diffs,
        lower_bound=rate_lower_bound,
        upper_bound=rate_upper_bound,
        root_scan_steps=root_scan_steps,
        tolerance=tolerance,
        max_iter=max_iter,
    )

    return _xirr_result_from_roots(roots=roots, base_convergence=base_convergence)


def _xirr_calendar_convergence(evidence: BusinessDayEvidence) -> dict[str, object]:
    return {
        "trading_calendar": evidence.calendar_id,
        "calendar_version": evidence.calendar_version,
        "day_count_interval": evidence.session_interval,
        "business_day_count": evidence.business_day_count,
    }


def _xirr_calendar_metadata(
    *,
    anchor_date: date | None,
    dates: np.ndarray,
    annualization: Annualization,
    calendar: Calendar,
) -> dict[str, object]:
    if anchor_date is None or not len(dates) or annualization.basis != "BUS/252":
        return {}
    evidence = business_day_evidence(
        calendar=calendar,
        start_date=anchor_date,
        end_date=dates.max(),
    )
    return _xirr_calendar_convergence(evidence)


def _dietz_denominator(*, begin_mv, cash_flows, start_date, end_date, method):
    if method == "DIETZ":
        return _simple_dietz_denominator(begin_mv=begin_mv, cash_flows=cash_flows)

    period_days = (end_date - start_date).days
    if period_days <= 0:
        return _simple_dietz_denominator(begin_mv=begin_mv, cash_flows=cash_flows)

    weighted_cash_flows = sum(cf.amount * ((end_date - cf.date).days / period_days) for cf in cash_flows)
    return begin_mv + weighted_cash_flows


def _simple_dietz_denominator(*, begin_mv, cash_flows):
    return begin_mv + (sum(cf.amount for cf in cash_flows) / 2)


@dataclass(frozen=True)
class _MWRXirrAttempt:
    result: MWRResult | None
    notes: list[str]
    reason_code: str | None = None
    convergence: MWRConvergence | None = None


@dataclass(frozen=True)
class _DietzFallbackMetadata:
    status: str
    reason_codes: list[str]
    warnings: list[str]
    fallback_from: str | None
    fallback_reason: str | None


@dataclass(frozen=True)
class _DietzReturnComponents:
    method: Literal["MODIFIED_DIETZ", "DIETZ"]
    denominator: Number
    numerator: Number
    periodic_rate: Number | None


@dataclass(frozen=True)
class _MWRPeriodBounds:
    start_date: date
    end_date: date
    period_days: int


def _xirr_attempt_convergence(xirr_result: dict) -> MWRConvergence:
    return MWRConvergence(**xirr_result.get("convergence", {}))


def _successful_xirr_mwr_attempt(
    *,
    xirr_result: dict,
    annualization: Annualization,
    start_date: date,
    end_date: date,
    period_days: int,
    convergence: MWRConvergence,
    calendar: Calendar | None = None,
) -> _MWRXirrAttempt:
    applied_calendar = calendar or Calendar()
    notes = [xirr_result["notes"]]
    return _MWRXirrAttempt(
        result=_successful_xirr_mwr_result(
            rate=xirr_result["rate"],
            annualization=annualization,
            calendar=applied_calendar,
            start_date=start_date,
            end_date=end_date,
            period_days=period_days,
            notes=notes,
            convergence=convergence,
        ),
        notes=notes,
    )


def _not_applicable_xirr_mwr_attempt(
    *,
    reason_code: str,
    start_date: date,
    end_date: date,
    notes: list[str],
    convergence: MWRConvergence,
) -> _MWRXirrAttempt:
    return _MWRXirrAttempt(
        result=MWRResult(
            mwr=0.0,
            method="DIETZ",
            start_date=start_date,
            end_date=end_date,
            notes=notes,
            convergence=convergence,
            status="NOT_APPLICABLE",
            reason_codes=[reason_code],
        ),
        notes=notes,
        reason_code=reason_code,
    )


def _fallback_xirr_mwr_attempt(*, reason_code: str, notes: list[str], convergence: MWRConvergence) -> _MWRXirrAttempt:
    notes.append("XIRR failed, falling back to Modified Dietz.")
    return _MWRXirrAttempt(result=None, notes=notes, reason_code=reason_code, convergence=convergence)


def _calculate_xirr_mwr_attempt(
    *,
    begin_mv: float,
    end_mv: float,
    cash_flows: Sequence[CashFlowLike],
    annualization: Annualization,
    start_date: date,
    end_date: date,
    period_days: int,
    solver=None,
    calendar: Calendar | None = None,
) -> _MWRXirrAttempt:
    applied_calendar = calendar or Calendar()
    xirr_start_date = start_date
    xirr_result = _calculate_xirr_solver_result(
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        annualization=annualization,
        calendar=applied_calendar,
        start_date=xirr_start_date,
        end_date=end_date,
        solver=solver,
    )
    convergence = _xirr_attempt_convergence(xirr_result)
    if xirr_result["converged"]:
        return _successful_xirr_mwr_attempt(
            xirr_result=xirr_result,
            annualization=annualization,
            calendar=applied_calendar,
            start_date=xirr_start_date,
            end_date=end_date,
            period_days=period_days,
            convergence=convergence,
        )

    notes = [xirr_result["notes"]]
    reason_code = xirr_result.get("reason_code", "SOLVER_DID_NOT_CONVERGE")
    if reason_code == "NO_ECONOMIC_CONTENT":
        return _not_applicable_xirr_mwr_attempt(
            reason_code=reason_code,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
            convergence=convergence,
        )

    return _fallback_xirr_mwr_attempt(
        reason_code=reason_code,
        notes=notes,
        convergence=convergence,
    )


def _calculate_xirr_solver_result(
    *,
    begin_mv: Number,
    end_mv: Number,
    cash_flows: Sequence[CashFlowLike],
    annualization: Annualization,
    start_date: date,
    end_date: date,
    solver=None,
    calendar: Calendar | None = None,
):
    dates = [start_date] + [cf.date for cf in cash_flows] + [end_date]
    values = [-begin_mv] + [-cf.amount for cf in cash_flows] + [end_mv]

    return _xirr(
        np.array(values),
        np.array(dates),
        annualization=annualization,
        calendar=calendar or Calendar(),
        rate_lower_bound=getattr(solver, "rate_lower_bound", -0.999999999),
        rate_upper_bound=getattr(solver, "rate_upper_bound", 1000.0),
        root_scan_steps=getattr(solver, "root_scan_steps", 512),
        tolerance=getattr(solver, "tolerance", 1e-10),
        max_iter=getattr(solver, "max_iter", 200),
    )


def _successful_xirr_mwr_result(
    *,
    rate,
    annualization,
    start_date,
    end_date,
    period_days,
    notes,
    convergence,
    calendar=None,
):
    holding_period_return = None
    if period_days > 0:
        day_count = _day_count_denominator(annualization)
        elapsed_measure = _elapsed_measure(
            start_date=start_date,
            end_date=end_date,
            annualization=annualization,
            calendar=calendar or Calendar(),
        )
        holding_period_return = (((1 + rate) ** (elapsed_measure / day_count)) - 1) * 100
    return MWRResult(
        mwr=rate * 100,
        mwr_annualized=rate * 100,
        method="XIRR",
        start_date=start_date,
        end_date=end_date,
        notes=notes,
        convergence=convergence,
        holding_period_return=holding_period_return,
        is_annualized_primary=True,
        is_approximation=False,
    )


def _calculate_dietz_mwr_result(
    *,
    begin_mv: float,
    end_mv: float,
    cash_flows: Sequence[CashFlowLike],
    calculation_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"],
    annualization: Annualization,
    start_date: date,
    end_date: date,
    period_days: int,
    notes: list[str],
    xirr_fallback_reason_code: str | None = None,
    xirr_convergence: MWRConvergence | None = None,
    calendar: Calendar | None = None,
) -> MWRResult:
    components = _dietz_return_components(
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        calculation_method=calculation_method,
        start_date=start_date,
        end_date=end_date,
    )
    if components.periodic_rate is None:
        return _zero_denominator_dietz_mwr_result(
            components=components,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
            convergence=xirr_convergence,
        )

    fallback_metadata = _dietz_fallback_metadata(
        calculation_method=calculation_method,
        xirr_fallback_reason_code=xirr_fallback_reason_code,
    )
    return _calculated_dietz_mwr_result(
        components=components,
        fallback_metadata=fallback_metadata,
        annualization=annualization,
        calendar=calendar or Calendar(),
        start_date=start_date,
        end_date=end_date,
        period_days=period_days,
        notes=notes,
        convergence=xirr_convergence,
    )


def _zero_denominator_dietz_mwr_result(
    *,
    components: _DietzReturnComponents,
    start_date: date,
    end_date: date,
    notes: list[str],
    convergence: MWRConvergence | None = None,
) -> MWRResult:
    notes.append("Calculation resulted in a zero denominator.")
    return MWRResult(
        mwr=0.0,
        method=components.method,
        start_date=start_date,
        end_date=end_date,
        notes=notes,
        status="NOT_CALCULABLE",
        reason_codes=["ZERO_DENOMINATOR"],
        convergence=convergence,
    )


def _calculated_dietz_mwr_result(
    *,
    components: _DietzReturnComponents,
    fallback_metadata: _DietzFallbackMetadata,
    annualization: Annualization,
    start_date: date,
    end_date: date,
    period_days: int,
    notes: list[str],
    convergence: MWRConvergence | None = None,
    calendar: Calendar | None = None,
) -> MWRResult:
    if components.periodic_rate is None:
        raise ValueError("Dietz periodic rate is required for calculated MWR result.")
    return MWRResult(
        mwr=components.periodic_rate * 100,
        mwr_annualized=_annualized_dietz_rate(
            periodic_rate=components.periodic_rate,
            annualization=annualization,
            calendar=calendar or Calendar(),
            start_date=start_date,
            end_date=end_date,
        ),
        method=components.method,
        start_date=start_date,
        end_date=end_date,
        notes=notes,
        status=fallback_metadata.status,
        reason_codes=fallback_metadata.reason_codes,
        warnings=fallback_metadata.warnings,
        holding_period_return=components.periodic_rate * 100,
        is_annualized_primary=False,
        fallback_from=fallback_metadata.fallback_from,
        fallback_reason=fallback_metadata.fallback_reason,
        is_approximation=True,
        convergence=convergence,
    )


def _dietz_return_components(
    *,
    begin_mv: float,
    end_mv: float,
    cash_flows: Sequence[CashFlowLike],
    calculation_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"],
    start_date: date,
    end_date: date,
) -> _DietzReturnComponents:
    net_cash_flow = sum(cf.amount for cf in cash_flows)
    method = _dietz_method_for_calculation(calculation_method)
    denominator = _dietz_denominator(
        begin_mv=begin_mv,
        cash_flows=cash_flows,
        start_date=start_date,
        end_date=end_date,
        method=method,
    )
    numerator = end_mv - begin_mv - net_cash_flow
    periodic_rate = None if denominator == 0 else numerator / denominator
    return _DietzReturnComponents(
        method=method,
        denominator=denominator,
        numerator=numerator,
        periodic_rate=periodic_rate,
    )


def _dietz_method_for_calculation(
    calculation_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"],
) -> Literal["MODIFIED_DIETZ", "DIETZ"]:
    if calculation_method in {"XIRR", "MODIFIED_DIETZ"}:
        return "MODIFIED_DIETZ"
    return "DIETZ"


def _annualized_dietz_rate(
    *,
    periodic_rate,
    annualization: Annualization,
    period_days: int | None = None,
    calendar: Calendar | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> float | None:
    elapsed_measure = _dietz_elapsed_measure(
        period_days=period_days,
        start_date=start_date,
        end_date=end_date,
        annualization=annualization,
        calendar=calendar,
    )
    if not annualization.enabled or elapsed_measure <= 0:
        return None
    ppy = _day_count_denominator(annualization)
    scale = ppy / elapsed_measure
    return ((1 + periodic_rate) ** scale - 1) * 100


def _dietz_elapsed_measure(
    *,
    period_days: int | None,
    start_date: date | None,
    end_date: date | None,
    annualization: Annualization,
    calendar: Calendar | None,
) -> int:
    if start_date is not None and end_date is not None:
        return _elapsed_measure(
            start_date=start_date,
            end_date=end_date,
            annualization=annualization,
            calendar=calendar or Calendar(),
        )
    return period_days or 0


def _dietz_fallback_metadata(
    *,
    calculation_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"],
    xirr_fallback_reason_code: str | None = None,
) -> _DietzFallbackMetadata:
    if calculation_method != "XIRR":
        return _DietzFallbackMetadata(
            status="CALCULATED",
            reason_codes=[],
            warnings=[],
            fallback_from=None,
            fallback_reason=None,
        )

    fallback_reason_code = xirr_fallback_reason_code or "SOLVER_DID_NOT_CONVERGE"
    return _DietzFallbackMetadata(
        status="FALLBACK_USED",
        reason_codes=[fallback_reason_code, "DIETZ_FALLBACK_USED"],
        warnings=["FALLBACK_METHOD_USED"],
        fallback_from="XIRR",
        fallback_reason=fallback_reason_code,
    )


def _resolve_mwr_period_bounds(
    *,
    cash_flows: Sequence[CashFlowLike],
    as_of: date,
    start_date: date | None,
) -> _MWRPeriodBounds:
    resolved_start_date = start_date
    if resolved_start_date is None:
        cash_flow_dates = [cf.date for cf in cash_flows]
        resolved_start_date = min(cash_flow_dates) if cash_flow_dates else as_of
    period_days = (as_of - resolved_start_date).days if as_of > resolved_start_date else 0
    return _MWRPeriodBounds(start_date=resolved_start_date, end_date=as_of, period_days=period_days)


def _cash_flows_outside_bounds(
    *,
    cash_flows: Sequence[CashFlowLike],
    start_date: date,
    end_date: date,
) -> list[CashFlowLike]:
    return [cash_flow for cash_flow in cash_flows if cash_flow.date < start_date or cash_flow.date > end_date]


def _validate_mwr_cash_flow_bounds(*, cash_flows: Sequence[CashFlowLike], bounds: _MWRPeriodBounds) -> None:
    outside_bounds = _cash_flows_outside_bounds(
        cash_flows=cash_flows,
        start_date=bounds.start_date,
        end_date=bounds.end_date,
    )
    if outside_bounds:
        dates = ", ".join(str(cash_flow.date) for cash_flow in outside_bounds)
        raise ValueError(f"MWR cash-flow dates outside the resolved measurement window: {dates}")


def _mwr_no_economic_content_result(
    *,
    begin_mv,
    end_mv,
    cash_flows: Sequence[CashFlowLike],
    bounds: _MWRPeriodBounds,
) -> MWRResult | None:
    if begin_mv != 0 or end_mv != 0 or cash_flows:
        return None
    return MWRResult(
        mwr=0.0,
        method="DIETZ",
        start_date=bounds.start_date,
        end_date=bounds.end_date,
        notes=["No economic content in MWR inputs."],
        status="NOT_APPLICABLE",
        reason_codes=["NO_ECONOMIC_CONTENT"],
    )


def calculate_money_weighted_return(
    begin_mv: float,
    end_mv: float,
    cash_flows: Sequence[CashFlowLike],
    calculation_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"],
    annualization: Annualization,
    as_of: date,
    start_date: date | None = None,
    calendar: Calendar | None = None,
    solver=None,
) -> MWRResult:
    """
    Orchestrates the MWR calculation using the specified method and fallback logic.
    Returns a simple MWRResult data object.
    """
    notes = []
    calendar = calendar or Calendar()
    bounds = _resolve_mwr_period_bounds(cash_flows=cash_flows, as_of=as_of, start_date=start_date)
    _validate_mwr_cash_flow_bounds(cash_flows=cash_flows, bounds=bounds)
    reason_code: str | None = None
    xirr_convergence: MWRConvergence | None = None

    no_economic_content_result = _mwr_no_economic_content_result(
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        bounds=bounds,
    )
    if no_economic_content_result is not None:
        return no_economic_content_result

    if calculation_method == "XIRR":
        xirr_attempt = _calculate_xirr_mwr_attempt(
            begin_mv=begin_mv,
            end_mv=end_mv,
            cash_flows=cash_flows,
            annualization=annualization,
            calendar=calendar,
            start_date=bounds.start_date,
            end_date=bounds.end_date,
            period_days=bounds.period_days,
            solver=solver,
        )
        if xirr_attempt.result is not None:
            return xirr_attempt.result
        notes.extend(xirr_attempt.notes)
        reason_code = xirr_attempt.reason_code
        xirr_convergence = xirr_attempt.convergence

    return _calculate_dietz_mwr_result(
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        calculation_method=calculation_method,
        annualization=annualization,
        calendar=calendar,
        start_date=bounds.start_date,
        end_date=bounds.end_date,
        period_days=bounds.period_days,
        notes=notes,
        xirr_fallback_reason_code=reason_code,
        xirr_convergence=xirr_convergence,
    )
