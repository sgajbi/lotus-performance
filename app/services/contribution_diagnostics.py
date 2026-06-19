from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.analytics_observation_dates import observation_date_series, observation_date_set
from app.services.contribution_methodology import _numeric_series_or_default, _to_basis_points
from core.envelope import Diagnostics
from engine.diagnostics import EngineDiagnostics
from engine.schema import PortfolioColumns


def _calculate_reset_relative_day_counts(portfolio_results_df: pd.DataFrame) -> tuple[int, int]:
    """Calculates reset-relative NIP and valid day counts from the portfolio engine frame."""
    if portfolio_results_df.empty:
        return 0, 0

    perf_reset_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value)
    nip_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.NIP.value)
    reset_rows = perf_reset_series == 1
    if reset_rows.any():
        relevant_df = portfolio_results_df.loc[reset_rows[reset_rows].index[-1] :]
        relevant_nip_series = nip_series.loc[relevant_df.index]
    else:
        relevant_df = portfolio_results_df
        relevant_nip_series = nip_series

    nip_days_since_last_reset = int(relevant_nip_series.sum())
    valid_days_since_last_reset = int(len(relevant_df) - nip_days_since_last_reset)
    return nip_days_since_last_reset, valid_days_since_last_reset


def _calculate_reset_characterization_counts(
    portfolio_results_df: pd.DataFrame,
) -> tuple[int, int, int, int, int, int, int]:
    """Calculates reset characterization counts from the portfolio engine frame."""
    if portfolio_results_df.empty:
        return 0, 0, 0, 0, 0, 0, 0

    active_reset_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value) == 1
    nctrl4_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.NCTRL_4.value) == 1
    account_reset_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.ACCOUNT_RESET.value) == 1
    sod_reset_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.SOD_RESET.value) == 1
    shadow_overlap_mask = account_reset_mask & sod_reset_mask
    any_shadow_mask = account_reset_mask | sod_reset_mask
    nctrl4_exclusive_mask = nctrl4_mask & ~any_shadow_mask
    shadow_only_candidate_reset_mask = any_shadow_mask & ~active_reset_mask
    active_reset_with_shadow_mask = active_reset_mask & any_shadow_mask

    return (
        int(nctrl4_mask.sum()),
        int(nctrl4_exclusive_mask.sum()),
        int(account_reset_mask.sum()),
        int(sod_reset_mask.sum()),
        int(shadow_overlap_mask.sum()),
        int(shadow_only_candidate_reset_mask.sum()),
        int(active_reset_with_shadow_mask.sum()),
    )


