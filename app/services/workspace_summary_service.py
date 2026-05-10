from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

import pandas as pd
from fastapi import HTTPException, status

from adapters.api_adapter import create_engine_config, create_engine_dataframe
from app.core.config import Settings, get_settings
from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.mwr_analytics_requests import MWRInputMode
from app.models.mwr_requests import CashFlow
from app.models.performance_diagnostics import build_performance_diagnostics
from app.models.requests import DailyInputData, PerformanceRequest
from app.models.twr_requests import TWRInputMode
from app.models.workspace_summary_requests import WorkspaceBenchmarkRequest, WorkspaceSummaryRequest
from app.models.workspace_summary_responses import (
    WorkspaceActiveBlock,
    WorkspaceBasisPair,
    WorkspaceBenchmarkBlock,
    WorkspaceBreakdownItem,
    WorkspaceEconomicContext,
    WorkspaceEconomicReturnSummary,
    WorkspaceMoneyWeightedReturnSummary,
    WorkspacePerformanceBlock,
    WorkspacePeriodSummaryResult,
    WorkspaceReturnSummary,
    WorkspaceReturnValue,
    WorkspaceSummaryResponse,
)
from app.precision_policy import to_decimal
from app.services.execution_lifecycle_service import complete_execution_with_lineage
from app.services.execution_registry import execution_registry
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input
from app.services.stateful_performance_input_service import (
    build_stateful_portfolio_valuation_input,
    retrieve_stateful_portfolio_input,
)
from app.services.stateful_upstream_errors import stateful_control_plane_unavailable_detail
from app.services.stateless_benchmark_input_service import normalize_stateless_component_observations
from app.services.twr_service import (
    _build_relative_return_value,
    _build_return_value_from_decomposition,
    _calculate_benchmark_return_from_slice,
    _calculate_total_return_from_slice,
    _iter_frequency_windows,
)
from common.enums import Frequency
from core.envelope import Audit, Diagnostics, Meta
from core.repro import generate_canonical_hash
from core.workspace_periods import ResolvedWorkspacePeriod, resolve_workspace_periods
from engine.compute import run_calculations
from engine.mwr import calculate_money_weighted_return
from engine.schema import PortfolioColumns

DEFAULT_STATEFUL_CONSUMER_SYSTEM = "lotus-performance"


@dataclass(frozen=True)
class ResolvedWorkspacePortfolioInput:
    input_mode: MWRInputMode
    performance_start_date: date
    valuation_points: list[DailyInputData]
    observations: list[dict[str, object]]
    source_details: dict[str, int]


@dataclass(frozen=True)
class ResolvedWorkspaceBenchmarkInput:
    benchmark_request: BenchmarkPerformanceRequest
    input_mode: BenchmarkInputMode
    benchmark_id: str
    source_details: dict[str, int]


@dataclass(frozen=True)
class WorkspaceTWRArtifacts:
    daily_results_df: pd.DataFrame
    diagnostics: Diagnostics


def calculate_workspace_summary(
    request: WorkspaceSummaryRequest,
    *,
    settings: Settings | None = None,
) -> WorkspaceSummaryResponse:
    active_settings = settings or get_settings()
    input_fingerprint, calculation_hash = generate_canonical_hash(request, active_settings.APP_VERSION)
    execution_registry.start_stage(request.calculation_id, "execution")
    resolved_periods, portfolio_input, benchmark_input, net_artifacts, gross_artifacts = _resolve_workspace_inputs(
        request=request,
        settings=active_settings,
    )
    response = _build_workspace_summary_response(
        request=request,
        settings=active_settings,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        resolved_periods=resolved_periods,
        portfolio_input=portfolio_input,
        benchmark_input=benchmark_input,
        net_artifacts=net_artifacts,
        gross_artifacts=gross_artifacts,
    )

    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type="WORKSPACE_SUMMARY",
        request_model=request,
        response_model=response,
        execution_details={
            "periods_resolved": len(response.results_by_period),
            "portfolio_valuation_points": len(portfolio_input.valuation_points),
            "portfolio_chunk_count": portfolio_input.source_details.get("portfolio_chunk_count", 0),
            "benchmark_chunk_count": benchmark_input.source_details.get("chunk_count", 0) if benchmark_input else 0,
        },
        calculation_details={
            "workspace_summary_portfolio_daily_results_net.csv": net_artifacts.daily_results_df,
            "workspace_summary_portfolio_daily_results_gross.csv": gross_artifacts.daily_results_df,
        },
    )
    execution_registry.complete_stage(
        request.calculation_id,
        "execution",
        details={
            "report_end_date": str(request.report_end_date),
            "requested_periods": [item.period.value for item in request.periods],
            "input_mode": request.input_mode.value,
            "include_benchmark": request.include_benchmark,
        },
    )
    return response


