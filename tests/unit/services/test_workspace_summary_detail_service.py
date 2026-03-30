from datetime import date
from uuid import uuid4

import pandas as pd
import pytest

from app.models.attribution_requests import AttributionRequest
from app.models.contribution_requests import ContributionRequest
from app.models.workspace_summary_requests import (
    WorkspaceAttributionSummaryRequest,
    WorkspaceContributionSummaryRequest,
    WorkspaceSegmentationRequest,
    WorkspaceSummaryRequest,
)
from app.services.workspace_summary_detail_service import (
    WorkspaceAttributionArtifacts,
    WorkspaceContributionArtifacts,
    _build_workspace_attribution_analytics_request,
    build_workspace_attribution_block,
    build_workspace_contribution_block,
)


def test_workspace_contribution_block_keeps_grouped_and_position_views(mocker):
    mocker.patch(
        "app.services.workspace_summary_detail_service._calculate_reset_aware_period_portfolio_return",
        return_value=0.025,
    )
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PORT-1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1025},
                ],
            },
            "positions_data": [
                {
                    "position_id": "TECH_1",
                    "meta": {"sector": "technology"},
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612},
                        {"perf_date": "2025-01-02", "begin_mv": 612, "end_mv": 624},
                    ],
                },
                {
                    "position_id": "HC_1",
                    "meta": {"sector": "healthcare"},
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 398},
                        {"perf_date": "2025-01-02", "begin_mv": 398, "end_mv": 401},
                    ],
                },
            ],
        }
    )
    artifacts = WorkspaceContributionArtifacts(
        request=request,
        daily_contributions_df=pd.DataFrame(
            {
                "perf_date": [date(2025, 1, 1), date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 2)],
                "position_id": ["TECH_1", "HC_1", "TECH_1", "HC_1"],
                "sector": ["technology", "healthcare", "technology", "healthcare"],
                "smoothed_contribution": [0.012, -0.002, 0.011, 0.004],
                "smoothed_local_contribution": [0.01, -0.002, 0.009, 0.003],
                "smoothed_fx_contribution": [0.002, 0.0, 0.002, 0.001],
                "daily_weight": [0.60, 0.40, 0.61, 0.39],
                "average_weight": [0.605, 0.395, 0.605, 0.395],
                "daily_ror": [2.0, -0.5, 1.9607843137, 0.7537688442],
                "perf_reset": [0, 0, 0, 0],
            }
        ),
        portfolio_results_df=pd.DataFrame(),
        source_details={"position_count": 2, "position_chunk_count": 3, "position_page_count": 4},
    )

    block = build_workspace_contribution_block(
        artifacts=artifacts,
        contribution_options=WorkspaceContributionSummaryRequest(metric_basis="NET", top_positions=1),
        segmentation=WorkspaceSegmentationRequest(group_by=["sector"]),
        period_start_date=date(2025, 1, 1),
        period_end_date=date(2025, 1, 2),
    )

    assert block is not None
    assert block.metric_basis == "NET"
    assert block.segmentation == ["sector"]
    assert block.levels is not None
    assert block.levels[0].name == "sector"
    assert len(block.position_contributions) == 1
    assert block.position_contributions[0].position_id == "TECH_1"
    assert block.position_contributions[0].total_return == pytest.approx(4.0)


def test_workspace_attribution_block_reuses_canonical_attribution_result_shape():
    request = AttributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "mode": "by_instrument",
            "frequency": "daily",
            "group_by": ["sector"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "instruments_data": [],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "technology"},
                    "observations": [
                        {"date": "2025-01-01", "weight_bop": 1.0, "return_base": 0.01},
                        {"date": "2025-01-02", "weight_bop": 1.0, "return_base": 0.01},
                    ],
                }
            ],
        }
    )
    effects_df = pd.DataFrame(
        {
            "sector": ["technology", "technology"],
            "w_p": [1.0, 1.0],
            "w_b": [1.0, 1.0],
            "r_base_p": [0.012, 0.008],
            "r_base_b": [0.010, 0.009],
            "r_b_total": [0.010, 0.009],
            "allocation": [0.0, 0.0],
            "selection": [0.002, -0.001],
            "interaction": [0.0, 0.0],
        },
        index=pd.MultiIndex.from_arrays(
            [pd.to_datetime(["2025-01-01", "2025-01-02"])],
            names=["date"],
        ),
    )
    artifacts = WorkspaceAttributionArtifacts(
        request=request,
        effects_df=effects_df,
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source="calculated",
        source_details={
            "instrument_count": 2,
            "position_chunk_count": 2,
            "position_page_count": 3,
            "benchmark_chunk_count": 1,
            "benchmark_page_count": 1,
            "index_page_count": 1,
        },
    )

    block = build_workspace_attribution_block(
        artifacts=artifacts,
        attribution_options=WorkspaceAttributionSummaryRequest(metric_basis="NET"),
        segmentation=WorkspaceSegmentationRequest(group_by=["sector"]),
        period_start_date=date(2025, 1, 1),
        period_end_date=date(2025, 1, 2),
    )

    assert block is not None
    assert block.metric_basis == "NET"
    assert block.segmentation == ["sector"]
    assert block.benchmark_context is not None
    assert block.benchmark_context.benchmark_id == "BMK_1"
    assert block.result.levels[0].dimension == "sector"


