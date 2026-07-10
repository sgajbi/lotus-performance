from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, NoReturn, Sequence
from uuid import UUID

import pandas as pd

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
from app.services.execution_stage_errors import is_mappable_application_error, safe_unexpected_failure_message
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from app.services.fail_fast_policy import enforce_core_analytics_fail_fast
from core.envelope import Audit, Diagnostics, Meta
from core.errors import APIBadRequestError, APIError, APIInternalServerError
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
        observation_date
        for observation in _iter_portfolio_group_observations(request)
        if (observation_date := _portfolio_group_observation_date(observation)) is not None
    ]


def _iter_portfolio_group_observations(request: AttributionRequest) -> Iterator[dict[str, Any]]:
    for group in request.portfolio_groups_data or []:
        yield from group.observations


def _portfolio_group_observation_date(observation: dict[str, Any]) -> object | None:
    return observation.get("date") or None


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
        period_response = _build_single_attribution_period_response(
            effects_df,
            request=request,
            period=period,
            lineage_data=lineage_data,
        )
        if period_response is None:
            continue
        results_by_period[period.name] = period_response
    return results_by_period


def _build_single_attribution_period_response(
    effects_df: pd.DataFrame,
    *,
    request: AttributionRequest,
    period: Any,
    lineage_data: dict[str, Any],
) -> dict[str, Any] | None:
    period_slice_df = _slice_attribution_effects_by_period(
        effects_df,
        start_date=period.start_date,
        end_date=period.end_date,
    )

    if period_slice_df.empty:
        return None

    period_result, aggregation_lineage = aggregate_attribution_results(period_slice_df, request)
    _record_attribution_period_lineage(
        lineage_data,
        period_name=period.name,
        aggregation_lineage=aggregation_lineage,
    )
    return build_single_period_attribution_response(period_result)


def _record_attribution_period_lineage(
    lineage_data: dict[str, Any],
    *,
    period_name: str,
    aggregation_lineage: dict[str, Any],
) -> None:
    if aggregation_lineage:
        lineage_data.update({f"{period_name}_{key}": value for key, value in aggregation_lineage.items()})


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


def _build_attribution_diagnostics(
    *,
    execution_window: _AttributionExecutionWindow,
    results_by_period: dict[str, Any],
    resolved_benchmark_id: str | None,
) -> Diagnostics:
    notes = [
        "Attribution diagnostics use period-level status, reason codes, supportability evidence, and residual materiality as the authoritative degraded-state contract.",
        "Benchmark version, classification version, calendar policy, derivative flags, and short flags are source-limited unless supplied by upstream contracts.",
    ]
    if resolved_benchmark_id is None:
        notes.append("No benchmark context was resolved for this attribution response.")
    return Diagnostics(
        nip_days=0,
        reset_days=0,
        effective_period_start=execution_window.master_start_date,
        notes=notes,
        samples={
            "period_status_counts": [_period_status_counts(results_by_period)],
            "residual_materiality_counts": [_residual_materiality_counts(results_by_period)],
            "supportability_evidence_counts": [_supportability_evidence_counts(results_by_period)],
        },
    )


def _build_attribution_audit(
    *,
    request: AttributionRequest,
    results_by_period: dict[str, Any],
    resolved_benchmark_id: str | None,
) -> Audit:
    return Audit(
        counts={
            "input_row_count": _count_attribution_input_rows(request),
            "portfolio_row_count": _count_attribution_portfolio_rows(request),
            "benchmark_row_count": _count_attribution_benchmark_rows(request),
            "resolved_period_count": len(results_by_period),
            "level_count": _attribution_level_count(results_by_period),
            "group_count": _attribution_group_count(results_by_period),
            "reason_count": _attribution_reason_count(results_by_period),
            "supportability_issue_count": _supportability_issue_count(results_by_period),
            "periods_with_material_residual": _residual_classification_count(results_by_period, "material"),
            "periods_with_watch_residual": _residual_classification_count(results_by_period, "watch"),
            "benchmark_context_count": 1 if resolved_benchmark_id is not None else 0,
        }
    )


