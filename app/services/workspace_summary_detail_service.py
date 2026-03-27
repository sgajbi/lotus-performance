from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.core.config import Settings
from app.models.attribution_analytics_requests import (
    AttributionAnalyticsRequest,
    AttributionStatefulInput,
)
from app.models.attribution_requests import AttributionRequest
from app.models.contribution_analytics_requests import (
    ContributionAnalyticsRequest,
    ContributionStatefulInput,
)
from app.models.contribution_requests import ContributionRequest
from app.models.workspace_summary_requests import (
    WorkspaceAttributionSummaryRequest,
    WorkspaceContributionSummaryRequest,
    WorkspaceSegmentationRequest,
    WorkspaceSummaryRequest,
)
from app.models.workspace_summary_responses import (
    WorkspaceAttributionSummaryBlock,
    WorkspaceContributionSummaryBlock,
)
from app.services.contribution_service import (
    _as_numeric,
    _calculate_daily_instrument_contributions,
    _calculate_reset_aware_period_portfolio_return,
    _prepare_hierarchical_data,
    build_hierarchical_contribution_result,
)
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.stateful_attribution_input_service import (
    build_stateful_attribution_input,
    retrieve_stateful_attribution_source_input,
)
from app.services.stateful_contribution_input_service import (
    build_stateful_contribution_input,
    retrieve_stateful_contribution_source_input,
)
from common.enums import AttributionMode, Frequency, PeriodType
from engine.attribution import aggregate_attribution_results, run_attribution_calculations
from engine.schema import PortfolioColumns


@dataclass(frozen=True)
class WorkspaceContributionArtifacts:
    request: ContributionRequest
    daily_contributions_df: pd.DataFrame
    portfolio_results_df: pd.DataFrame
    source_details: dict[str, int]


@dataclass(frozen=True)
class WorkspaceAttributionArtifacts:
    request: AttributionRequest
    effects_df: pd.DataFrame
    resolved_benchmark_id: str | None
    resolved_benchmark_return_source: str | None
    source_details: dict[str, int]


def build_workspace_contribution_artifacts(
    *,
    workspace_request: WorkspaceSummaryRequest,
    settings: Settings,
    master_start_date: date,
) -> WorkspaceContributionArtifacts | None:
    if workspace_request.contribution is None or workspace_request.segmentation is None:
        return None

    contribution_options = workspace_request.contribution
    segmentation = workspace_request.segmentation
    analytics_request = _build_workspace_contribution_analytics_request(
        workspace_request=workspace_request,
        contribution_options=contribution_options,
        segmentation=segmentation,
        master_start_date=master_start_date,
    )
    stateful_input_service = build_stateful_input_service(settings=settings)
    source_input = _run_async(
        retrieve_stateful_contribution_source_input(
            settings=settings,
            stateful_input_service=stateful_input_service,
            calculation_id=workspace_request.calculation_id,
            portfolio_id=workspace_request.portfolio_id,
            as_of_date=workspace_request.report_end_date,
            report_start_date=master_start_date,
            report_end_date=workspace_request.report_end_date,
            reporting_currency=workspace_request.report_ccy,
            consumer_system="lotus-performance",
            dimensions=list(segmentation.group_by),
            include_cash_flows=True,
            filters={},
        )
    )
    normalized_input = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis=contribution_options.metric_basis,
        currency_mode=workspace_request.currency_mode,
        fx=workspace_request.fx,
        reporting_currency=workspace_request.report_ccy,
    )
    contribution_request = analytics_request.to_stateless_contribution_request(
        portfolio_data=normalized_input.portfolio_data,
        positions_data=normalized_input.positions_data,
    )
    instruments_df, portfolio_results_df = _prepare_hierarchical_data(contribution_request)
    daily_contributions_df = _calculate_daily_instrument_contributions(
        instruments_df,
        portfolio_results_df,
        contribution_request.weighting_scheme,
        contribution_request.smoothing,
    )
    daily_contributions_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
        daily_contributions_df[PortfolioColumns.PERF_DATE.value]
    ).dt.date
    return WorkspaceContributionArtifacts(
        request=contribution_request,
        daily_contributions_df=daily_contributions_df,
        portfolio_results_df=portfolio_results_df,
        source_details={
            "position_count": len(normalized_input.positions_data),
            "position_chunk_count": source_input.position_retrieval_metadata.chunk_count,
            "position_page_count": source_input.position_retrieval_metadata.page_count,
        },
    )


