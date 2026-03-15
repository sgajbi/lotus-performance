from __future__ import annotations

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionResponse
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from core.envelope import Meta
from core.periods import resolve_periods
from engine.attribution import aggregate_attribution_results, run_attribution_calculations
from engine.exceptions import EngineCalculationError, InvalidEngineInputError


def calculate_attribution(
    request: AttributionRequest,
    *,
    input_fingerprint: str,
    calculation_hash: str,
    input_mode: AttributionInputMode = AttributionInputMode.STATELESS,
) -> AttributionResponse:
    active_settings = get_settings()
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    lineage_stage_started = False

    try:
        execution_registry.start_stage(request.calculation_id, "execution")
        execution_stage_started = True
        periods_to_resolve = [analysis.period for analysis in request.analyses]
        resolved_periods = resolve_periods(periods_to_resolve, request.report_end_date, request.report_start_date)

        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)

        master_request = request.model_copy(deep=True)
        master_request.report_start_date = master_start_date
        master_request.report_end_date = master_end_date

        effects_df, lineage_data = run_attribution_calculations(master_request)

        results_by_period = {}
        for period in resolved_periods:
            period_slice_df = effects_df[
                (effects_df.index.get_level_values("date") >= pd.to_datetime(period.start_date))
                & (effects_df.index.get_level_values("date") <= pd.to_datetime(period.end_date))
            ].copy()

            if period_slice_df.empty:
                continue

            period_result, aggregation_lineage = aggregate_attribution_results(period_slice_df, request)
            if aggregation_lineage:
                lineage_data.update({f"{period.name}_{key}": value for key, value in aggregation_lineage.items()})
            results_by_period[period.name] = period_result

        meta = Meta(
            calculation_id=request.calculation_id,
            engine_version=active_settings.APP_VERSION,
            precision_mode=request.precision_mode,
            annualization=request.annualization,
            calendar=request.calendar,
            periods={
                "requested": [p.value for p in periods_to_resolve],
                "master_start": str(master_start_date),
                "master_end": str(master_end_date),
            },
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )

        response_model = AttributionResponse(
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            input_mode=input_mode,
            model=request.model,
            linking=request.linking,
            results_by_period=results_by_period,
            meta=meta,
        )

        complete_execution_with_lineage(
            calculation_id=request.calculation_id,
            calculation_type="Attribution",
            request_model=request,
            response_model=response_model,
            execution_details={"period_count": len(results_by_period)},
            calculation_details=lineage_data,
        )
        return response_model
    except (InvalidEngineInputError, ValueError, NotImplementedError) as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc),
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EngineCalculationError as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"Calculation Error: {exc.message}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Calculation Error: {exc.message}",
        ) from exc
    except HTTPException as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise
    except Exception as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected server error occurred: {str(exc)}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred: {str(exc)}",
        ) from exc
