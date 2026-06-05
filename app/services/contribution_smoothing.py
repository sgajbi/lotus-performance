from __future__ import annotations

from typing import Any

import pandas as pd

from app.models.contribution_responses import ContributionSmoothingEvidence
from app.services.analytics_numeric import valid_numeric_series
from app.services.contribution_methodology import _as_numeric
from engine.schema import PortfolioColumns


def _count_carino_invalid_domain_days(portfolio_period_slice_df: pd.DataFrame) -> int:
    """Counts days where Carino smoothing leaves its valid logarithmic return domain.

    Domain meaning:
    Carino smoothing uses ``log(1 + r)``. Once a daily portfolio return reaches ``-100%`` or
    below, the linked gross return factor stops being positive and logarithmic smoothing is no
    longer economically or mathematically defensible for that period slice.
    """
    if portfolio_period_slice_df.empty or PortfolioColumns.DAILY_ROR.value not in portfolio_period_slice_df.columns:
        return 0

    daily_returns = valid_numeric_series(portfolio_period_slice_df[PortfolioColumns.DAILY_ROR.value])
    return int((1 + (daily_returns / 100) <= 0).sum())


def _contribution_smoothing_status_and_reasons(
    *,
    smoothing_method: str,
    invalid_domain_days: int,
    raw_residual,
    smoothing_residual,
    residual_allocation_applied: bool,
) -> tuple[str, list[str]]:
    reason_codes: list[str] = []
    if smoothing_method != "CARINO":
        status_text = "NOT_REQUESTED"
        reason_codes.append("SMOOTHING_NOT_REQUESTED")
    elif invalid_domain_days > 0:
        status_text = "INVALID_DOMAIN_FALLBACK"
        reason_codes.append("CARINO_INVALID_DAILY_LOG_DOMAIN")
    else:
        status_text = "APPLIED"
        reason_codes.append("CARINO_FACTOR_APPLIED")

    if residual_allocation_applied:
        reason_codes.append("RESIDUAL_ALLOCATED_TO_RECONCILE_PERIOD")
    if abs(raw_residual) > 1e-12:
        reason_codes.append("RAW_CONTRIBUTION_DIFFERS_FROM_LINKED_RETURN")
    if abs(smoothing_residual) <= 1e-9 and smoothing_method == "CARINO" and invalid_domain_days == 0:
        reason_codes.append("SMOOTHED_CONTRIBUTION_RECONCILES")
    return status_text, sorted(set(reason_codes))


def _carino_factor_range(period_slice_df: pd.DataFrame) -> tuple[Any, Any]:
    if "carino_factor" not in period_slice_df.columns:
        return None, None

    factors = valid_numeric_series(period_slice_df["carino_factor"])
    if factors.empty:
        return None, None
    return _as_numeric(factors.min(), default=None), _as_numeric(factors.max(), default=None)


def _build_contribution_smoothing_evidence(
    *,
    period_slice_df: pd.DataFrame,
    portfolio_period_slice_df: pd.DataFrame,
    smoothing_method: str,
    linked_return,
    final_contribution,
    residual_allocation_applied: bool,
    residual_allocation_basis: str | None,
) -> ContributionSmoothingEvidence:
    """Builds support-safe raw/smoothed contribution evidence for one resolved period."""
    if period_slice_df.empty:
        return ContributionSmoothingEvidence(
            smoothing_method=smoothing_method,
            status="NO_CONTRIBUTION_ROWS",
            reason_codes=["NO_CONTRIBUTION_ROWS"],
            linked_return=linked_return * 100,
            raw_contribution=0.0,
            smoothed_contribution=0.0,
            final_contribution=final_contribution * 100,
            raw_residual=linked_return * 100,
            smoothing_residual=linked_return * 100,
            post_allocation_residual=(linked_return - final_contribution) * 100,
            residual_allocation_applied=False,
            residual_allocation_basis=None,
            invalid_domain_days=0,
        )

    raw_contribution = _as_numeric(period_slice_df.get("raw_contribution", pd.Series()).sum())
    smoothed_contribution = _as_numeric(period_slice_df.get("smoothed_contribution", pd.Series()).sum())
    invalid_domain_days = (
        _count_carino_invalid_domain_days(portfolio_period_slice_df) if smoothing_method == "CARINO" else 0
    )
    raw_residual = linked_return - raw_contribution
    smoothing_residual = linked_return - smoothed_contribution
    post_allocation_residual = linked_return - final_contribution
    status_text, reason_codes = _contribution_smoothing_status_and_reasons(
        smoothing_method=smoothing_method,
        invalid_domain_days=invalid_domain_days,
        raw_residual=raw_residual,
        smoothing_residual=smoothing_residual,
        residual_allocation_applied=residual_allocation_applied,
    )
    carino_factor_min, carino_factor_max = _carino_factor_range(period_slice_df)

    return ContributionSmoothingEvidence(
        smoothing_method=smoothing_method,
        status=status_text,
        reason_codes=reason_codes,
        linked_return=linked_return * 100,
        raw_contribution=raw_contribution * 100,
        smoothed_contribution=smoothed_contribution * 100,
        final_contribution=final_contribution * 100,
        raw_residual=raw_residual * 100,
        smoothing_residual=smoothing_residual * 100,
        post_allocation_residual=post_allocation_residual * 100,
        residual_allocation_applied=residual_allocation_applied,
        residual_allocation_basis=residual_allocation_basis if residual_allocation_applied else None,
        carino_factor_min=carino_factor_min,
        carino_factor_max=carino_factor_max,
        invalid_domain_days=invalid_domain_days,
    )