def test_workspace_contribution_block_returns_none_for_empty_period_slice(mocker):
    mocker.patch(
        "app.services.workspace_summary_detail_service._calculate_reset_aware_period_portfolio_return",
        return_value=0.025,
    )
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PORT-1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1025}],
            },
            "positions_data": [
                {
                    "position_id": "TECH_1",
                    "meta": {"sector": "technology"},
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1025}],
                }
            ],
        }
    )
    artifacts = WorkspaceContributionArtifacts(
        request=request,
        daily_contributions_df=pd.DataFrame(
            {
                "perf_date": [date(2025, 1, 1)],
                "position_id": ["TECH_1"],
                "sector": ["technology"],
                "smoothed_contribution": [0.012],
                "smoothed_local_contribution": [0.01],
                "smoothed_fx_contribution": [0.002],
                "daily_weight": [1.0],
                "average_weight": [1.0],
            }
        ),
        portfolio_results_df=pd.DataFrame(),
        source_details={"position_count": 1},
    )

    block = build_workspace_contribution_block(
        artifacts=artifacts,
        contribution_options=WorkspaceContributionSummaryRequest(metric_basis="NET", top_positions=1),
        segmentation=WorkspaceSegmentationRequest(group_by=["sector"]),
        period_start_date=date(2025, 1, 2),
        period_end_date=date(2025, 1, 2),
    )

    assert block is None


def test_workspace_attribution_block_returns_none_when_effects_are_empty():
    request = AttributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "mode": "by_group",
            "frequency": "daily",
            "group_by": ["sector"],
            "portfolio_groups_data": [],
            "benchmark_groups_data": [],
        }
    )
    artifacts = WorkspaceAttributionArtifacts(
        request=request,
        effects_df=pd.DataFrame(),
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source="calculated",
        source_details={},
    )

    block = build_workspace_attribution_block(
        artifacts=artifacts,
        attribution_options=WorkspaceAttributionSummaryRequest(metric_basis="NET"),
        segmentation=WorkspaceSegmentationRequest(group_by=["sector"]),
        period_start_date=date(2025, 1, 1),
        period_end_date=date(2025, 1, 2),
    )

    assert block is None


def test_workspace_attribution_block_returns_none_for_empty_period_slice():
    request = AttributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "mode": "by_group",
            "frequency": "daily",
            "group_by": ["sector"],
            "portfolio_groups_data": [],
            "benchmark_groups_data": [],
        }
    )
    effects_df = pd.DataFrame(
        {"sector": ["technology"], "allocation": [0.0], "selection": [0.1], "interaction": [0.0]},
        index=pd.MultiIndex.from_arrays([pd.to_datetime(["2025-01-01"])], names=["date"]),
    )
    artifacts = WorkspaceAttributionArtifacts(
        request=request,
        effects_df=effects_df,
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source="calculated",
        source_details={},
    )

    block = build_workspace_attribution_block(
        artifacts=artifacts,
        attribution_options=WorkspaceAttributionSummaryRequest(metric_basis="NET"),
        segmentation=WorkspaceSegmentationRequest(group_by=["sector"]),
        period_start_date=date(2025, 1, 2),
        period_end_date=date(2025, 1, 2),
    )

    assert block is None


def test_workspace_attribution_request_carries_stateful_benchmark_override():
    workspace_request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2025-01-02",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
            "segmentation": {"group_by": ["sector"]},
            "attribution": {"metric_basis": "NET"},
            "benchmark": {"input_mode": "stateful", "benchmark_id": "BMK_LINKED", "stateful_input": {}},
        }
    )

    analytics_request = _build_workspace_attribution_analytics_request(
        workspace_request=workspace_request,
        attribution_options=WorkspaceAttributionSummaryRequest(metric_basis="NET"),
        segmentation=WorkspaceSegmentationRequest(group_by=["sector"]),
        master_start_date=date(2025, 1, 1),
    )

    assert analytics_request.stateful_input.benchmark_id == "BMK_LINKED"
