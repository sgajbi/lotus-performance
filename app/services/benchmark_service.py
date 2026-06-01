from __future__ import annotations

from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.benchmark_responses import BenchmarkPerformanceResponse
from app.services.benchmark_calculation_service import calculate_benchmark_artifacts
from app.services.execution_lifecycle_service import complete_execution_with_lineage
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from core.envelope import Audit, Diagnostics, Meta


def calculate_benchmark_response(
    benchmark_request: BenchmarkPerformanceRequest,
    *,
    input_fingerprint: str,
    calculation_hash: str,
    input_mode: BenchmarkInputMode,
    engine_version: str,
    request_artifact_model,
) -> BenchmarkPerformanceResponse:
    execution_registry.start_stage(benchmark_request.calculation_id, EXECUTION_STAGE_EXECUTION)
    try:
        benchmark_artifacts = calculate_benchmark_artifacts(
            benchmark_request,
            input_mode=input_mode.value,
        )

        response_model = BenchmarkPerformanceResponse(
            calculation_id=benchmark_request.calculation_id,
            benchmark_id=benchmark_request.benchmark_id,
            benchmark_currency=benchmark_request.benchmark_currency,
            input_mode=input_mode,
            return_source=BenchmarkReturnSource(benchmark_request.return_source),
            results_by_period=benchmark_artifacts.results_by_period,
            meta=Meta(
                calculation_id=benchmark_request.calculation_id,
                engine_version=engine_version,
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
            ),
            diagnostics=Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=benchmark_artifacts.effective_period_start,
                notes=benchmark_artifacts.notes,
            ),
            audit=Audit(
                counts={
                    "component_observations": len(benchmark_request.component_observations),
                    "benchmark_return_points": len(benchmark_request.benchmark_return_points),
                    "daily_returns": len(benchmark_artifacts.daily_returns_df),
                },
                residual_applied_bp=benchmark_artifacts.max_weight_sum_deviation * 10000,
            ),
        )
    except Exception as exc:
        execution_registry.fail_stage(benchmark_request.calculation_id, EXECUTION_STAGE_EXECUTION, str(exc))
        raise

    complete_execution_with_lineage(
        calculation_id=benchmark_request.calculation_id,
        calculation_type="BENCHMARK",
        request_model=request_artifact_model,
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
