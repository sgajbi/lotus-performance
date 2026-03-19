from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_responses import (
    BenchmarkPerformanceResponse,
)
from app.services.benchmark_calculation_service import calculate_benchmark_artifacts
from app.services.benchmark_mode_service import resolve_benchmark_request
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from core.envelope import Audit, Diagnostics, Meta
from core.repro import generate_canonical_hash

router = APIRouter(tags=["Performance"])


@router.post(
    "/benchmark",
    response_model=BenchmarkPerformanceResponse,
    summary="Calculate benchmark performance",
)
async def calculate_benchmark_endpoint(request: BenchmarkAnalyticsRequest):
    settings = get_settings()
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)
    register_window = {
        "benchmark_start_date": str(request.benchmark_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "return_source": request.return_source.value,
    }
    from app.services.submission_fencing_service import register_sync_execution_or_raise

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="BENCHMARK",
        portfolio_id=request.benchmark_id,
        requested_window=register_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    lineage_stage_started = False

    try:
        resolved_request = await resolve_benchmark_request(request, settings=settings)
        benchmark_request = resolved_request.benchmark_request
        if _should_persist_resolved_benchmark_request(request):
            input_fingerprint, calculation_hash = generate_canonical_hash(
                benchmark_request,
                settings.APP_VERSION,
            )
            execution_registry.update_execution_identity(
                request.calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )

        execution_registry.start_stage(request.calculation_id, "execution")
        execution_stage_started = True
        benchmark_artifacts = calculate_benchmark_artifacts(benchmark_request)

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
            message=f"An unexpected server error occurred: {exc}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred: {exc}",
        )

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=settings.APP_VERSION,
        precision_mode=benchmark_request.precision_mode,
        calendar=benchmark_request.calendar,
        annualization=benchmark_request.annualization,
        periods={
            "requested": [analysis.period.value for analysis in benchmark_request.analyses],
            "master_start": str(benchmark_request.benchmark_start_date),
            "master_end": str(benchmark_request.report_end_date),
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        report_ccy=benchmark_request.benchmark_currency,
    )
    diagnostics = Diagnostics(
        nip_days=0,
        reset_days=0,
        effective_period_start=benchmark_artifacts.effective_period_start,
        notes=benchmark_artifacts.notes,
    )
    audit = Audit(
        counts={
            "component_observations": len(benchmark_request.component_observations),
            "benchmark_return_points": len(benchmark_request.benchmark_return_points),
            "daily_returns": len(benchmark_artifacts.daily_returns_df),
        },
        residual_applied_bp=benchmark_artifacts.max_weight_sum_deviation * 10000,
    )

    response_model = BenchmarkPerformanceResponse(
        calculation_id=request.calculation_id,
        benchmark_id=request.benchmark_id,
        benchmark_currency=benchmark_request.benchmark_currency,
        input_mode=request.input_mode,
        return_source=request.return_source,
        results_by_period=benchmark_artifacts.results_by_period,
        meta=meta,
        diagnostics=diagnostics,
        audit=audit,
    )

    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type="BENCHMARK",
        request_model=benchmark_request if _should_persist_resolved_benchmark_request(request) else request,
        response_model=response_model,
        execution_details={
            "daily_returns": len(benchmark_artifacts.daily_returns_df),
            "component_contributions": len(benchmark_artifacts.component_contributions_df),
        },
        calculation_details={
            "benchmark_daily_returns.csv": benchmark_artifacts.daily_returns_df,
            "benchmark_component_contributions.csv": benchmark_artifacts.component_contributions_df,
        },
    )

    return response_model


def _should_persist_resolved_benchmark_request(request: BenchmarkAnalyticsRequest) -> bool:
    if request.input_mode == BenchmarkInputMode.STATEFUL:
        return True
    stateless_input = request.stateless_input
    if stateless_input is None:
        return False
    return bool(stateless_input.component_price_points)