def _period_status_counts(results_by_period: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for period in results_by_period.values():
        status = getattr(period, "status", None) or period.get("status", "unknown")
        counts[str(status)] = counts.get(str(status), 0) + 1
    return counts


def _residual_materiality_counts(results_by_period: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for period in results_by_period.values():
        classification = _residual_classification(period)
        counts[classification] = counts.get(classification, 0) + 1
    return counts


def _supportability_evidence_counts(results_by_period: dict[str, Any]) -> dict[str, int]:
    total_counts = {
        "portfolio_only_group_count": 0,
        "benchmark_only_group_count": 0,
        "unclassified_group_count": 0,
        "missing_benchmark_return_count": 0,
        "negative_weight_count": 0,
        "zero_portfolio_exposure_count": 0,
    }
    for period in results_by_period.values():
        supportability_evidence = _period_supportability_evidence(period)
        for key in total_counts:
            total_counts[key] += int(_period_field_value(supportability_evidence, key, default=0) or 0)
    return total_counts


def _attribution_level_count(results_by_period: dict[str, Any]) -> int:
    return sum(len(_period_field_value(period, "levels", default=[]) or []) for period in results_by_period.values())


def _attribution_group_count(results_by_period: dict[str, Any]) -> int:
    return sum(
        len(_period_field_value(level, "groups", default=[]) or [])
        for period in results_by_period.values()
        for level in (_period_field_value(period, "levels", default=[]) or [])
    )


def _attribution_reason_count(results_by_period: dict[str, Any]) -> int:
    return sum(len(_period_field_value(period, "reasons", default=[]) or []) for period in results_by_period.values())


def _supportability_issue_count(results_by_period: dict[str, Any]) -> int:
    return sum(_supportability_evidence_counts(results_by_period).values())


def _residual_classification_count(results_by_period: dict[str, Any], classification: str) -> int:
    return sum(1 for period in results_by_period.values() if _residual_classification(period) == classification)


def _residual_classification(period: Any) -> str:
    reconciliation = _period_field_value(period, "reconciliation", default={}) or {}
    residual_materiality = _period_field_value(reconciliation, "residual_materiality", default={}) or {}
    return str(_period_field_value(residual_materiality, "classification", default="unknown") or "unknown")


def _period_supportability_evidence(period: Any) -> Any:
    return _period_field_value(period, "supportability_evidence", default={}) or {}


def _period_field_value(value: Any, field_name: str, *, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


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


def _build_completed_attribution_response(
    *,
    request: AttributionRequest,
    input_mode: AttributionInputMode,
    results_by_period: dict[str, Any],
    execution_window: _AttributionExecutionWindow,
    app_version: str,
    input_fingerprint: str,
    calculation_hash: str,
    resolved_benchmark_id: str | None,
    resolved_benchmark_return_source: str | None,
) -> AttributionResponse:
    meta = _build_attribution_meta(
        request=request,
        app_version=app_version,
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
    diagnostics = _build_attribution_diagnostics(
        execution_window=execution_window,
        results_by_period=results_by_period,
        resolved_benchmark_id=resolved_benchmark_id,
    )
    audit = _build_attribution_audit(
        request=request,
        results_by_period=results_by_period,
        resolved_benchmark_id=resolved_benchmark_id,
    )

    return AttributionResponse(
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
        diagnostics=diagnostics,
        audit=audit,
    )


def _complete_attribution_execution(
    *,
    request: AttributionRequest,
    response_model: AttributionResponse,
    lineage_data: dict[str, Any],
) -> None:
    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type="Attribution",
        request_model=request,
        response_model=response_model,
        execution_details={"period_count": len(response_model.results_by_period)},
        calculation_details=lineage_data,
    )


def _resolve_attribution_execution_window(request: AttributionRequest) -> _AttributionExecutionWindow:
    periods_to_resolve = [analysis.period for analysis in request.analyses]
    resolved_periods = resolve_periods(
        periods_to_resolve,
        request.report_end_date,
        request.report_start_date,
        explicit_start_date=request.report_start_date,
    )

    if not resolved_periods:
        raise APIBadRequestError("No valid periods could be resolved.")

    master_start_date, master_end_date, master_request = _attribution_master_request_for_resolved_periods(
        request,
        resolved_periods=resolved_periods,
    )

    return _AttributionExecutionWindow(
        periods_to_resolve=periods_to_resolve,
        resolved_periods=resolved_periods,
        master_start_date=master_start_date,
        master_end_date=master_end_date,
        master_request=master_request,
    )


def _attribution_master_request_for_resolved_periods(
    request: AttributionRequest,
    *,
    resolved_periods: Sequence[Any],
) -> tuple[Any, Any, AttributionRequest]:
    master_start_date = min(period.start_date for period in resolved_periods)
    master_end_date = max(period.end_date for period in resolved_periods)
    master_request = request.model_copy(deep=True)
    master_request.report_start_date = master_start_date
    master_request.report_end_date = master_end_date
    return master_start_date, master_end_date, master_request


def _record_attribution_execution_failure(
    *,
    calculation_id: UUID,
    message: str,
    execution_stage_started: bool,
    lineage_stage_started: bool,
) -> None:
    record_execution_failure(
        calculation_id=calculation_id,
        message=message,
        execution_stage_started=execution_stage_started,
        lineage_stage_started=lineage_stage_started,
    )


def _attribution_failure_api_error(exc: Exception) -> APIError:
    if isinstance(exc, APIError):
        return exc
    if is_mappable_application_error(exc):
        return APIError(status_code=int(getattr(exc, "status_code")), detail=getattr(exc, "detail"))
    if isinstance(exc, (InvalidEngineInputError, ValueError, NotImplementedError)):
        return APIBadRequestError(str(exc))
    if isinstance(exc, EngineCalculationError):
        return APIInternalServerError(f"Calculation Error: {exc.message}")
    return APIInternalServerError(safe_unexpected_failure_message("Attribution calculation"))


def _raise_recorded_attribution_failure(
    exc: Exception,
    *,
    calculation_id: UUID,
    execution_stage_started: bool,
    lineage_stage_started: bool,
) -> NoReturn:
    mapped_exc = _attribution_failure_api_error(exc)
    _record_attribution_execution_failure(
        calculation_id=calculation_id,
        message=str(mapped_exc.detail),
        execution_stage_started=execution_stage_started,
        lineage_stage_started=lineage_stage_started,
    )
    raise mapped_exc from exc


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

        response_model = _build_completed_attribution_response(
            request=request,
            input_mode=input_mode,
            results_by_period=results_by_period,
            execution_window=execution_window,
            app_version=active_settings.APP_VERSION,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            resolved_benchmark_id=resolved_benchmark_id,
            resolved_benchmark_return_source=resolved_benchmark_return_source,
        )
        enforce_core_analytics_fail_fast(operation="attribution", request=request, response=response_model)

        _complete_attribution_execution(
            request=request,
            response_model=response_model,
            lineage_data=lineage_data,
        )
        return response_model
    except Exception as exc:
        _raise_recorded_attribution_failure(
            exc,
            calculation_id=request.calculation_id,
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
