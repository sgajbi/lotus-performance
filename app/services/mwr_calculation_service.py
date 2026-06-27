from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
from typing import Any, cast

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.responses import PerformanceCalculationSupportability
from app.observability import record_mwr_solver_outcome
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_MWR
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
from app.services.execution_lifecycle_service import complete_execution_with_lineage, record_execution_failure
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from app.services.mwr_mode_service import ResolvedMWRRequest, resolve_mwr_request
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.submission_fencing_service import register_sync_execution_or_raise
from core.envelope import Audit, Diagnostics, Meta
from engine.mwr import calculate_money_weighted_return
from engine.mwr_types import MWRResult


@dataclass(frozen=True)
class _ResolvedMWRExecution:
    resolved_request: ResolvedMWRRequest
    input_fingerprint: str
    calculation_hash: str


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
    calculation_supportability = _mwr_calculation_supportability(
        mwr_request=mwr_request,
        mwr_result=mwr_result,
    )
    _record_mwr_response_metrics(
        request=request,
        mwr_result=mwr_result,
        calculation_supportability=calculation_supportability,
    )

    return MoneyWeightedReturnResponse.model_validate(
        _build_mwr_response_payload(
            request=request,
            resolved_request=resolved_request,
            mwr_result=mwr_result,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            engine_version=engine_version,
            calculation_supportability=calculation_supportability,
        )
    )


def _mwr_calculation_supportability(
    *,
    mwr_request: MoneyWeightedReturnRequest,
    mwr_result: MWRResult,
) -> PerformanceCalculationSupportability:
    return build_calculation_supportability(
        input_row_count=len(mwr_request.cash_flows) + 2,
        resolved_period_count=1,
        latest_observation_date=mwr_result.end_date,
        report_end_date=mwr_request.as_of,
        minimum_input_row_count=2,
    )


def _record_mwr_response_metrics(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    mwr_result: MWRResult,
    calculation_supportability: PerformanceCalculationSupportability,
) -> None:
    record_supportability_metric(operation="mwr", supportability=calculation_supportability)
    record_mwr_solver_outcome(
        input_mode=request.input_mode.value,
        method=mwr_result.method,
        status=mwr_result.status,
        reason_codes=mwr_result.reason_codes,
        fallback_used=mwr_result.fallback_from is not None or bool(mwr_result.is_approximation),
    )


