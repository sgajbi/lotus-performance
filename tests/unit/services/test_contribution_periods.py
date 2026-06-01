from datetime import date

import pandas as pd

from app.services.contribution_periods import _extract_reset_dates, _slice_contribution_period_frames
from engine.schema import PortfolioColumns


def test_slice_contribution_period_frames_uses_observation_date_boundaries():
    daily_contributions_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: ["2026-03-30T12:00:00Z", "2026-03-31T12:00:00Z"],
            "position_id": ["SEC_A", "SEC_A"],
        }
    )
    portfolio_results_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: ["2026-03-30", "2026-03-31"],
            PortfolioColumns.PERF_RESET.value: [0, 1],
        }
    )

    frames = _slice_contribution_period_frames(
        daily_contributions_df=daily_contributions_df,
        portfolio_results_df=portfolio_results_df,
        start_date=date(2026, 3, 31),
        end_date=date(2026, 3, 31),
    )

    assert frames.period_slice_df[PortfolioColumns.PERF_DATE.value].tolist() == ["2026-03-31T12:00:00Z"]
    assert frames.portfolio_period_slice_df[PortfolioColumns.PERF_DATE.value].tolist() == ["2026-03-31"]


def test_extract_reset_dates_uses_shared_observation_date_set():
    period_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: ["2026-03-30", "2026-03-31T12:00:00Z"],
            PortfolioColumns.PERF_RESET.value: [0, 1],
        }
    )

    assert _extract_reset_dates(period_df) == {date(2026, 3, 31)}
