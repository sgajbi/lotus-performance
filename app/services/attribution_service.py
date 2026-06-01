from __future__ import annotations

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionResponse
from app.services.analytics_observation_dates import latest_observation_date
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from core.envelope import Meta
from core.periods import resolve_periods
from engine.attribution import aggregate_attribution_results, run_attribution_calculations
from engine.exceptions import EngineCalculationError, InvalidEngineInputError


def _count_attribution_benchmark_rows(request: AttributionRequest) -> int:
    return sum(len(group.observations) for group in request.benchmark_groups_data)


def _count_attribution_input_rows(request: AttributionRequest) -> int:
    portfolio_observations = len(request.portfolio_data.valuation_points) if request.portfolio_data is not None else 0
    instrument_observations = sum(len(instrument.valuation_points) for instrument in (request.instruments_data or []))
    portfolio_group_observations = sum(len(group.observations) for group in (request.portfolio_groups_data or []))
    return (
        portfolio_observations
        + instrument_observations
        + portfolio_group_observations
        + _count_attribution_benchmark_rows(request)
    )


def _latest_attribution_observation_date(request: AttributionRequest):
    dates: list[object] = []
    if request.portfolio_data is not None:
        dates.extend(point.perf_date for point in request.portfolio_data.valuation_points)
    for instrument in request.instruments_data or []:
        dates.extend(point.perf_date for point in instrument.valuation_points)
    for group in request.portfolio_groups_data or []:
        dates.extend(observation.get("date") for observation in group.observations if observation.get("date"))
    for group in request.benchmark_groups_data:
        dates.extend(observation.date for observation in group.observations)
    return latest_observation_date(dates)


def _slice_attribution_effects_by_period(
    effects_df: pd.DataFrame,
    *,
    start_date,
    end_date,
) -> pd.DataFrame:
    effect_dates = effects_df.index.get_level_values("date")
    start_timestamp = pd.Timestamp(start_date)
    end_timestamp = pd.Timestamp(end_date)
    return effects_df[(effect_dates >= start_timestamp) & (effect_dates <= end_timestamp)].copy()


def calculate_attribution(
    request: AttributionRequest,
    *,
    input_fingerprint: str,
    calculation_hash: str,
    input_mode: AttributionInputMode = AttributionInputMode.STATELESS,
    resolved_benchmark_id: str | None = None,
    resolved_benchmark_return_source: str | None = None,
) -> AttributionResponse:
    active_settings = get_settings()
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    lineage_stage_started = False

    try:
        execution_registry.start_stage(request.calculation_id, "execution")
        execution_stage_started = True
        periods_to_resolve = [analysis.period for analysis in request.analyses]
        resolved_periods = resolve_periods(
            periods_to_resolve,
            request.report_end_date,
            request.report_start_date,
            explicit_start_date=request.report_start_date,
        )

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
            period_slice_df = _slice_attribution_effects_by_period(
                effects_df,
                start_date=period.start_date,
                end_date=period.end_date,
            )

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
        calculation_supportability = build_calculation_supportability(
            input_row_count=_count_attribution_input_rows(request),
            resolved_period_count=len(results_by_period),
            latest_observation_date=_latest_attribution_observation_date(request),
            report_end_date=request.report_end_date,
            benchmark_row_count=_count_attribution_benchmark_rows(request),
        )
        record_supportability_metric(operation="attribution", supportability=calculation_supportability)

        response_model = AttributionResponse(
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            input_mode=input_mode,
            model=request.model,
            linking=request.linking,
            results_by_period=results_by_period,
            benchmark_context=(
                {
                    "benchmark_id": resolved_benchmark_id,
                    "return_source": resolved_benchmark_return_source,
                }
                if resolved_benchmark_id is not None and resolved_benchmark_return_source is not None
                else None
            ),
            calculation_supportability=calculation_supportability,
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
