"""Invoke the existing MWR service, preserving its actual numeric disposition."""

from dataclasses import asdict
from decimal import Decimal

from app.models.composite_pooled_mwr import CompositePooledMWRRequest, PooledMonetaryObservation, PooledSolverOutcome
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.services.composite_pooled_mwr.source_binding import require_pooled_day_basis
from app.services.mwr_calculation_service import calculate_mwr_result
from core.annualize import periods_per_year_for_basis
from core.monetary_input import validate_calculated_money_model
from engine.numerical_boundary import NumericalDomainError


def calculate_pooled_xirr(
    request: CompositePooledMWRRequest, observation: PooledMonetaryObservation
) -> PooledSolverOutcome:
    require_pooled_day_basis(request)
    mwr_request = validate_calculated_money_model(
        MoneyWeightedReturnRequest,
        {
            "calculation_id": request.calculation_id,
            "portfolio_id": observation.composite_id,
            "begin_mv": observation.opening_value,
            "end_mv": observation.terminal_value,
            "cash_flows": [
                {"date": flow.economic_date, "amount": flow.amount} for flow in observation.portfolio_cash_flows
            ],
            "start_date": observation.period_start,
            "as_of": observation.period_end,
            "currency": observation.reporting_currency,
            "mwr_method": "XIRR",
            "precision_mode": "FLOAT64",
            "solver": request.solver,
            "calendar": request.calendar,
            "annualization": request.annualization,
        },
    )
    try:
        result = calculate_mwr_result(mwr_request)
    except NumericalDomainError as exc:
        return PooledSolverOutcome(
            availability="NOT_CALCULABLE",
            actual_method="XIRR",
            return_value=None,
            annualized_return=None,
            holding_period_return=None,
            reason_codes=("NUMERICAL_DOMAIN_UNSUPPORTED",),
            diagnostics={
                "actual_interval_start": observation.period_start,
                "actual_interval_end": observation.period_end,
                "root_precision": "FLOAT64",
                "actual_algorithm": None,
                "projection_failure": str(exc),
                "solver_controls": request.solver.model_dump(mode="json"),
            },
            original_solver_result={"error_type": type(exc).__name__, "message": str(exc)},
        )
    unique_xirr = _qualified_xirr(result)
    allowed_fallback = _admitted_fallback(request, result)
    available = unique_xirr or allowed_fallback
    return PooledSolverOutcome(
        availability=_outcome_availability(unique_xirr, allowed_fallback),
        actual_method=result.method,
        return_value=_percentage_to_ratio(result.mwr) if available else None,
        annualized_return=_percentage_to_ratio(result.mwr_annualized) if available else None,
        holding_period_return=_percentage_to_ratio(result.holding_period_return) if available else None,
        reason_codes=_outcome_reasons(result, available),
        diagnostics=_diagnostics(request, observation, result),
        original_solver_result=asdict(result),
    )


def _qualified_xirr(result):
    convergence = result.convergence
    return (
        result.method == "XIRR"
        and result.status == "CALCULATED"
        and convergence is not None
        and convergence.converged is True
        and convergence.root_count_detected == 1
        and convergence.uniqueness_supported is True
        and not convergence.non_simple_root_detected
    )


def _admitted_fallback(request, result):
    return (
        request.fallback_policy == "ALLOW_MODIFIED_DIETZ"
        and result.method == "MODIFIED_DIETZ"
        and result.status == "FALLBACK_USED"
    )


def _outcome_reasons(result, available):
    if result.reason_codes:
        return tuple(result.reason_codes)
    return () if available else ("XIRR_NOT_CALCULABLE",)


def _outcome_availability(unique_xirr, allowed_fallback):
    if unique_xirr:
        return "AVAILABLE"
    return "FALLBACK_ANALYSIS" if allowed_fallback else "NOT_CALCULABLE"


def _percentage_to_ratio(value):
    if value is None:
        return None
    percentage = Decimal(str(value))
    if not percentage.is_finite():
        raise NumericalDomainError("MWR percentage output is not finite.")
    sign, digits, exponent = percentage.as_tuple()
    if not isinstance(exponent, int):
        raise NumericalDomainError("MWR percentage output has no finite decimal exponent.")
    # Adjust the decimal exponent exactly once, without caller-context rounding.
    return Decimal((sign, digits, exponent - 2))


def _diagnostics(request, observation, result):
    convergence = {} if result.convergence is None else asdict(result.convergence)
    anchor = convergence.get("anchor_date") or observation.period_start
    dates = [flow.economic_date for flow in observation.investor_cash_flows if flow.amount != 0]
    divisor = periods_per_year_for_basis(basis=request.annualization.basis)
    measures = [(day - anchor).days for day in dates]
    return {
        "convergence": convergence,
        "actual_interval_start": result.start_date,
        "actual_interval_end": result.end_date,
        "actual_calendar_days": (result.end_date - result.start_date).days,
        "day_count_basis": request.annualization.basis,
        "resolved_year_divisor": divisor,
        "time_axis": [
            {"economic_date": day, "elapsed_measure": measure, "year_fraction": measure / divisor}
            for day, measure in zip(dates, measures, strict=True)
        ],
        "date_basis_note": "Reviewed ACT/365 convention: actual elapsed calendar days divided by 365.",
        "root_selection_policy": "UNIQUE_QUALIFIED_ROOT_WITHIN_CONFIGURED_BOUNDS",
        "solver_control_method": request.solver.method,
        "actual_algorithm": convergence.get("algorithm"),
        "residual_units": "REPORTING_CURRENCY_NPV_AT_SOLVER_ANCHOR_FLOAT64",
        "residual_note": "Existing residual and residual_npv are the same solver NPV residual; no independent high-precision residual is invented.",
        "source_percentage_units": "PERCENT",
        "output_units": "DECIMAL_FRACTION",
        "is_annualized_primary": result.is_annualized_primary,
        "fallback_from": result.fallback_from,
        "fallback_reason": result.fallback_reason,
        "is_approximation": result.is_approximation,
        "notes": result.notes,
        "warnings": result.warnings,
    }
