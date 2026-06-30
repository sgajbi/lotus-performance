# engine/mwr.py
from dataclasses import dataclass
from datetime import date
from math import exp, isfinite, log
from typing import Callable, Literal, Sequence

import numpy as np

from core.envelope import Annualization
from engine.mwr_types import CashFlowLike, MWRConvergence, MWRResult, Number


def _day_count_denominator(annualization: Annualization) -> float:
    if annualization.periods_per_year:
        return float(annualization.periods_per_year)
    if annualization.basis == "ACT/ACT":
        return 365.25
    return 365.0


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
) -> tuple[float, int]:
    left_value = func(left)
    for iteration in range(1, max_iter + 1):
        middle = (left + right) / 2
        middle_value = func(middle)
        if abs(middle_value) <= value_tolerance or abs(right - left) <= rate_tolerance:
            return middle, iteration
        if left_value * middle_value <= 0:
            right = middle
        else:
            left = middle
            left_value = middle_value
    return (left + right) / 2, max_iter


def _build_xirr_base_convergence(
    *,
    annualization: Annualization,
    lower_bound: float,
    upper_bound: float,
    anchor_date: date | None,
    normalized_flow_count: int,
    gross_cash_flow_scale: float,
) -> dict:
    return {
        "algorithm": "log_rate_bracket_scan_bisection",
        "rate_lower_bound": lower_bound,
        "rate_upper_bound": upper_bound,
        "day_count_basis": annualization.basis,
        "anchor_date": anchor_date,
        "normalized_flow_count": normalized_flow_count,
        "gross_cash_flow_scale": gross_cash_flow_scale,
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
    return rate_lower_bound <= -1 or rate_upper_bound <= rate_lower_bound


def _xirr_time_diffs(*, dates: np.ndarray, anchor_date: date, annualization: Annualization) -> np.ndarray:
    day_count = _day_count_denominator(annualization)
    return np.array([(d - anchor_date).days / day_count for d in dates])


def _scan_xirr_roots(
    *,
    values: np.ndarray,
    time_diffs: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    root_scan_steps: int,
    tolerance: float,
    max_iter: int,
    gross_cash_flow_scale: float,
    log_npv: Callable[[float], float],
) -> list[tuple[float, int, float]]:
    x_min = log(1 + lower_bound)
    x_max = log(1 + upper_bound)
    grid = np.linspace(x_min, x_max, max(root_scan_steps, 32))
    roots: list[tuple[float, int, float]] = []
    previous_x = float(grid[0])
    previous_y = log_npv(previous_x)
    for current_x_raw in grid[1:]:
        current_x = float(current_x_raw)
        current_y = log_npv(current_x)
        candidate = _xirr_root_candidate(
            previous_x=previous_x,
            previous_y=previous_y,
            current_x=current_x,
            current_y=current_y,
            tolerance=tolerance,
            max_iter=max_iter,
            gross_cash_flow_scale=gross_cash_flow_scale,
            log_npv=log_npv,
        )
        if candidate is not None:
            candidate_value, iterations = candidate
            if _is_distinct_xirr_candidate(candidate_value, roots):
                residual = _npv_at_rate(values, time_diffs, candidate_value)
                roots.append((candidate_value, iterations, residual))
        previous_x, previous_y = current_x, current_y
    return roots


def _xirr_root_candidate(
    *,
    previous_x,
    previous_y,
    current_x,
    current_y,
    tolerance,
    max_iter,
    gross_cash_flow_scale,
    log_npv,
):
    if not isfinite(previous_y) or not isfinite(current_y):
        return None
    if abs(previous_y) <= tolerance:
        return exp(previous_x) - 1, 0
    if previous_y * current_y >= 0:
        return None
    root_x, iterations = _bisect_root(
        log_npv,
        previous_x,
        current_x,
        value_tolerance=max(tolerance * max(gross_cash_flow_scale, 1.0), 1e-8),
        rate_tolerance=tolerance,
        max_iter=max_iter,
    )
    return exp(root_x) - 1, iterations


def _is_distinct_xirr_candidate(solver_value, roots):
    return all(abs(solver_value - existing_rate) > 1e-8 for existing_rate, _, _ in roots)


def _xirr_result_from_roots(*, roots: list[tuple[float, int, float]], base_convergence: dict) -> dict:
    convergence = {**base_convergence, "root_count_detected": len(roots), "converged": False}
    if not roots:
        return {
            "rate": None,
            "converged": False,
            "notes": "No XIRR root found in configured bounds.",
            "reason_code": "NO_ROOT_FOUND",
            "convergence": convergence,
        }
    if len(roots) > 1:
        return {
            "rate": None,
            "converged": False,
            "notes": "Multiple XIRR roots detected.",
            "reason_code": "MULTIPLE_IRR_ROOTS_DETECTED",
            "convergence": convergence,
        }
    rate, iterations, residual = roots[0]
    return {
        "rate": rate,
        "converged": True,
        "notes": "XIRR calculation successful.",
        "convergence": {
            **convergence,
            "iterations": iterations,
            "residual": residual,
            "residual_npv": residual,
            "converged": True,
        },
    }


def _xirr(
    values: np.ndarray,
    dates: np.ndarray,
    *,
    annualization: Annualization | None = None,
    rate_lower_bound: float = -0.999999999,
    rate_upper_bound: float = 1000.0,
    root_scan_steps: int = 512,
    tolerance: float = 1e-10,
    max_iter: int = 200,
) -> dict:
    """Calculates XIRR using log-rate bracket scanning and bisection refinement."""
    annualization = annualization or Annualization(enabled=False, basis="ACT/365")
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
    time_diffs = _xirr_time_diffs(dates=dates, anchor_date=anchor_date, annualization=annualization)

    def f_log(log_rate: float) -> float:
        return float(np.sum(values * np.exp(-log_rate * time_diffs)))

    roots = _scan_xirr_roots(
        values=values,
        time_diffs=time_diffs,
        lower_bound=rate_lower_bound,
        upper_bound=rate_upper_bound,
        root_scan_steps=root_scan_steps,
        tolerance=tolerance,
        max_iter=max_iter,
        gross_cash_flow_scale=gross_cash_flow_scale,
        log_npv=f_log,
    )

    return _xirr_result_from_roots(roots=roots, base_convergence=base_convergence)


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
) -> _MWRXirrAttempt:
    notes = [xirr_result["notes"]]
    return _MWRXirrAttempt(
        result=_successful_xirr_mwr_result(
            rate=xirr_result["rate"],
            annualization=annualization,
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


def _fallback_xirr_mwr_attempt(*, reason_code: str, notes: list[str]) -> _MWRXirrAttempt:
    notes.append("XIRR failed, falling back to Modified Dietz.")
    return _MWRXirrAttempt(result=None, notes=notes, reason_code=reason_code)


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
) -> _MWRXirrAttempt:
    xirr_start_date = start_date
    xirr_result = _calculate_xirr_solver_result(
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        annualization=annualization,
        start_date=xirr_start_date,
        end_date=end_date,
        solver=solver,
    )
    convergence = _xirr_attempt_convergence(xirr_result)
    if xirr_result["converged"]:
        return _successful_xirr_mwr_attempt(
            xirr_result=xirr_result,
            annualization=annualization,
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

    return _fallback_xirr_mwr_attempt(reason_code=reason_code, notes=notes)


def _calculate_xirr_solver_result(
    *,
    begin_mv: Number,
    end_mv: Number,
    cash_flows: Sequence[CashFlowLike],
    annualization: Annualization,
    start_date: date,
    end_date: date,
    solver=None,
):
    dates = [start_date] + [cf.date for cf in cash_flows] + [end_date]
    values = [-begin_mv] + [-cf.amount for cf in cash_flows] + [end_mv]

    return _xirr(
        np.array(values),
        np.array(dates),
        annualization=annualization,
        rate_lower_bound=getattr(solver, "rate_lower_bound", -0.999999999),
        rate_upper_bound=getattr(solver, "rate_upper_bound", 1000.0),
        root_scan_steps=getattr(solver, "root_scan_steps", 512),
        tolerance=getattr(solver, "tolerance", 1e-10),
        max_iter=getattr(solver, "max_iter", 200),
    )


def _successful_xirr_mwr_result(*, rate, annualization, start_date, end_date, period_days, notes, convergence):
    holding_period_return = None
    if period_days > 0:
        day_count = _day_count_denominator(annualization)
        holding_period_return = (((1 + rate) ** (period_days / day_count)) - 1) * 100
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
        )

    fallback_metadata = _dietz_fallback_metadata(
        calculation_method=calculation_method,
        xirr_fallback_reason_code=xirr_fallback_reason_code,
    )
    return _calculated_dietz_mwr_result(
        components=components,
        fallback_metadata=fallback_metadata,
        annualization=annualization,
        start_date=start_date,
        end_date=end_date,
        period_days=period_days,
        notes=notes,
    )


def _zero_denominator_dietz_mwr_result(
    *,
    components: _DietzReturnComponents,
    start_date: date,
    end_date: date,
    notes: list[str],
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
) -> MWRResult:
    if components.periodic_rate is None:
        raise ValueError("Dietz periodic rate is required for calculated MWR result.")
    return MWRResult(
        mwr=components.periodic_rate * 100,
        mwr_annualized=_annualized_dietz_rate(
            periodic_rate=components.periodic_rate,
            annualization=annualization,
            period_days=period_days,
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
    period_days: int,
) -> float | None:
    if not annualization.enabled or period_days <= 0:
        return None
    ppy = 365.25 if annualization.basis == "ACT/ACT" else 365.0
    scale = ppy / period_days
    return ((1 + periodic_rate) ** scale - 1) * 100


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
    solver=None,
) -> MWRResult:
    """
    Orchestrates the MWR calculation using the specified method and fallback logic.
    Returns a simple MWRResult data object.
    """
    notes = []
    bounds = _resolve_mwr_period_bounds(cash_flows=cash_flows, as_of=as_of, start_date=start_date)
    reason_code: str | None = None

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
            start_date=bounds.start_date,
            end_date=bounds.end_date,
            period_days=bounds.period_days,
            solver=solver,
        )
        if xirr_attempt.result is not None:
            return xirr_attempt.result
        notes.extend(xirr_attempt.notes)
        reason_code = xirr_attempt.reason_code

    return _calculate_dietz_mwr_result(
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        calculation_method=calculation_method,
        annualization=annualization,
        start_date=bounds.start_date,
        end_date=bounds.end_date,
        period_days=bounds.period_days,
        notes=notes,
        xirr_fallback_reason_code=reason_code,
    )
