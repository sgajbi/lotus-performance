from datetime import date

import pandas as pd

from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import PositionContributionSeries, PositionDailyContribution
from app.services.contribution_series import (
    _adjusted_position_hierarchy_records,
    _apply_hierarchy_unclassified_policy,
    _build_hierarchy_from_adjusted_position_series,
    _daily_hierarchy_metadata,
)
from engine.schema import PortfolioColumns


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
