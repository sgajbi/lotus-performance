from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionResponse
from app.services.analytics_observation_dates import latest_observation_date
from app.services.attribution_response_service import build_single_period_attribution_response
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from core.envelope import Meta
from core.periods import resolve_periods
from engine.attribution import aggregate_attribution_results, run_attribution_calculations
from engine.exceptions import EngineCalculationError, InvalidEngineInputError


@dataclass(frozen=True)
class _AttributionExecutionWindow:
    periods_to_resolve: Sequence[Any]
    resolved_periods: Sequence[Any]
    master_start_date: Any
    master_end_date: Any
    master_request: AttributionRequest


def _count_attribution_benchmark_rows(request: AttributionRequest) -> int:
    return sum(len(group.observations) for group in request.benchmark_groups_data)


def _count_optional_nested_rows(items: Sequence[Any] | None, attribute: str) -> int:
    return sum(len(getattr(item, attribute)) for item in (items or []))


def _count_direct_portfolio_rows(request: AttributionRequest) -> int:
    return len(request.portfolio_data.valuation_points) if request.portfolio_data is not None else 0


def _count_attribution_portfolio_rows(request: AttributionRequest) -> int:
    return (
        _count_direct_portfolio_rows(request)
        + _count_optional_nested_rows(request.instruments_data, "valuation_points")
        + _count_optional_nested_rows(request.portfolio_groups_data, "observations")
    )


def _count_attribution_input_rows(request: AttributionRequest) -> int:
    return _count_attribution_portfolio_rows(request) + _count_attribution_benchmark_rows(request)


def _latest_attribution_observation_date(request: AttributionRequest):
    return latest_observation_date(
        [
            *_portfolio_observation_dates(request),
            *_instrument_observation_dates(request),
            *_portfolio_group_observation_dates(request),
            *_benchmark_group_observation_dates(request),
        ]
    )


def _portfolio_observation_dates(request: AttributionRequest) -> list[object]:
    if request.portfolio_data is None:
        return []
    return [point.perf_date for point in request.portfolio_data.valuation_points]


def _instrument_observation_dates(request: AttributionRequest) -> list[object]:
    return [point.perf_date for instrument in request.instruments_data or [] for point in instrument.valuation_points]


def _portfolio_group_observation_dates(request: AttributionRequest) -> list[object]:
    return [
        observation["date"]
        for group in request.portfolio_groups_data or []
        for observation in group.observations
        if observation.get("date")
    ]


def _benchmark_group_observation_dates(request: AttributionRequest) -> list[object]:
    return [observation.date for group in request.benchmark_groups_data for observation in group.observations]


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


def _build_attribution_results_by_period(
    *,
    effects_df: pd.DataFrame,
    request: AttributionRequest,
    resolved_periods: Sequence[Any],
    lineage_data: dict[str, Any],
) -> dict[str, Any]:
    results_by_period: dict[str, Any] = {}
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
        results_by_period[period.name] = build_single_period_attribution_response(period_result)
    return results_by_period


def _build_attribution_meta(
    *,
    request: AttributionRequest,
    app_version: str,
    periods_to_resolve: Sequence[Any],
    master_start_date,
    master_end_date,
    input_fingerprint: str,
    calculation_hash: str,
) -> Meta:
    return Meta(
        calculation_id=request.calculation_id,
        engine_version=app_version,
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


def _build_attribution_supportability(request: AttributionRequest, *, resolved_period_count: int):
    calculation_supportability = build_calculation_supportability(
        input_row_count=_count_attribution_input_rows(request),
        resolved_period_count=resolved_period_count,
        latest_observation_date=_latest_attribution_observation_date(request),
        report_end_date=request.report_end_date,
        benchmark_row_count=_count_attribution_benchmark_rows(request),
    )
    record_supportability_metric(operation="attribution", supportability=calculation_supportability)
    return calculation_supportability


def _attribution_benchmark_context(
    *,
    resolved_benchmark_id: str | None,
    resolved_benchmark_return_source: str | None,
) -> dict[str, str] | None:
    if resolved_benchmark_id is None or resolved_benchmark_return_source is None:
        return None
    return {
        "benchmark_id": resolved_benchmark_id,
        "return_source": resolved_benchmark_return_source,
    }


def _resolve_attribution_execution_window(request: AttributionRequest) -> _AttributionExecutionWindow:
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

    return _AttributionExecutionWindow(
        periods_to_resolve=periods_to_resolve,
        resolved_periods=resolved_periods,
        master_start_date=master_start_date,
        master_end_date=master_end_date,
        master_request=master_request,
    )


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
        execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_EXECUTION)
        execution_stage_started = True
        execution_window = _resolve_attribution_execution_window(request)

        effects_df, lineage_data = run_attribution_calculations(execution_window.master_request)

        results_by_period = _build_attribution_results_by_period(
            effects_df=effects_df,
            request=request,
            resolved_periods=execution_window.resolved_periods,
            lineage_data=lineage_data,
        )

        meta = _build_attribution_meta(
            request=request,
            app_version=active_settings.APP_VERSION,
            periods_to_resolve=execution_window.periods_to_resolve,
            master_start_date=execution_window.master_start_date,
            master_end_date=execution_window.master_end_date,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        calculation_supportability = _build_attribution_supportability(
            request,
            resolved_period_count=len(results_by_period),
        )

        response_model = AttributionResponse(
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            input_mode=input_mode,
            model=request.model,
            linking=request.linking,
            results_by_period=results_by_period,
            benchmark_context=_attribution_benchmark_context(
                resolved_benchmark_id=resolved_benchmark_id,
                resolved_benchmark_return_source=resolved_benchmark_return_source,
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