def _resolve_workspace_inputs(
    *,
    request: WorkspaceSummaryRequest,
    settings: Settings,
) -> tuple[
    list[ResolvedWorkspacePeriod],
    ResolvedWorkspacePortfolioInput,
    ResolvedWorkspaceBenchmarkInput | None,
    WorkspaceTWRArtifacts,
    WorkspaceTWRArtifacts,
]:
    portfolio_input = _resolve_workspace_portfolio_input(request=request, settings=settings)
    resolved_periods = resolve_workspace_periods(
        [item.period for item in request.periods],
        as_of=request.report_end_date,
        performance_start_date=portfolio_input.performance_start_date,
        explicit_start_date=request.report_start_date,
    )
    if not resolved_periods:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No valid workspace periods could be resolved."
        )

    master_start_date = min(period.start_date for period in resolved_periods)
    portfolio_input = _trim_portfolio_input_to_master_window(
        portfolio_input=portfolio_input,
        master_start_date=master_start_date,
        report_end_date=request.report_end_date,
    )
    benchmark_input = _resolve_workspace_benchmark_input(
        request=request,
        settings=settings,
        master_start_date=master_start_date,
    )
    net_artifacts, gross_artifacts = _calculate_workspace_basis_artifacts(
        request=request,
        valuation_points=portfolio_input.valuation_points,
        performance_start_date=portfolio_input.performance_start_date,
    )
    return resolved_periods, portfolio_input, benchmark_input, net_artifacts, gross_artifacts


def _resolve_workspace_portfolio_input(
    *,
    request: WorkspaceSummaryRequest,
    settings: Settings,
) -> ResolvedWorkspacePortfolioInput:
    if request.input_mode == TWRInputMode.STATELESS:
        valuation_points = request.resolved_stateless_valuation_points()
        if request.performance_start_date is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="performance_start_date is required for stateless workspace summary requests.",
            )
        return ResolvedWorkspacePortfolioInput(
            input_mode=MWRInputMode.STATELESS,
            performance_start_date=request.performance_start_date,
            valuation_points=valuation_points,
            observations=[point.model_dump(mode="python") for point in valuation_points],
            source_details={"portfolio_chunk_count": 0, "portfolio_page_count": 0},
        )

    performance_start_date = request.performance_start_date or _resolve_stateful_portfolio_start_date(
        request=request,
        settings=settings,
    )
    resolved_periods = resolve_workspace_periods(
        [item.period for item in request.periods],
        as_of=request.report_end_date,
        performance_start_date=performance_start_date,
        explicit_start_date=request.report_start_date,
    )
    master_start_date = min(period.start_date for period in resolved_periods)
    source_input = _run_async(
        retrieve_stateful_portfolio_input(
            settings=settings,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.report_end_date,
            start_date=master_start_date,
            end_date=request.report_end_date,
            reporting_currency=request.report_ccy,
            consumer_system=DEFAULT_STATEFUL_CONSUMER_SYSTEM,
        )
    )
    normalized = build_stateful_portfolio_valuation_input(source_input)
    return ResolvedWorkspacePortfolioInput(
        input_mode=MWRInputMode.STATEFUL,
        performance_start_date=normalized.performance_start_date,
        valuation_points=[DailyInputData.model_validate(point) for point in normalized.valuation_points],
        observations=normalized.observations,
        source_details={
            "portfolio_chunk_count": source_input.retrieval_metadata.chunk_count,
            "portfolio_page_count": source_input.retrieval_metadata.page_count,
        },
    )


def _calculate_workspace_basis_artifacts(
    *,
    request: WorkspaceSummaryRequest,
    valuation_points: list[DailyInputData],
    performance_start_date: date,
) -> tuple[WorkspaceTWRArtifacts, WorkspaceTWRArtifacts]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        net_future = executor.submit(
            _calculate_workspace_twr_artifacts,
            request=request,
            valuation_points=valuation_points,
            performance_start_date=performance_start_date,
            metric_basis="NET",
        )
        gross_future = executor.submit(
            _calculate_workspace_twr_artifacts,
            request=request,
            valuation_points=valuation_points,
            performance_start_date=performance_start_date,
            metric_basis="GROSS",
        )
        return net_future.result(), gross_future.result()


