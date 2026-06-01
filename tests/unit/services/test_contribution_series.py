from datetime import date

import pandas as pd

from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import PositionContributionSeries, PositionDailyContribution
from app.services.contribution_series import _build_hierarchy_from_adjusted_position_series
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