def _build_portfolio_engine_diagnostics(portfolio_results_df: pd.DataFrame, effective_period_start) -> Diagnostics:
    """Maps portfolio-engine state already present in contribution inputs into shared diagnostics."""
    if portfolio_results_df.empty:
        return Diagnostics(nip_days=0, reset_days=0, effective_period_start=effective_period_start, notes=[])

    nip_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.NIP.value)
    nip_v1_series = _numeric_series_or_default(portfolio_results_df, "nip_rule_v1_shadow")
    nip_v2_series = _numeric_series_or_default(portfolio_results_df, "nip_rule_v2_shadow")
    perf_reset_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value)
    (
        nctrl4_reset_days,
        nctrl4_exclusive_reset_days,
        account_reset_shadow_days,
        sod_reset_shadow_days,
        shadow_reset_overlap_days,
        shadow_only_candidate_reset_days,
        active_reset_with_shadow_days,
    ) = _calculate_reset_characterization_counts(portfolio_results_df)
    candidate_canonical_reset_days = int(
        (
            perf_reset_series.eq(1)
            | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.ACCOUNT_RESET.value).eq(1)
            | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.SOD_RESET.value).eq(1)
        ).sum()
    )
    reset_delta_days = int(
        (
            (
                perf_reset_series.eq(1)
                | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.ACCOUNT_RESET.value).eq(1)
                | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.SOD_RESET.value).eq(1)
            )
            != perf_reset_series.eq(1)
        ).sum()
    )
    nip_days_since_last_reset, valid_days_since_last_reset = _calculate_reset_relative_day_counts(portfolio_results_df)

    diagnostics = EngineDiagnostics(
        nip_days=int(nip_series.sum()),
        nip_rule_delta_days=int((nip_v1_series != nip_v2_series).sum()),
        reset_days=int(perf_reset_series.sum()),
        nctrl4_reset_days=nctrl4_reset_days,
        nctrl4_exclusive_reset_days=nctrl4_exclusive_reset_days,
        account_reset_shadow_days=account_reset_shadow_days,
        sod_reset_shadow_days=sod_reset_shadow_days,
        shadow_reset_overlap_days=shadow_reset_overlap_days,
        shadow_only_candidate_reset_days=shadow_only_candidate_reset_days,
        active_reset_with_shadow_days=active_reset_with_shadow_days,
        candidate_canonical_reset_days=candidate_canonical_reset_days,
        reset_delta_days=reset_delta_days,
        nip_days_since_last_reset=nip_days_since_last_reset,
        valid_days_since_last_reset=valid_days_since_last_reset,
        effective_period_start=effective_period_start,
    )
    return Diagnostics.model_validate(
        {
            "nip_days": diagnostics.nip_days,
            "nip_rule_delta_days": diagnostics.nip_rule_delta_days,
            "reset_days": diagnostics.reset_days,
            "nctrl4_reset_days": diagnostics.nctrl4_reset_days,
            "nctrl4_exclusive_reset_days": diagnostics.nctrl4_exclusive_reset_days,
            "account_reset_shadow_days": diagnostics.account_reset_shadow_days,
            "sod_reset_shadow_days": diagnostics.sod_reset_shadow_days,
            "shadow_reset_overlap_days": diagnostics.shadow_reset_overlap_days,
            "shadow_only_candidate_reset_days": diagnostics.shadow_only_candidate_reset_days,
            "active_reset_with_shadow_days": diagnostics.active_reset_with_shadow_days,
            "candidate_canonical_reset_days": diagnostics.candidate_canonical_reset_days,
            "reset_delta_days": diagnostics.reset_delta_days,
            "nip_days_since_last_reset": diagnostics.nip_days_since_last_reset,
            "valid_days_since_last_reset": diagnostics.valid_days_since_last_reset,
            "effective_period_start": effective_period_start,
            "notes": [],
        }
    )


def _calculate_grouped_return_reset_alignment_counts(
    instruments_df: pd.DataFrame,
    portfolio_results_df: pd.DataFrame,
) -> dict[str, int]:
    """Characterizes whether position-level reset days line up with portfolio reset days.

    Domain meaning:
    contribution relies on per-position engine runs plus the portfolio engine run. If those paths
    disagree on reset boundaries, contribution can still reconcile numerically in simple cases while
    telling a different state story from TWR. This helper keeps that alignment visible without
    changing behavior yet.
    """
    if instruments_df.empty or portfolio_results_df.empty:
        return {
            "portfolio_reset_days": 0,
            "position_reset_days": 0,
            "portfolio_reset_without_position_reset_days": 0,
            "position_reset_without_portfolio_reset_days": 0,
        }

    if PortfolioColumns.PERF_RESET.value not in instruments_df.columns:
        position_reset_dates: set[Any] = set()
    else:
        position_reset_dates = observation_date_set(
            instruments_df.loc[
                _numeric_series_or_default(instruments_df, PortfolioColumns.PERF_RESET.value) == 1,
                PortfolioColumns.PERF_DATE.value,
            ]
        )

    portfolio_reset_dates = observation_date_set(
        portfolio_results_df.loc[
            _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value) == 1,
            PortfolioColumns.PERF_DATE.value,
        ]
    )

    return {
        "portfolio_reset_days": len(portfolio_reset_dates),
        "position_reset_days": len(position_reset_dates),
        "portfolio_reset_without_position_reset_days": len(portfolio_reset_dates - position_reset_dates),
        "position_reset_without_portfolio_reset_days": len(position_reset_dates - portfolio_reset_dates),
    }


def _empty_position_flow_balance_counts(*, residual_days: int = 0) -> dict[str, int]:
    return {
        "position_flow_residual_days": residual_days,
        "position_flow_residual_max_bp": 0,
        "position_flow_residual_sum_bp": 0,
    }


_FLOW_BALANCE_REQUIRED_COLUMNS = {
    PortfolioColumns.PERF_DATE.value,
    PortfolioColumns.BOD_CF.value,
    PortfolioColumns.EOD_CF.value,
}