def _trim_portfolio_input_to_master_window(
    *,
    portfolio_input: ResolvedWorkspacePortfolioInput,
    master_start_date: date,
    report_end_date: date,
) -> ResolvedWorkspacePortfolioInput:
    filtered_points = [
        point for point in portfolio_input.valuation_points if master_start_date <= point.perf_date <= report_end_date
    ]
    filtered_observations = []
    for observation in portfolio_input.observations:
        perf_date_raw = observation.get("perf_date")
        if not isinstance(perf_date_raw, str):
            continue
        perf_date = date.fromisoformat(perf_date_raw)
        if master_start_date <= perf_date <= report_end_date:
            filtered_observations.append(observation)
    return ResolvedWorkspacePortfolioInput(
        input_mode=portfolio_input.input_mode,
        performance_start_date=portfolio_input.performance_start_date,
        valuation_points=filtered_points,
        observations=filtered_observations,
        source_details=portfolio_input.source_details,
    )


def _resolve_workspace_benchmark_input(
    *,
    request: WorkspaceSummaryRequest,
    settings: Settings,
    master_start_date: date,
) -> ResolvedWorkspaceBenchmarkInput | None:
    if not request.include_benchmark:
        return None

    benchmark = request.benchmark or WorkspaceBenchmarkRequest.model_validate(
        {
            "input_mode": BenchmarkInputMode.STATEFUL.value,
            "stateful_input": {},
        }
    )
    if benchmark.input_mode == BenchmarkInputMode.STATELESS:
        if benchmark.stateless_input is None or benchmark.benchmark_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stateless workspace benchmark requests require benchmark_id and stateless_input.",
            )
        resolved_request = BenchmarkPerformanceRequest.model_validate(
            {
                "calculation_id": request.calculation_id,
                "benchmark_id": benchmark.benchmark_id,
                "benchmark_start_date": master_start_date,
                "report_end_date": request.report_end_date,
                "return_source": benchmark.return_source.value,
                "benchmark_currency": benchmark.stateless_input.benchmark_currency,
                "component_observations": (
                    normalize_stateless_component_observations(
                        benchmark_currency=benchmark.stateless_input.benchmark_currency,
                        stateless_input=benchmark.stateless_input,
                    )
                    if benchmark.return_source == BenchmarkReturnSource.CALCULATED
                    else []
                ),
                "benchmark_return_points": [
                    point.model_dump(mode="python") for point in benchmark.stateless_input.benchmark_return_points
                ],
                "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
                "report_start_date": master_start_date,
            }
        )
        return ResolvedWorkspaceBenchmarkInput(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATELESS,
            benchmark_id=benchmark.benchmark_id,
            source_details={},
        )

    stateful_input_service = build_stateful_input_service(settings=settings)
    benchmark_id = benchmark.benchmark_id
    source_details: dict[str, int] = {}
    if benchmark_id is None:
        assignment_status, assignment_payload = _run_async(
            stateful_input_service.get_benchmark_assignment(
                portfolio_id=request.portfolio_id,
                as_of_date=request.report_end_date,
                reporting_currency=request.report_ccy,
                calculation_id=request.calculation_id,
            )
        )
        if assignment_status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No benchmark assignment found for portfolio_id={request.portfolio_id}.",
            )
        if assignment_status >= status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"benchmark assignment source unavailable ({assignment_status}).",
            )
        benchmark_id_raw = assignment_payload.get("benchmark_id")
        if not isinstance(benchmark_id_raw, str) or not benchmark_id_raw:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="benchmark assignment payload missing benchmark_id.",
            )
        benchmark_id = benchmark_id_raw
        source_details["resolved_benchmark_assignment"] = 1

    normalized_input = _run_async(
        build_stateful_benchmark_input(
            stateful_input_service=stateful_input_service,
            calculation_id=request.calculation_id,
            benchmark_id=benchmark_id,
            as_of_date=request.report_end_date,
            start_date=master_start_date,
            end_date=request.report_end_date,
            return_source=benchmark.return_source,
        )
    )
    source_details.update(normalized_input.source_details)
    resolved_request = BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": request.calculation_id,
            "benchmark_id": benchmark_id,
            "benchmark_start_date": master_start_date,
            "report_end_date": request.report_end_date,
            "return_source": benchmark.return_source.value,
            "benchmark_currency": normalized_input.benchmark_currency,
            "component_observations": [
                item.model_dump(mode="python") for item in normalized_input.component_observations
            ],
            "benchmark_return_points": [
                item.model_dump(mode="python") for item in normalized_input.benchmark_return_points
            ],
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "report_start_date": master_start_date,
        }
    )
    return ResolvedWorkspaceBenchmarkInput(
        benchmark_request=resolved_request,
        input_mode=BenchmarkInputMode.STATEFUL,
        benchmark_id=benchmark_id,
        source_details=source_details,
    )


