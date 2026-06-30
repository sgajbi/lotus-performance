from datetime import date

import pandas as pd
import pytest

from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    PositionContribution,
    PositionContributionSeries,
    PositionDailyContribution,
)
from app.services.contribution_series import (
    _adjusted_position_hierarchy_records,
    _apply_hierarchy_unclassified_policy,
    _build_hierarchy_from_adjusted_position_series,
    _daily_hierarchy_metadata,
    _has_adjusted_hierarchy_inputs,
    _hierarchy_metadata_columns,
    _other_hierarchy_row_for_emission,
    _prepared_adjusted_hierarchy_frames,
    _residual_adjusted_daily_totals_by_date,
    _residual_adjusted_position_rows,
    _target_total_contribution_by_position,
)
from engine.schema import PortfolioColumns


def test_has_adjusted_hierarchy_inputs_requires_hierarchy_period_rows_and_position_series():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                ],
            },
            "positions_data": [
                {
                    "position_id": "SEC_A",
                    "valuation_points": [
                        {"perf_date": "2026-03-30", "begin_mv": 500, "end_mv": 505},
                    ],
                }
            ],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A"],
            PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30)],
            "daily_weight": [0.5],
            "sector": ["Technology"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[PositionDailyContribution(date=date(2026, 3, 30), contribution=1.0)],
        )
    ]

    assert _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request,
    )
    assert not _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request.model_copy(update={"hierarchy": []}),
    )
    assert not _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df.iloc[0:0],
        position_series=position_series,
        request=request,
    )
    assert not _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=[],
        request=request,
    )


def test_build_hierarchy_from_adjusted_position_series_uses_observation_date_alignment():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-31", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {
                    "position_id": "SEC_A",
                    "valuation_points": [
                        {"perf_date": "2026-03-30", "begin_mv": 500, "end_mv": 505},
                        {"perf_date": "2026-03-31", "begin_mv": 505, "end_mv": 510},
                    ],
                }
            ],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_A"],
            PortfolioColumns.PERF_DATE.value: ["2026-03-30T12:00:00Z", "2026-03-31T12:00:00Z"],
            "daily_weight": [0.5, 0.5],
            "sector": ["Technology", "Technology"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[
                PositionDailyContribution(date=date(2026, 3, 30), contribution=1.0),
                PositionDailyContribution(date=date(2026, 3, 31), contribution=2.0),
            ],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request,
    )

    assert hierarchy["summary"]["portfolio_contribution"] == 3.0
    assert hierarchy["levels"][0]["rows"] == [
        {"key": {"sector": "Technology"}, "contribution": 3.0, "weight_avg": 50.0}
    ]


def test_build_hierarchy_from_adjusted_position_series_uses_selected_period_average_weights():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-31", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {"position_id": "SEC_A", "valuation_points": []},
                {"position_id": "SEC_B", "valuation_points": []},
            ],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_A", "SEC_B", "SEC_B"],
            PortfolioColumns.PERF_DATE.value: [
                date(2026, 3, 30),
                date(2026, 3, 31),
                date(2026, 3, 30),
                date(2026, 3, 31),
            ],
            "daily_weight": [0.10, 0.95, 0.90, 0.05],
            "sector": ["Technology", "Technology", "Health Care", "Health Care"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[
                PositionDailyContribution(date=date(2026, 3, 30), contribution=1.0),
                PositionDailyContribution(date=date(2026, 3, 31), contribution=1.0),
            ],
        ),
        PositionContributionSeries(
            position_id="SEC_B",
            series=[
                PositionDailyContribution(date=date(2026, 3, 30), contribution=2.0),
                PositionDailyContribution(date=date(2026, 3, 31), contribution=2.0),
            ],
        ),
    ]
    selected_average_weights = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_B"],
            "selected_average_weight": [0.95, 0.05],
        }
    )

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        position_series=position_series,
        position_average_weights=selected_average_weights,
        request=request,
    )

    rows_by_sector = {row["key"]["sector"]: row for row in hierarchy["levels"][0]["rows"]}
    assert rows_by_sector["Technology"]["weight_avg"] == pytest.approx(95.0)
    assert rows_by_sector["Health Care"]["weight_avg"] == pytest.approx(5.0)


