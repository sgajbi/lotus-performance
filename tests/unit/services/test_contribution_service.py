from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from app.models.contribution_responses import AverageWeightMethodologyStatus, PositionContribution
from app.services import contribution_service
from app.services.contribution_audit import AverageWeightShadowAuditState
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


def test_build_flat_period_contribution_result_preserves_average_weight_basis(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "smoothed_contribution": [0.01]})
    portfolio_period_slice_df = pd.DataFrame({"portfolio_id": ["P"]})
    totals_df = pd.DataFrame({"position_id": ["A"], "selected_average_weight": [0.5]})
    average_weight_shadow_df = pd.DataFrame(
        {
            "position_id": ["A"],
            "average_weight": [0.4],
            "reset_aware_average_weight_shadow": [0.5],
        }
    )
    period = SimpleNamespace(name="QTD", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
    request = SimpleNamespace(
        smoothing=SimpleNamespace(method="CARINO"),
        emit=SimpleNamespace(timeseries=False, by_position_timeseries=False),
    )
    audit_state = AverageWeightShadowAuditState()
    residual_calls: list[dict[str, object]] = []
    smoothing_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        contribution_service,
        "_slice_contribution_period_frames",
        lambda **_kwargs: SimpleNamespace(
            period_slice_df=period_slice_df,
            portfolio_period_slice_df=portfolio_period_slice_df,
        ),
    )
    monkeypatch.setattr(
        contribution_service,
        "_build_contribution_period_methodology_context",
        lambda **_kwargs: SimpleNamespace(
            delta_positions=2,
            max_shadow_delta_bp=125,
            sum_shadow_delta_bp=175,
            average_weight_shadow_df=average_weight_shadow_df,
        ),
    )
    monkeypatch.setattr(
        contribution_service,
        "_select_period_average_weight_column",
        lambda **_kwargs: ("reset_aware_average_weight_shadow", True),
    )
    monkeypatch.setattr(
        contribution_service,
        "_calculate_reset_aware_period_portfolio_return",
        lambda *_args: 0.0348,
    )

    def build_residual_adjusted_position_totals(**kwargs):
        residual_calls.append(kwargs)
        return SimpleNamespace(totals_df=totals_df, residual_allocation_applied=True)

    monkeypatch.setattr(
        contribution_service,
        "build_residual_adjusted_position_totals",
        build_residual_adjusted_position_totals,
    )
    monkeypatch.setattr(
        contribution_service,
        "build_position_contributions",
        lambda **_kwargs: [
            PositionContribution(
                position_id="A",
                total_contribution=3.48,
                average_weight=50.0,
                total_return=6.96,
            )
        ],
    )
    monkeypatch.setattr(
        contribution_service,
        "_build_period_contribution_series_outputs",
        lambda **_kwargs: ([], None, None),
    )
    monkeypatch.setattr(contribution_service, "_calculate_average_weight_sum_residual_bp", lambda _rows: 12)

    def build_smoothing_evidence(**kwargs):
        smoothing_calls.append(kwargs)
        return None

    monkeypatch.setattr(contribution_service, "_build_contribution_smoothing_evidence", build_smoothing_evidence)
    monkeypatch.setattr(contribution_service, "_record_period_timeseries_total_delta", lambda **_kwargs: 0)
    monkeypatch.setattr(
        contribution_service,
        "_build_period_average_weight_methodology_status",
        lambda **_kwargs: AverageWeightMethodologyStatus(
            status="PROMOTED",
            max_shadow_delta_bp=125,
            is_material_shadow=True,
            is_cutover_candidate=True,
            is_promoted=True,
        ),
    )

    result = contribution_service._build_flat_period_contribution_result(
        request=request,
        period=period,
        daily_contributions_df=pd.DataFrame(),
        portfolio_results_df=pd.DataFrame(),
        reset_aware_average_weight_mode="candidate_periods",
        average_weight_audit_state=audit_state,
    )

    assert result is not None
    assert result.period_name == "QTD"
    assert result.average_weight_sum_residual_bp == 12
    assert result.result.total_portfolio_return == pytest.approx(3.48)
    assert result.result.total_contribution == 3.48
    assert result.result.average_weight_methodology_status is not None
    assert result.result.average_weight_methodology_status.is_promoted is True
    assert audit_state.delta_positions == 2
    assert residual_calls[0]["selected_average_weight_source_column"] == "reset_aware_average_weight_shadow"
    assert residual_calls[0]["residual_allocation_weight_column"] == "selected_average_weight"
    assert smoothing_calls[0]["residual_allocation_basis"] == "reset_aware_average_weight_shadow"