def _resolve_stateful_portfolio_start_date(*, request: WorkspaceSummaryRequest, settings: Settings) -> date:
    stateful_input_service = build_stateful_input_service(settings=settings)
    upstream_status, upstream_payload = _run_async(
        stateful_input_service.get_portfolio_reference(
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.report_end_date,
        )
    )
    if upstream_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=stateful_control_plane_unavailable_detail(
                source_label="stateful portfolio reference source",
                upstream_status=upstream_status,
            ),
        )
    portfolio_open_date = upstream_payload.get("portfolio_open_date")
    if not isinstance(portfolio_open_date, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stateful source missing portfolio_open_date.",
        )
    try:
        return date.fromisoformat(portfolio_open_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid portfolio_open_date from stateful source.",
        ) from exc


def _calculate_workspace_twr_artifacts(
    *,
    request: WorkspaceSummaryRequest,
    valuation_points: list[DailyInputData],
    performance_start_date: date,
    metric_basis: str,
) -> WorkspaceTWRArtifacts:
    performance_request = PerformanceRequest.model_validate(
        {
            "calculation_id": request.calculation_id,
            "portfolio_id": request.portfolio_id,
            "performance_start_date": performance_start_date,
            "metric_basis": metric_basis,
            "report_start_date": request.report_start_date,
            "report_end_date": request.report_end_date,
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "valuation_points": [point.model_dump(mode="python") for point in valuation_points],
            "currency": request.currency,
            "precision_mode": request.precision_mode,
            "rounding_precision": request.rounding_precision,
            "calendar": request.calendar.model_dump(mode="python"),
            "annualization": request.annualization.model_dump(mode="python"),
            "output": request.output.model_dump(mode="python"),
            "report_ccy": request.report_ccy,
            "currency_mode": request.currency_mode,
            "fx": request.fx.model_dump(mode="python") if request.fx is not None else None,
        }
    )
    master_start_date = min(point.perf_date for point in valuation_points)
    engine_config = create_engine_config(performance_request, master_start_date, request.report_end_date)
    engine_df = create_engine_dataframe([point.model_dump(mode="python") for point in valuation_points])
    daily_results_df, engine_diagnostics = run_calculations(engine_df, engine_config)
    daily_results_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
        daily_results_df[PortfolioColumns.PERF_DATE.value]
    ).dt.date
    return WorkspaceTWRArtifacts(
        daily_results_df=daily_results_df,
        diagnostics=Diagnostics(**build_performance_diagnostics(engine_diagnostics).model_dump(mode="python")),
    )


