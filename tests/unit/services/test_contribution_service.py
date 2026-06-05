from datetime import date
from types import SimpleNamespace

import pandas as pd
from fastapi import HTTPException

from app.services import contribution_service
from engine.schema import PortfolioColumns


def test_prepare_contribution_engine_inputs_resolves_master_window_and_normalizes_dates(monkeypatch):
    periods = [
        SimpleNamespace(name="JAN", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)),
        SimpleNamespace(name="FEB", start_date=date(2026, 2, 1), end_date=date(2026, 2, 28)),
    ]
    instruments_df = pd.DataFrame({"instrument_id": ["A"]})
    portfolio_results_df = pd.DataFrame({"portfolio_id": ["P"]})
    daily_contributions_df = pd.DataFrame({PortfolioColumns.PERF_DATE.value: ["2026-01-02"]})
    request = SimpleNamespace(
        analyses=[SimpleNamespace(period="JAN"), SimpleNamespace(period="FEB")],
        portfolio_data=SimpleNamespace(valuation_points=[SimpleNamespace(perf_date=date(2025, 12, 31))]),
        report_end_date=date(2026, 2, 28),
        report_start_date=date(2026, 1, 1),
        weighting_scheme="daily",
        smoothing=SimpleNamespace(method="NONE"),
    )
    resolve_calls: list[tuple[object, ...]] = []

    def resolve_periods(periods_to_resolve, report_end_date, inception_date, *, explicit_start_date):
        resolve_calls.append((periods_to_resolve, report_end_date, inception_date, explicit_start_date))
        return periods

    monkeypatch.setattr(contribution_service, "resolve_periods", resolve_periods)
    monkeypatch.setattr(
        contribution_service,
        "_prepare_hierarchical_data",
        lambda prepared_request: (instruments_df, portfolio_results_df),
    )
    monkeypatch.setattr(
        contribution_service,
        "_calculate_daily_instrument_contributions",
        lambda *_args: daily_contributions_df,
    )

    result = contribution_service._prepare_contribution_engine_inputs(request)

    assert resolve_calls == [(["JAN", "FEB"], date(2026, 2, 28), date(2025, 12, 31), date(2026, 1, 1))]
    assert result.periods_to_resolve == ["JAN", "FEB"]
    assert result.resolved_periods == periods
    assert result.master_start_date == date(2026, 1, 1)
    assert result.master_end_date == date(2026, 2, 28)
    assert result.instruments_df is instruments_df
    assert result.portfolio_results_df is portfolio_results_df
    assert result.daily_contributions_df[PortfolioColumns.PERF_DATE.value].tolist() == [date(2026, 1, 2)]


def test_prepare_contribution_engine_inputs_rejects_unresolved_periods(monkeypatch):
    request = SimpleNamespace(
        analyses=[SimpleNamespace(period="MTD")],
        portfolio_data=SimpleNamespace(valuation_points=[]),
        report_end_date=date(2026, 2, 28),
        report_start_date=None,
    )
    monkeypatch.setattr(contribution_service, "resolve_periods", lambda *_args, **_kwargs: [])

    try:
        contribution_service._prepare_contribution_engine_inputs(request)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "No valid periods could be resolved."
    else:
        raise AssertionError("Expected HTTPException for unresolved contribution periods.")