def build_workspace_contribution_block(
    *,
    artifacts: WorkspaceContributionArtifacts | None,
    contribution_options: WorkspaceContributionSummaryRequest | None,
    segmentation: WorkspaceSegmentationRequest | None,
    period_start_date: date,
    period_end_date: date,
) -> WorkspaceContributionSummaryBlock | None:
    if artifacts is None or contribution_options is None or segmentation is None:
        return None

    period_slice_df = artifacts.daily_contributions_df[
        (artifacts.daily_contributions_df[PortfolioColumns.PERF_DATE.value] >= period_start_date)
        & (artifacts.daily_contributions_df[PortfolioColumns.PERF_DATE.value] <= period_end_date)
    ].copy()
    if period_slice_df.empty:
        return None

    total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
        artifacts.request,
        period_start_date,
        period_end_date,
        PeriodType.EXPLICIT,
    )
    hierarchical_result = build_hierarchical_contribution_result(
        period_slice_df,
        artifacts.request,
        total_portfolio_return=total_portfolio_return,
    )
    grouped_totals = (
        period_slice_df.groupby("position_id")
        .agg(
            total_contribution=("smoothed_contribution", "sum"),
            local_contribution=("smoothed_local_contribution", "sum"),
            average_weight=("daily_weight", "mean"),
        )
        .reset_index()
    )
    grouped_totals["fx_contribution"] = grouped_totals["total_contribution"] - grouped_totals["local_contribution"]

    position_contributions = sorted(
        [
            {
                "position_id": row["position_id"],
                "total_contribution": _as_numeric(row["total_contribution"]) * 100,
                "average_weight": _as_numeric(row["average_weight"]) * 100,
                "total_return": 0.0,
                "local_contribution": _as_numeric(row["local_contribution"]) * 100,
                "fx_contribution": _as_numeric(row["fx_contribution"]) * 100,
            }
            for _, row in grouped_totals.iterrows()
        ],
        key=lambda row: abs(row["total_contribution"]),
        reverse=True,
    )[: contribution_options.top_positions]

    return WorkspaceContributionSummaryBlock(
        metric_basis=contribution_options.metric_basis,
        segmentation=list(segmentation.group_by),
        summary=hierarchical_result.get("summary"),
        levels=hierarchical_result.get("levels"),
        position_contributions=position_contributions,
    )


def build_workspace_attribution_artifacts(
    *,
    workspace_request: WorkspaceSummaryRequest,
    settings: Settings,
    master_start_date: date,
) -> WorkspaceAttributionArtifacts | None:
    if workspace_request.attribution is None or workspace_request.segmentation is None:
        return None

    analytics_request = _build_workspace_attribution_analytics_request(
        workspace_request=workspace_request,
        attribution_options=workspace_request.attribution,
        segmentation=workspace_request.segmentation,
        master_start_date=master_start_date,
    )
    benchmark_id_override = None
    if workspace_request.benchmark is not None and workspace_request.benchmark.input_mode.value == "stateful":
        benchmark_id_override = workspace_request.benchmark.benchmark_id
    stateful_input_service = build_stateful_input_service(settings=settings)
    source_input = _run_async(
        retrieve_stateful_attribution_source_input(
            settings=settings,
            stateful_input_service=stateful_input_service,
            calculation_id=workspace_request.calculation_id,
            portfolio_id=workspace_request.portfolio_id,
            as_of_date=workspace_request.report_end_date,
            report_start_date=master_start_date,
            report_end_date=workspace_request.report_end_date,
            reporting_currency=workspace_request.report_ccy,
            consumer_system="lotus-performance",
            group_by=list(workspace_request.segmentation.group_by),
            dimensions=[],
            include_cash_flows=True,
            filters={},
            benchmark_id_override=benchmark_id_override,
        )
    )
    normalized_input = build_stateful_attribution_input(
        source_input=source_input,
        mode=AttributionMode.BY_INSTRUMENT.value,
        group_by=list(workspace_request.segmentation.group_by),
        metric_basis=workspace_request.attribution.metric_basis,
        currency_mode=workspace_request.currency_mode,
        fx=workspace_request.fx,
        reporting_currency=workspace_request.report_ccy,
    )
    attribution_request = analytics_request.to_stateless_attribution_request(
        portfolio_data=normalized_input.portfolio_data,
        instruments_data=normalized_input.instruments_data,
        benchmark_groups_data=normalized_input.benchmark_groups_data,
    )
    effects_df, _lineage = run_attribution_calculations(attribution_request)
    return WorkspaceAttributionArtifacts(
        request=attribution_request,
        effects_df=effects_df,
        resolved_benchmark_id=source_input.benchmark_id,
        resolved_benchmark_return_source="calculated",
        source_details={
            "instrument_count": len(normalized_input.instruments_data),
            "position_chunk_count": source_input.position_retrieval_metadata.chunk_count,
            "position_page_count": source_input.position_retrieval_metadata.page_count,
            "benchmark_chunk_count": source_input.benchmark_retrieval_metadata.chunk_count,
            "benchmark_page_count": source_input.benchmark_retrieval_metadata.page_count,
            "index_page_count": source_input.index_retrieval_metadata.page_count,
        },
    )