def _build_workspace_summary_response(
    *,
    request: WorkspaceSummaryRequest,
    settings: Settings,
    input_fingerprint: str,
    calculation_hash: str,
    resolved_periods: list[ResolvedWorkspacePeriod],
    portfolio_input: ResolvedWorkspacePortfolioInput,
    benchmark_input: ResolvedWorkspaceBenchmarkInput | None,
    net_artifacts: WorkspaceTWRArtifacts,
    gross_artifacts: WorkspaceTWRArtifacts,
) -> WorkspaceSummaryResponse:
    requested_frequencies = {item.period.value: item.frequencies for item in request.periods}
    valuation_df = pd.DataFrame([point.model_dump(mode="python") for point in portfolio_input.valuation_points])
    valuation_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
        valuation_df[PortfolioColumns.PERF_DATE.value]
    ).dt.date
    benchmark_daily_df = _build_workspace_benchmark_daily_df(benchmark_input)
    results_by_period: dict[str, WorkspacePeriodSummaryResult] = {}

    for resolved_period in resolved_periods:
        portfolio_slice = _slice_by_date(
            valuation_df,
            date_column=PortfolioColumns.PERF_DATE.value,
            start_date=resolved_period.start_date,
            end_date=resolved_period.end_date,
        )
        if portfolio_slice.empty:
            continue
        net_daily_slice = _slice_by_date(
            net_artifacts.daily_results_df,
            date_column=PortfolioColumns.PERF_DATE.value,
            start_date=resolved_period.start_date,
            end_date=resolved_period.end_date,
        )
        gross_daily_slice = _slice_by_date(
            gross_artifacts.daily_results_df,
            date_column=PortfolioColumns.PERF_DATE.value,
            start_date=resolved_period.start_date,
            end_date=resolved_period.end_date,
        )
        frequencies = requested_frequencies.get(resolved_period.name, [])
        net_summary = _build_workspace_performance_block(
            portfolio_slice=portfolio_slice,
            period_daily_slice=net_daily_slice,
            full_daily_df=net_artifacts.daily_results_df,
            frequencies=frequencies,
            annualization=request.annualization,
        )
        gross_summary = _build_workspace_performance_block(
            portfolio_slice=portfolio_slice,
            period_daily_slice=gross_daily_slice,
            full_daily_df=gross_artifacts.daily_results_df,
            frequencies=frequencies,
            annualization=request.annualization,
        )

        benchmark_block = None
        active_block = None
        if benchmark_input is not None and benchmark_daily_df is not None:
            benchmark_slice = _slice_by_date(
                benchmark_daily_df,
                date_column="date",
                start_date=resolved_period.start_date,
                end_date=resolved_period.end_date,
            )
            if not benchmark_slice.empty:
                benchmark_block = _build_workspace_benchmark_block(
                    benchmark_slice=benchmark_slice,
                    full_benchmark_df=benchmark_daily_df,
                    frequencies=frequencies,
                    annualization=request.annualization,
                    benchmark_input=benchmark_input,
                )
                active_block = WorkspaceActiveBlock(
                    net=WorkspaceReturnSummary(
                        period_return=_to_workspace_return_value(
                            _build_relative_return_value(
                                net_summary.summary.period_return,
                                benchmark_block.summary.period_return,
                            )
                        ),
                        cumulative_return=_to_workspace_return_value(
                            _build_relative_return_value(
                                net_summary.summary.cumulative_return,
                                benchmark_block.summary.cumulative_return,
                            )
                        ),
                        annualized_return=_to_workspace_return_value(
                            _build_relative_return_value(
                                net_summary.summary.annualized_return,
                                benchmark_block.summary.annualized_return,
                            )
                        ),
                    ),
                    gross=WorkspaceReturnSummary(
                        period_return=_to_workspace_return_value(
                            _build_relative_return_value(
                                gross_summary.summary.period_return,
                                benchmark_block.summary.period_return,
                            )
                        ),
                        cumulative_return=_to_workspace_return_value(
                            _build_relative_return_value(
                                gross_summary.summary.cumulative_return,
                                benchmark_block.summary.cumulative_return,
                            )
                        ),
                        annualized_return=_to_workspace_return_value(
                            _build_relative_return_value(
                                gross_summary.summary.annualized_return,
                                benchmark_block.summary.annualized_return,
                            )
                        ),
                    ),
                )

        results_by_period[resolved_period.name] = WorkspacePeriodSummaryResult(
            portfolio_twr=WorkspaceBasisPair(net=net_summary, gross=gross_summary),
            benchmark=benchmark_block,
            active=active_block,
            money_weighted_return=_build_workspace_mwr_summary(
                period_slice=portfolio_slice,
                period=resolved_period,
                input_mode=portfolio_input.input_mode,
                request=request,
            ),
        )

    diagnostics_notes = list(net_artifacts.diagnostics.notes)
    if benchmark_input is not None:
        diagnostics_notes.append(
            f"Benchmark summary uses {benchmark_input.input_mode.value} benchmark input with {benchmark_input.benchmark_request.return_source} returns."
        )

    diagnostics = Diagnostics(
        **net_artifacts.diagnostics.model_dump(mode="python", exclude={"notes"}),
        notes=diagnostics_notes,
    )
    return WorkspaceSummaryResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        input_mode=request.input_mode,
        results_by_period=results_by_period,
        meta=Meta(
            calculation_id=request.calculation_id,
            engine_version=settings.APP_VERSION,
            precision_mode=request.precision_mode,
            annualization=request.annualization,
            calendar=request.calendar,
            periods={
                "requested": [item.period.value for item in request.periods],
                "master_start": str(min(period.start_date for period in resolved_periods)),
                "master_end": str(request.report_end_date),
            },
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            report_ccy=request.report_ccy,
        ),
        diagnostics=diagnostics,
        audit=Audit(
            counts={
                "input_rows": len(portfolio_input.valuation_points),
                "periods_resolved": len(results_by_period),
                "portfolio_chunk_count": portfolio_input.source_details.get("portfolio_chunk_count", 0),
                "portfolio_page_count": portfolio_input.source_details.get("portfolio_page_count", 0),
                "benchmark_chunk_count": benchmark_input.source_details.get("chunk_count", 0) if benchmark_input else 0,
            }
        ),
    )


