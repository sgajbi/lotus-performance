from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any, cast

from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.models.mwr_responses import MoneyWeightedReturnResponse, MWRResult
from app.observability import record_mwr_solver_outcome
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
from app.services.mwr_mode_service import ResolvedMWRRequest
from core.envelope import Audit, Diagnostics, Meta
from engine.mwr import calculate_money_weighted_return


def calculate_mwr_result(request: MoneyWeightedReturnRequest) -> MWRResult:
    return calculate_money_weighted_return(
        begin_mv=request.begin_mv,
        end_mv=request.end_mv,
        cash_flows=request.cash_flows,
        calculation_method=request.mwr_method,
        annualization=request.annualization,
        as_of=request.as_of,
        start_date=request.start_date,
        solver=request.solver,
    )


def build_mwr_response(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    resolved_request: ResolvedMWRRequest,
    mwr_result: MWRResult,
    input_fingerprint: str,
    calculation_hash: str,
    engine_version: str,
) -> MoneyWeightedReturnResponse:
    mwr_request = resolved_request.mwr_request
    calculation_supportability = build_calculation_supportability(
        input_row_count=len(mwr_request.cash_flows) + 2,
        resolved_period_count=1,
        latest_observation_date=mwr_result.end_date,
        report_end_date=mwr_request.as_of,
        minimum_input_row_count=2,
    )
    record_supportability_metric(operation="mwr", supportability=calculation_supportability)
    record_mwr_solver_outcome(
        input_mode=request.input_mode.value,
        method=mwr_result.method,
        status=mwr_result.status,
        reason_codes=mwr_result.reason_codes,
        fallback_used=mwr_result.fallback_from is not None or mwr_result.is_approximation,
    )
    reporting_currency = (
        resolved_request.currency_evidence.reporting_currency
        if resolved_request.currency_evidence is not None
        else mwr_request.report_ccy or mwr_request.currency
    )

    return MoneyWeightedReturnResponse.model_validate(
        {
            "calculation_id": request.calculation_id,
            "portfolio_id": request.portfolio_id,
            "input_mode": request.input_mode,
            "money_weighted_return": mwr_result.mwr,
            "mwr_annualized": mwr_result.mwr_annualized,
            "method": mwr_result.method,
            "status": mwr_result.status,
            "reason_codes": mwr_result.reason_codes,
            "warnings": mwr_result.warnings,
            "holding_period_return": mwr_result.holding_period_return,
            "is_annualized_primary": mwr_result.is_annualized_primary,
            "fallback_from": mwr_result.fallback_from,
            "fallback_reason": mwr_result.fallback_reason,
            "is_approximation": mwr_result.is_approximation,
            "start_date": mwr_result.start_date,
            "end_date": mwr_result.end_date,
            "notes": mwr_result.notes,
            "convergence": mwr_result.convergence,
            "cashflows_used": mwr_request.cash_flows if mwr_request.emit_cashflows_used else None,
            "reporting_currency": reporting_currency,
            "currency_evidence": (
                _decimal_safe_dataclass_payload(resolved_request.currency_evidence)
                if resolved_request.currency_evidence is not None
                else None
            ),
            "calculation_supportability": calculation_supportability,
            "meta": Meta(
                calculation_id=request.calculation_id,
                engine_version=engine_version,
                precision_mode=mwr_request.precision_mode,
                annualization=mwr_request.annualization,
                calendar=mwr_request.calendar,
                periods={"type": "EXPLICIT", "start": str(mwr_result.start_date), "end": str(mwr_result.end_date)},
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            ),
            "diagnostics": Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=mwr_result.start_date,
                notes=mwr_result.notes,
            ),
            "audit": Audit(counts={"cashflows": len(mwr_request.cash_flows)}),
        }
    )


def _decimal_safe_dataclass_payload(value: object) -> object:
    if not is_dataclass(value):
        return value
    payload = asdict(cast(Any, value))
    return _stringify_decimals(payload)


def _stringify_decimals(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_stringify_decimals(item) for item in value]
    if isinstance(value, dict):
        return {key: _stringify_decimals(item) for key, item in value.items()}
    return value