def build_workspace_attribution_block(
    *,
    artifacts: WorkspaceAttributionArtifacts | None,
    attribution_options: WorkspaceAttributionSummaryRequest | None,
    segmentation: WorkspaceSegmentationRequest | None,
    period_start_date: date,
    period_end_date: date,
) -> WorkspaceAttributionSummaryBlock | None:
    if artifacts is None or attribution_options is None or segmentation is None:
        return None
    if artifacts.effects_df.empty:
        return None

    period_slice_df = artifacts.effects_df[
        (artifacts.effects_df.index.get_level_values("date") >= pd.to_datetime(period_start_date))
        & (artifacts.effects_df.index.get_level_values("date") <= pd.to_datetime(period_end_date))
    ].copy()
    if period_slice_df.empty:
        return None

    period_result, _aggregation_lineage = aggregate_attribution_results(period_slice_df, artifacts.request)
    return WorkspaceAttributionSummaryBlock(
        metric_basis=attribution_options.metric_basis,
        segmentation=list(segmentation.group_by),
        model=artifacts.request.model,
        linking=artifacts.request.linking,
        benchmark_context=(
            {
                "benchmark_id": artifacts.resolved_benchmark_id,
                "return_source": artifacts.resolved_benchmark_return_source,
            }
            if artifacts.resolved_benchmark_id is not None and artifacts.resolved_benchmark_return_source is not None
            else None
        ),
        result=period_result,
    )


def _build_workspace_contribution_analytics_request(
    *,
    workspace_request: WorkspaceSummaryRequest,
    contribution_options: WorkspaceContributionSummaryRequest,
    segmentation: WorkspaceSegmentationRequest,
    master_start_date: date,
) -> ContributionAnalyticsRequest:
    return ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(workspace_request.calculation_id),
            "portfolio_id": workspace_request.portfolio_id,
            "report_start_date": str(master_start_date),
            "report_end_date": str(workspace_request.report_end_date),
            "analyses": [{"period": "EXPLICIT", "frequencies": [Frequency.DAILY.value]}],
            "hierarchy": list(segmentation.group_by),
            "emit": {
                "timeseries": False,
                "by_position_timeseries": False,
                "by_level": True,
                "top_n_per_level": 20,
                "include_other": True,
                "include_unclassified": True,
            },
            "input_mode": "stateful",
            "stateful_input": ContributionStatefulInput(
                metric_basis=contribution_options.metric_basis,
                dimensions=[],
                include_cash_flows=True,
            ).model_dump(mode="python"),
            "currency": workspace_request.currency,
            "precision_mode": workspace_request.precision_mode,
            "rounding_precision": workspace_request.rounding_precision,
            "calendar": workspace_request.calendar.model_dump(mode="python"),
            "annualization": workspace_request.annualization.model_dump(mode="python"),
            "output": workspace_request.output.model_dump(mode="python"),
            "report_ccy": workspace_request.report_ccy,
            "currency_mode": workspace_request.currency_mode,
            "fx": workspace_request.fx.model_dump(mode="python") if workspace_request.fx is not None else None,
        }
    )


def _build_workspace_attribution_analytics_request(
    *,
    workspace_request: WorkspaceSummaryRequest,
    attribution_options: WorkspaceAttributionSummaryRequest,
    segmentation: WorkspaceSegmentationRequest,
    master_start_date: date,
) -> AttributionAnalyticsRequest:
    benchmark_id_override = None
    if workspace_request.benchmark is not None and workspace_request.benchmark.input_mode.value == "stateful":
        benchmark_id_override = workspace_request.benchmark.benchmark_id

    return AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(workspace_request.calculation_id),
            "portfolio_id": workspace_request.portfolio_id,
            "report_start_date": str(master_start_date),
            "report_end_date": str(workspace_request.report_end_date),
            "analyses": [{"period": "EXPLICIT", "frequencies": [Frequency.DAILY.value]}],
            "mode": AttributionMode.BY_INSTRUMENT.value,
            "frequency": Frequency.DAILY.value,
            "group_by": list(segmentation.group_by),
            "input_mode": "stateful",
            "stateful_input": AttributionStatefulInput(
                metric_basis=attribution_options.metric_basis,
                benchmark_id=benchmark_id_override,
                dimensions=[],
                include_cash_flows=True,
            ).model_dump(mode="python"),
            "currency": workspace_request.currency,
            "precision_mode": workspace_request.precision_mode,
            "rounding_precision": workspace_request.rounding_precision,
            "calendar": workspace_request.calendar.model_dump(mode="python"),
            "annualization": workspace_request.annualization.model_dump(mode="python"),
            "output": workspace_request.output.model_dump(mode="python"),
            "report_ccy": workspace_request.report_ccy,
            "currency_mode": workspace_request.currency_mode,
            "fx": workspace_request.fx.model_dump(mode="python") if workspace_request.fx is not None else None,
        }
    )


def _run_async(coroutine):
    return asyncio.run(coroutine)