def _build_workspace_performance_block(
    *,
    portfolio_slice: pd.DataFrame,
    period_daily_slice: pd.DataFrame,
    full_daily_df: pd.DataFrame,
    frequencies: list[Frequency],
    annualization,
) -> WorkspacePerformanceBlock:
    summary_return = _to_workspace_return_value(
        _build_return_value_from_decomposition(_calculate_total_return_from_slice(period_daily_slice, full_daily_df))
    )
    return WorkspacePerformanceBlock(
        summary=WorkspaceEconomicReturnSummary(
            economics=_build_economic_context(portfolio_slice),
            period_return=summary_return,
            cumulative_return=summary_return,
            annualized_return=_annualize_return_value(
                summary_return,
                start_date=_date_from_boundary(portfolio_slice[PortfolioColumns.PERF_DATE.value].min()),
                end_date=_date_from_boundary(portfolio_slice[PortfolioColumns.PERF_DATE.value].max()),
                annualization=annualization,
                business_day_count=len(period_daily_slice),
            ),
        ),
        breakdowns=_build_workspace_performance_breakdowns(
            portfolio_slice=portfolio_slice,
            period_daily_slice=period_daily_slice,
            full_daily_df=full_daily_df,
            frequencies=frequencies,
            annualization=annualization,
        ),
    )