def _build_mwr_response_payload(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    resolved_request: ResolvedMWRRequest,
    mwr_result: MWRResult,
    input_fingerprint: str,
    calculation_hash: str,
    engine_version: str,
    calculation_supportability: PerformanceCalculationSupportability,
) -> dict[str, object]:
    mwr_request = resolved_request.mwr_request
    return {
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
        "convergence": asdict(mwr_result.convergence) if mwr_result.convergence is not None else None,
        "cashflows_used": mwr_request.cash_flows if mwr_request.emit_cashflows_used else None,
        "reporting_currency": _mwr_reporting_currency(resolved_request=resolved_request),
        "currency_evidence": _mwr_currency_evidence_payload(resolved_request=resolved_request),
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


def _mwr_reporting_currency(*, resolved_request: ResolvedMWRRequest) -> str | None:
    if resolved_request.currency_evidence is not None:
        return resolved_request.currency_evidence.reporting_currency
    mwr_request = resolved_request.mwr_request
    return mwr_request.report_ccy or mwr_request.currency


def _mwr_currency_evidence_payload(*, resolved_request: ResolvedMWRRequest) -> object:
    if resolved_request.currency_evidence is None:
        return None
    return _decimal_safe_dataclass_payload(resolved_request.currency_evidence)


def _decimal_safe_dataclass_payload(value: object) -> object:
    if not is_dataclass(value):
        return value
    payload = asdict(cast(Any, value))
    return _stringify_decimals(payload)


def _stringify_decimals(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    collection_payload = _stringify_decimal_collection(value)
    return value if collection_payload is None else collection_payload


def _stringify_decimal_collection(value: object) -> object | None:
    if isinstance(value, list):
        return [_stringify_decimals(item) for item in value]
    if isinstance(value, dict):
        return {key: _stringify_decimals(item) for key, item in value.items()}
    return None


def _build_mwr_lineage_dataframe(
    mwr_request: MoneyWeightedReturnRequest,
) -> pd.DataFrame:
    lineage_rows = [
        {"date": str(mwr_request.start_date or mwr_request.as_of), "type": "begin_mv", "amount": mwr_request.begin_mv}
    ]
    lineage_rows.extend(
        [{"date": str(cf.date), "type": "cash_flow", "amount": cf.amount} for cf in mwr_request.cash_flows]
    )
    lineage_rows.append({"date": str(mwr_request.as_of), "type": "end_mv", "amount": mwr_request.end_mv})
    return pd.DataFrame(lineage_rows)


async def calculate_mwr_response(
    request: MoneyWeightedReturnAnalyticsRequest,
) -> MoneyWeightedReturnResponse:
    """Calculate MWR and emit execution-lineage artifacts for sync workflow execution."""
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, active_settings.APP_VERSION)
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_MWR,
        portfolio_id=request.portfolio_id,
        requested_window=_mwr_requested_window(request),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    lineage_stage_started = False

    try:
        resolved_execution = await _resolve_mwr_execution_request(
            request=request,
            active_settings=active_settings,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        resolved_request = resolved_execution.resolved_request
        mwr_request = resolved_request.mwr_request
        execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_EXECUTION)
        execution_stage_started = True
        mwr_result = calculate_mwr_result(mwr_request)
        response_model = build_mwr_response(
            request=request,
            resolved_request=resolved_request,
            mwr_result=mwr_result,
            input_fingerprint=resolved_execution.input_fingerprint,
            calculation_hash=resolved_execution.calculation_hash,
            engine_version=active_settings.APP_VERSION,
        )
    except HTTPException:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message="HTTPException raised during MWR execution.",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise
    except Exception as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected error occurred during MWR calculation: {str(e)}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during MWR calculation: {str(e)}",
        )

    _complete_mwr_execution(
        request=request,
        mwr_request=mwr_request,
        response_model=response_model,
    )

    return response_model


async def _resolve_mwr_execution_request(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    active_settings: Any,
    input_fingerprint: str,
    calculation_hash: str,
) -> _ResolvedMWRExecution:
    resolved_request = await resolve_mwr_request(request, settings=active_settings)
    if resolved_request.input_mode != MWRInputMode.STATEFUL:
        return _ResolvedMWRExecution(
            resolved_request=resolved_request,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )

    stateful_fingerprint, stateful_hash = generate_request_fingerprint(
        resolved_request.mwr_request,
        active_settings.APP_VERSION,
    )
    execution_registry.update_execution_identity(
        request.calculation_id,
        input_fingerprint=stateful_fingerprint,
        calculation_hash=stateful_hash,
    )
    return _ResolvedMWRExecution(
        resolved_request=resolved_request,
        input_fingerprint=stateful_fingerprint,
        calculation_hash=stateful_hash,
    )


def _complete_mwr_execution(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    mwr_request: MoneyWeightedReturnRequest,
    response_model: MoneyWeightedReturnResponse,
) -> None:
    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type=ANALYTICS_WORKFLOW_MWR,
        request_model=mwr_request if request.input_mode == MWRInputMode.STATEFUL else request,
        response_model=response_model,
        execution_details={"cashflows": len(mwr_request.cash_flows)},
        calculation_details={"mwr_cashflow_schedule.csv": _build_mwr_lineage_dataframe(mwr_request)},
    )


def _mwr_requested_window(request: MoneyWeightedReturnAnalyticsRequest) -> dict[str, str | None]:
    start_date = None
    if request.input_mode == MWRInputMode.STATEFUL and request.stateful_input is not None:
        start_date = str(request.stateful_input.window_start_date)
    elif request.start_date is not None:
        start_date = str(request.start_date)
    return {"as_of": str(request.as_of), "start_date": start_date}