def _has_flow_balance_source_columns(frame: pd.DataFrame) -> bool:
    return not frame.empty and _FLOW_BALANCE_REQUIRED_COLUMNS.issubset(frame.columns)


def _daily_cash_flow_series(frame: pd.DataFrame, *, value_name: str) -> pd.Series:
    return (
        pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: observation_date_series(frame[PortfolioColumns.PERF_DATE.value]),
                value_name: _numeric_series_or_default(frame, PortfolioColumns.BOD_CF.value)
                + _numeric_series_or_default(frame, PortfolioColumns.EOD_CF.value),
            }
        )
        .groupby(PortfolioColumns.PERF_DATE.value, dropna=False)[value_name]
        .sum()
    )


def _portfolio_capital_base_by_day(portfolio_results_df: pd.DataFrame) -> pd.Series:
    capital_by_day = (
        pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: observation_date_series(
                    portfolio_results_df[PortfolioColumns.PERF_DATE.value]
                ),
                "capital_base": _numeric_series_or_default(portfolio_results_df, PortfolioColumns.BEGIN_MV.value).abs()
                + _numeric_series_or_default(portfolio_results_df, PortfolioColumns.BOD_CF.value).abs(),
            }
        )
        .groupby(PortfolioColumns.PERF_DATE.value, dropna=False)["capital_base"]
        .max()
    )
    return capital_by_day.replace(0, pd.NA).fillna(1.0)


def _position_flow_counts_without_portfolio_flow(position_flow_by_day: pd.Series) -> dict[str, int]:
    residual_days = int(position_flow_by_day.abs().gt(1e-9).sum())
    return _empty_position_flow_balance_counts(residual_days=residual_days)


def _position_flow_residual_counts(
    residual_flow_by_day: pd.Series,
    portfolio_capital_by_day: pd.Series,
) -> dict[str, int]:
    residual_ratio_by_day = (
        residual_flow_by_day.abs().reindex(portfolio_capital_by_day.index, fill_value=0.0) / portfolio_capital_by_day
    )
    return {
        "position_flow_residual_days": int(residual_flow_by_day.abs().gt(1e-9).sum()),
        "position_flow_residual_max_bp": _to_basis_points(residual_ratio_by_day.max())
        if not residual_ratio_by_day.empty
        else 0,
        "position_flow_residual_sum_bp": _to_basis_points(residual_ratio_by_day.sum())
        if not residual_ratio_by_day.empty
        else 0,
    }


def _calculate_position_flow_balance_counts(
    instruments_df: pd.DataFrame,
    portfolio_results_df: pd.DataFrame,
) -> dict[str, int]:
    """Counts and sizes dates where summed position-level flows fail to reconcile to portfolio flow.

    Domain meaning:
    contribution should still calculate for real-world scoped books even when the visible position
    set is not flow-neutral on every date. When the stock leg and cash leg both sit inside the
    scoped position set, summed position flow on a date will normally net to zero. A non-zero
    residual therefore does not invalidate the engine; it characterizes that the current scoped
    slice includes net flow pressure that sits outside the visible offsetting legs.

    The important nuance is that position flow should reconcile to the portfolio-level net flow for
    the date, not always to literal zero. In a one-position cash portfolio carrying pure external
    funding, the visible position flow is expected to equal the portfolio external flow exactly. We
    therefore measure residual flow as:

    ``summed position flow - portfolio net flow``

    and size that residual relative to the portfolio capital base for the date.
    """
    if not _has_flow_balance_source_columns(instruments_df):
        return _empty_position_flow_balance_counts()

    position_flow_by_day = _daily_cash_flow_series(instruments_df, value_name="position_flow")

    if not _has_flow_balance_source_columns(portfolio_results_df):
        return _position_flow_counts_without_portfolio_flow(position_flow_by_day)

    portfolio_flow_by_day = _daily_cash_flow_series(portfolio_results_df, value_name="portfolio_flow")
    residual_flow_by_day = position_flow_by_day.subtract(portfolio_flow_by_day, fill_value=0.0)

    return _position_flow_residual_counts(
        residual_flow_by_day,
        _portfolio_capital_base_by_day(portfolio_results_df),
    )