def _build_workspace_performance_breakdowns(
    *,
    portfolio_slice: pd.DataFrame,
    period_daily_slice: pd.DataFrame,
    full_daily_df: pd.DataFrame,
    frequencies: list[Frequency],
    annualization,
) -> dict[Frequency, list[WorkspaceBreakdownItem]]:
    breakdowns: dict[Frequency, list[WorkspaceBreakdownItem]] = {}
    for frequency in frequencies:
        items: list[WorkspaceBreakdownItem] = []
        for label, start_date, end_date, valuation_window in _iter_frequency_windows(
            portfolio_slice,
            date_column=PortfolioColumns.PERF_DATE.value,
            frequency=frequency,
        ):
            window_start_date = _date_from_boundary(start_date)
            window_end_date = _date_from_boundary(end_date)
            period_return = _to_workspace_return_value(
                _build_return_value_from_decomposition(
                    _calculate_total_return_from_slice(
                        _slice_by_date(
                            period_daily_slice,
                            date_column=PortfolioColumns.PERF_DATE.value,
                            start_date=window_start_date,
                            end_date=window_end_date,
                        ),
                        full_daily_df,
                    )
                )
            )
            cumulative_daily = full_daily_df[full_daily_df[PortfolioColumns.PERF_DATE.value] <= window_end_date].copy()
            cumulative_return = _to_workspace_return_value(
                _build_return_value_from_decomposition(
                    _calculate_total_return_from_slice(cumulative_daily, full_daily_df)
                )
            )
            items.append(
                WorkspaceBreakdownItem(
                    period=label,
                    period_start=window_start_date,
                    period_end=window_end_date,
                    economics=_build_economic_context(valuation_window),
                    period_return=period_return,
                    cumulative_return=cumulative_return,
                    annualized_return=_annualize_return_value(
                        cumulative_return,
                        start_date=_date_from_boundary(portfolio_slice[PortfolioColumns.PERF_DATE.value].min()),
                        end_date=window_end_date,
                        annualization=annualization,
                        business_day_count=len(cumulative_daily),
                    ),
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _build_workspace_benchmark_block(
    *,
    benchmark_slice: pd.DataFrame,
    full_benchmark_df: pd.DataFrame,
    frequencies: list[Frequency],
    annualization,
    benchmark_input: ResolvedWorkspaceBenchmarkInput,
) -> WorkspaceBenchmarkBlock:
    summary_return = _to_workspace_return_value(_calculate_benchmark_return_from_slice(benchmark_slice))
    return WorkspaceBenchmarkBlock(
        summary=WorkspaceReturnSummary(
            period_return=summary_return,
            cumulative_return=summary_return,
            annualized_return=_annualize_return_value(
                summary_return,
                start_date=_date_from_boundary(benchmark_slice["date"].min()),
                end_date=_date_from_boundary(benchmark_slice["date"].max()),
                annualization=annualization,
                business_day_count=len(benchmark_slice),
            ),
        ),
        breakdowns=_build_workspace_benchmark_breakdowns(
            benchmark_slice=benchmark_slice,
            full_benchmark_df=full_benchmark_df,
            frequencies=frequencies,
            annualization=annualization,
        ),
        benchmark_id=benchmark_input.benchmark_id,
        benchmark_currency=benchmark_input.benchmark_request.benchmark_currency,
        input_mode=benchmark_input.input_mode,
        return_source=BenchmarkReturnSource(benchmark_input.benchmark_request.return_source),
    )


def _build_workspace_benchmark_breakdowns(
    *,
    benchmark_slice: pd.DataFrame,
    full_benchmark_df: pd.DataFrame,
    frequencies: list[Frequency],
    annualization,
) -> dict[Frequency, list[WorkspaceBreakdownItem]]:
    breakdowns: dict[Frequency, list[WorkspaceBreakdownItem]] = {}
    for frequency in frequencies:
        items: list[WorkspaceBreakdownItem] = []
        for label, start_date, end_date, benchmark_window in _iter_frequency_windows(
            benchmark_slice,
            date_column="date",
            frequency=frequency,
        ):
            window_start_date = _date_from_boundary(start_date)
            window_end_date = _date_from_boundary(end_date)
            period_return = _to_workspace_return_value(_calculate_benchmark_return_from_slice(benchmark_window))
            cumulative_df = full_benchmark_df[full_benchmark_df["date"] <= window_end_date].copy()
            cumulative_return = _to_workspace_return_value(_calculate_benchmark_return_from_slice(cumulative_df))
            items.append(
                WorkspaceBreakdownItem(
                    period=label,
                    period_start=window_start_date,
                    period_end=window_end_date,
                    period_return=period_return,
                    cumulative_return=cumulative_return,
                    annualized_return=_annualize_return_value(
                        cumulative_return,
                        start_date=_date_from_boundary(benchmark_slice["date"].min()),
                        end_date=window_end_date,
                        annualization=annualization,
                        business_day_count=len(cumulative_df),
                    ),
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _build_workspace_mwr_summary(
    *,
    period_slice: pd.DataFrame,
    period: ResolvedWorkspacePeriod,
    input_mode: MWRInputMode,
    request: WorkspaceSummaryRequest,
) -> WorkspaceMoneyWeightedReturnSummary:
    mwr_result = calculate_money_weighted_return(
        begin_mv=period_slice.iloc[0]["begin_mv"],
        end_mv=period_slice.iloc[-1]["end_mv"],
        cash_flows=_build_mwr_cash_flows(period_slice),
        calculation_method=request.mwr_method,
        annualization=request.annualization,
        as_of=period.end_date,
        start_date=period.start_date,
        solver=request.solver,
    )
    return WorkspaceMoneyWeightedReturnSummary(
        input_mode=input_mode,
        method=mwr_result.method,
        period_return=mwr_result.mwr,
        cumulative_return=mwr_result.mwr,
        annualized_return=mwr_result.mwr_annualized if mwr_result.mwr_annualized is not None else mwr_result.mwr,
        economics=_build_economic_context(period_slice),
        start_date=period.start_date,
        end_date=period.end_date,
        notes=mwr_result.notes,
    )


def _build_mwr_cash_flows(period_slice: pd.DataFrame) -> list[CashFlow]:
    cash_flows: list[CashFlow] = []
    carry_forward_adjustments = dict(_iter_carry_forward_adjustments(period_slice))
    for _, row in period_slice.iterrows():
        perf_date = row[PortfolioColumns.PERF_DATE.value]
        bod_cf = _decimal_or_zero(row.get("bod_cf"))
        eod_cf = _decimal_or_zero(row.get("eod_cf"))
        carry_forward_adjustment = carry_forward_adjustments.get(perf_date, Decimal("0"))
        if carry_forward_adjustment != Decimal("0"):
            bod_cf += carry_forward_adjustment
        if bod_cf != Decimal("0"):
            cash_flows.append(CashFlow(amount=bod_cf, date=perf_date))
        if eod_cf != Decimal("0"):
            cash_flows.append(CashFlow(amount=eod_cf, date=perf_date))
    return cash_flows


def _build_economic_context(period_slice: pd.DataFrame) -> WorkspaceEconomicContext:
    first_row = period_slice.iloc[0]
    last_row = period_slice.iloc[-1]
    beginning_cash_flow = _sum_decimal_column(period_slice, "bod_cf")
    ending_cash_flow = _sum_decimal_column(period_slice, "eod_cf")
    fees = _sum_decimal_column(period_slice, "mgmt_fees")
    net_cash_flow = beginning_cash_flow + ending_cash_flow
    end_market_value = _decimal_or_zero(last_row["end_mv"])
    return WorkspaceEconomicContext(
        begin_market_value=_decimal_or_zero(first_row["begin_mv"]),
        end_market_value=end_market_value,
        beginning_cash_flow=beginning_cash_flow,
        ending_cash_flow=ending_cash_flow,
        fees=fees,
        net_cash_flow=net_cash_flow,
        flow_adjusted_end_market_value=end_market_value - net_cash_flow,
    )


def _iter_carry_forward_adjustments(period_slice: pd.DataFrame) -> list[tuple[date, Decimal]]:
    adjustments: list[tuple[date, Decimal]] = []
    previous_ending_market_value: Decimal | None = None
    for _, row in period_slice.iterrows():
        perf_date = row[PortfolioColumns.PERF_DATE.value]
        begin_mv = _decimal_or_zero(row.get("begin_mv"))
        if previous_ending_market_value is not None:
            adjustment = begin_mv - previous_ending_market_value
            if adjustment != Decimal("0"):
                adjustments.append((perf_date, adjustment))
        previous_ending_market_value = _decimal_or_zero(row.get("end_mv"))
    return adjustments


def _annualize_return_value(
    value: WorkspaceReturnValue,
    *,
    start_date: date,
    end_date: date,
    annualization,
    business_day_count: int,
) -> WorkspaceReturnValue:
    return WorkspaceReturnValue(
        base=_annualize_percentage(
            to_decimal(value.base),
            start_date=start_date,
            end_date=end_date,
            annualization=annualization,
            business_day_count=business_day_count,
        ),
        local=(
            None
            if value.local is None
            else _annualize_percentage(
                to_decimal(value.local),
                start_date=start_date,
                end_date=end_date,
                annualization=annualization,
                business_day_count=business_day_count,
            )
        ),
        fx=(
            None
            if value.fx is None
            else _annualize_percentage(
                to_decimal(value.fx),
                start_date=start_date,
                end_date=end_date,
                annualization=annualization,
                business_day_count=business_day_count,
            )
        ),
    )


def _annualize_percentage(
    value_pct: Decimal,
    *,
    start_date: date,
    end_date: date,
    annualization,
    business_day_count: int,
) -> Decimal:
    elapsed_days = max((end_date - start_date).days + 1, 1)
    if elapsed_days <= 365:
        return value_pct
    periods_per_year = annualization.periods_per_year or (252 if annualization.basis == "BUS/252" else 365)
    elapsed_measure = business_day_count if annualization.basis == "BUS/252" else elapsed_days
    if elapsed_measure <= 0:
        return value_pct
    growth_factor = Decimal("1") + (value_pct / Decimal("100"))
    exponent = Decimal(periods_per_year) / Decimal(elapsed_measure)
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, 28)
        annualized_growth = (growth_factor.ln() * exponent).exp()
    return (annualized_growth - Decimal("1")) * Decimal("100")


def _build_workspace_benchmark_daily_df(
    benchmark_input: ResolvedWorkspaceBenchmarkInput | None,
) -> pd.DataFrame | None:
    if benchmark_input is None:
        return None
    benchmark_request = benchmark_input.benchmark_request
    if benchmark_request.return_source == "calculated":
        from app.services.benchmark_calculation_service import calculate_benchmark_artifacts

        daily_df = calculate_benchmark_artifacts(benchmark_request).daily_returns_df.copy()
    else:
        daily_df = pd.DataFrame(
            [
                {"date": point.perf_date, "benchmark_return": point.benchmark_return}
                for point in benchmark_request.benchmark_return_points
            ]
        )
    if not daily_df.empty:
        daily_df["date"] = pd.to_datetime(daily_df["date"]).dt.date
    return daily_df


def _slice_by_date(
    df: pd.DataFrame,
    *,
    date_column: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    return df[(df[date_column] >= start_date) & (df[date_column] <= end_date)].copy()


def _run_async(coroutine):
    return asyncio.run(coroutine)


def _date_from_boundary(value: object) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"Unsupported date boundary value: {value!r}")


def _to_workspace_return_value(value) -> WorkspaceReturnValue:
    return WorkspaceReturnValue(
        base=to_decimal(value.base),
        local=None if value.local is None else to_decimal(value.local),
        fx=None if value.fx is None else to_decimal(value.fx),
    )


def _decimal_or_zero(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        if value != value:
            return Decimal("0")
    except TypeError:
        pass
    return to_decimal(value)


def _sum_decimal_column(frame: pd.DataFrame, column_name: str) -> Decimal:
    if column_name not in frame:
        return Decimal("0")
    total = Decimal("0")
    for value in frame[column_name]:
        total += _decimal_or_zero(value)
    return total