def test_hierarchy_metadata_helpers_align_dates_and_unclassified_policy():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "hierarchy": ["sector", "region"],
            "emit": {"include_unclassified": True, "threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-31", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {
                    "position_id": "SEC_A",
                    "valuation_points": [
                        {"perf_date": "2026-03-30", "begin_mv": 500, "end_mv": 505},
                    ],
                }
            ],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[PositionDailyContribution(date=date(2026, 3, 30), contribution=1.25)],
        )
    ]
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A"],
            PortfolioColumns.PERF_DATE.value: ["2026-03-30T12:00:00Z"],
            "daily_weight": [0.5],
            "sector": ["Technology"],
        }
    )

    records = _adjusted_position_hierarchy_records(position_series)
    metadata = _daily_hierarchy_metadata(period_slice_df, hierarchy_levels=request.hierarchy)
    merged_df = pd.DataFrame(records).merge(
        metadata,
        on=["position_id", PortfolioColumns.PERF_DATE.value],
        how="left",
    )
    classified_df = _apply_hierarchy_unclassified_policy(merged_df, request=request)

    assert records == [
        {
            "position_id": "SEC_A",
            PortfolioColumns.PERF_DATE.value: date(2026, 3, 30),
            "adjusted_contribution": 0.0125,
        }
    ]
    assert list(metadata.columns) == [
        "position_id",
        PortfolioColumns.PERF_DATE.value,
        "daily_weight",
        "sector",
        "region",
    ]
    assert metadata.iloc[0][PortfolioColumns.PERF_DATE.value] == date(2026, 3, 30)
    assert classified_df.iloc[0]["region"] == "Unclassified"

    exclude_request = request.model_copy(
        update={"emit": request.emit.model_copy(update={"include_unclassified": False})}
    )
    assert _apply_hierarchy_unclassified_policy(merged_df, request=exclude_request).empty
    assert (
        _prepared_adjusted_hierarchy_frames(
            period_slice_df=period_slice_df,
            position_series=position_series,
            request=exclude_request,
        )
        is None
    )


def test_hierarchy_metadata_columns_preserves_base_columns_and_unique_levels():
    assert _hierarchy_metadata_columns(
        [
            "sector",
            "daily_weight",
            "region",
            "sector",
            PortfolioColumns.PERF_DATE.value,
        ]
    ) == [
        "position_id",
        PortfolioColumns.PERF_DATE.value,
        "daily_weight",
        "sector",
        "region",
    ]


def test_other_hierarchy_row_for_emission_aggregates_overflow_rows_and_suppresses_when_disabled():
    overflow_rows = pd.DataFrame(
        {
            "contribution": [0.0125, -0.0025],
            "weight_avg": [0.15, 0.05],
        }
    )

    assert _other_hierarchy_row_for_emission(
        overflow_rows=overflow_rows,
        level_keys=["sector", "region"],
        include_other=True,
    ) == {
        "key": {"sector": "Other", "region": "Other"},
        "contribution": 1.0,
        "weight_avg": 20.0,
        "children_count": 2,
        "is_other": True,
    }
    assert (
        _other_hierarchy_row_for_emission(
            overflow_rows=overflow_rows,
            level_keys=["sector"],
            include_other=False,
        )
        is None
    )
    assert (
        _other_hierarchy_row_for_emission(
            overflow_rows=overflow_rows.iloc[0:0],
            level_keys=["sector"],
            include_other=True,
        )
        is None
    )


def test_residual_adjusted_position_rows_allocate_by_weight_and_equal_fallback():
    weighted_rows = _residual_adjusted_position_rows(
        position_id="SEC_A",
        position_slice=pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)],
                "smoothed_contribution": [0.01, 0.01],
                "daily_weight": [-0.25, 0.75],
            }
        ),
        target_total=0.04,
    )
    equal_fallback_rows = _residual_adjusted_position_rows(
        position_id="SEC_B",
        position_slice=pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)],
                "smoothed_contribution": [0.02, 0.00],
                "daily_weight": [0.0, 0.0],
            }
        ),
        target_total=0.00,
    )

    assert [row["adjusted_contribution"] for row in weighted_rows] == [0.015, 0.025]
    assert [row["adjusted_contribution"] for row in equal_fallback_rows] == [0.01, -0.01]


def test_target_total_contribution_by_position_projects_percentage_totals_to_ratios():
    targets = _target_total_contribution_by_position(
        [
            PositionContribution(
                position_id="SEC_A",
                total_contribution=2.5,
                average_weight=25.0,
                total_return=10.0,
            ),
            PositionContribution(
                position_id="SEC_B",
                total_contribution=0.0,
                average_weight=0.0,
                total_return=0.0,
            ),
        ]
    )

    assert targets == {"SEC_A": 0.025, "SEC_B": 0.0}


def test_residual_adjusted_daily_totals_by_date_aggregates_position_points():
    totals_by_date = _residual_adjusted_daily_totals_by_date(
        [
            PositionContributionSeries(
                position_id="SEC_A",
                series=[
                    PositionDailyContribution(date=date(2026, 3, 30), contribution=1.25),
                    PositionDailyContribution(date=date(2026, 3, 31), contribution=-0.25),
                ],
            ),
            PositionContributionSeries(
                position_id="SEC_B",
                series=[
                    PositionDailyContribution(date=date(2026, 3, 30), contribution=2.75),
                ],
            ),
        ]
    )

    assert totals_by_date == {
        date(2026, 3, 30): 4.0,
        date(2026, 3, 31): -0.25,
    }
