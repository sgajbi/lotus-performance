from uuid import uuid4

import pandas as pd
import pytest

from app.api.endpoints.contribution import _as_numeric
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import DailyContribution
from app.services.contribution_audit import AverageWeightShadowAuditState
from app.services.contribution_calculation_workflow_service import (
    accepted_contribution_response,
    build_contribution_execution_window,
    build_resolved_contribution_execution_window,
    should_offload_contribution,
    should_offload_resolved_contribution,
    should_preemptively_offload_stateful_contribution,
)
from app.services.contribution_diagnostics import (
    _build_portfolio_engine_diagnostics,
    _calculate_grouped_return_reset_alignment_counts,
    _calculate_position_flow_balance_counts,
    _calculate_reset_characterization_counts,
    _calculate_reset_relative_day_counts,
)
from app.services.contribution_methodology import (
    _assess_average_weight_shadow_cutover,
    _build_average_weight_methodology_status,
    _calculate_average_weight_sum_residual_bp,
    _calculate_average_weight_sum_residual_bp_from_ratio_series,
    _calculate_promotion_ready_rate_bp,
    _calculate_reset_aware_average_weight_shadow,
    _classify_average_weight_methodology_status,
    _classify_average_weight_shadow_cutover_blockers,
    _classify_average_weight_shadow_period,
    _is_average_weight_shadow_cutover_candidate,
    _normalize_reset_aware_average_weight_mode,
)
from app.services.contribution_periods import (
    ContributionPeriodMethodologyContext,
    _build_contribution_period_methodology_context,
    _extract_reset_dates,
    _slice_contribution_period_frames,
)
from app.services.contribution_returns import (
    _calculate_position_total_return_pct,
    _calculate_reset_aware_period_portfolio_return,
    build_position_contributions,
    build_residual_adjusted_position_totals,
)
from app.services.contribution_series import (
    _build_daily_contribution_series,
    _build_hierarchy_from_adjusted_position_series,
    _build_position_contribution_series,
    _build_residual_adjusted_daily_contribution_series,
    _build_residual_adjusted_position_timeseries,
)
from app.services.contribution_service import (
    _build_period_average_weight_methodology_status,
    _record_period_timeseries_total_delta,
)
from app.services.contribution_smoothing import _count_carino_invalid_domain_days
from core.envelope import Diagnostics
from engine.schema import PortfolioColumns


def test_contribution_as_numeric_returns_default_for_non_numeric():
    assert _as_numeric("not-a-number", default=3) == 3


def test_average_weight_shadow_audit_state_records_counts_and_diagnostic_notes():
    audit_state = AverageWeightShadowAuditState()

    audit_state.record_shadow_observation(
        delta_positions=2,
        max_shadow_delta_bp=600,
        sum_shadow_delta_bp=700,
    )
    emitted_blockers = audit_state.record_cutover_assessment(
        is_cutover_candidate=False,
        blocker_reason_codes={"weight_residual", "timeseries_reconciliation"},
    )
    audit_state.record_timeseries_total_delta()

    diagnostics = Diagnostics(
        nip_days=0,
        reset_days=0,
        effective_period_start=pd.Timestamp("2025-01-01").date(),
    )
    audit_state.append_diagnostic_notes(
        diagnostics,
        average_weight_sum_residual_bp=2,
        carino_invalid_domain_days=1,
        reset_alignment_counts={
            "portfolio_reset_without_position_reset_days": 1,
            "position_reset_without_portfolio_reset_days": 0,
        },
        position_flow_balance_counts={
            "position_flow_residual_days": 1,
            "position_flow_residual_max_bp": 11,
        },
    )
    counts = audit_state.to_audit_counts(
        average_weight_sum_residual_bp=2,
        carino_invalid_domain_days=1,
    )

    assert emitted_blockers == {"weight_residual", "timeseries_reconciliation"}
    assert counts["average_weight_shadow_delta_positions"] == 2
    assert counts["average_weight_shadow_material_periods"] == 1
    assert counts["average_weight_shadow_blocked_periods"] == 1
    assert counts["timeseries_total_delta_periods"] == 1
    assert any("rollout readiness" in note for note in diagnostics.notes)
    assert any("daily contribution series" in note for note in diagnostics.notes)


def test_build_period_average_weight_methodology_status_records_promotion_ready_period():
    audit_state = AverageWeightShadowAuditState()
    period_context = ContributionPeriodMethodologyContext(
        average_weight_shadow_df=pd.DataFrame(),
        delta_positions=2,
        max_shadow_delta_bp=600,
        sum_shadow_delta_bp=700,
        position_reset_dates={pd.Timestamp("2025-01-02").date()},
        portfolio_reset_dates={pd.Timestamp("2025-01-02").date()},
        position_flow_balance_counts={"position_flow_residual_days": 0},
    )

    status = _build_period_average_weight_methodology_status(
        period_methodology_context=period_context,
        average_weight_sum_residual_bp=0,
        timeseries_total_delta_periods=0,
        average_weight_audit_state=audit_state,
    )

    assert status.status == "PROMOTION_READY"
    assert status.is_cutover_candidate is True
    assert status.is_promoted is False
    assert status.blocker_reason_codes == []
    assert audit_state.cutover_candidate_periods == 1
    assert audit_state.blocked_periods == 0


def test_build_period_average_weight_methodology_status_records_blockers():
    audit_state = AverageWeightShadowAuditState()
    period_context = ContributionPeriodMethodologyContext(
        average_weight_shadow_df=pd.DataFrame(),
        delta_positions=2,
        max_shadow_delta_bp=600,
        sum_shadow_delta_bp=700,
        position_reset_dates={pd.Timestamp("2025-01-03").date()},
        portfolio_reset_dates={pd.Timestamp("2025-01-02").date()},
        position_flow_balance_counts={"position_flow_residual_days": 1},
    )

    blocked_status = _build_period_average_weight_methodology_status(
        period_methodology_context=period_context,
        average_weight_sum_residual_bp=50,
        timeseries_total_delta_periods=1,
        average_weight_audit_state=audit_state,
    )

    assert blocked_status.status == "BLOCKED"
    assert blocked_status.blocker_reason_codes == [
        "flow_balance",
        "reset_alignment",
        "timeseries_reconciliation",
        "weight_residual",
    ]
    assert audit_state.blocked_periods == 1
    assert audit_state.blocked_by_weight_residual_periods == 1
    assert audit_state.blocked_by_flow_balance_periods == 1
    assert audit_state.blocked_by_reset_alignment_periods == 1
    assert audit_state.blocked_by_timeseries_delta_periods == 1


def test_build_period_average_weight_methodology_status_records_promoted_clean_period():
    audit_state = AverageWeightShadowAuditState()
    period_context = ContributionPeriodMethodologyContext(
        average_weight_shadow_df=pd.DataFrame(),
        delta_positions=2,
        max_shadow_delta_bp=600,
        sum_shadow_delta_bp=700,
        position_reset_dates={pd.Timestamp("2025-01-02").date()},
        portfolio_reset_dates={pd.Timestamp("2025-01-02").date()},
        position_flow_balance_counts={"position_flow_residual_days": 0},
    )

    status = _build_period_average_weight_methodology_status(
        period_methodology_context=period_context,
        average_weight_sum_residual_bp=0,
        timeseries_total_delta_periods=0,
        average_weight_audit_state=audit_state,
        is_promoted=True,
    )

    assert status.status == "PROMOTED"
    assert status.is_cutover_candidate is True
    assert status.is_promoted is True
    assert status.blocker_reason_codes == []
    assert audit_state.cutover_candidate_periods == 1
    assert audit_state.promoted_periods == 1
    assert audit_state.blocked_periods == 0


def test_record_period_timeseries_total_delta_ignores_absent_series():
    audit_state = AverageWeightShadowAuditState()

    delta_periods = _record_period_timeseries_total_delta(
        daily_series=None,
        period_total_contribution=1.25,
        average_weight_audit_state=audit_state,
    )

    assert delta_periods == 0
    assert audit_state.timeseries_total_delta_periods == 0


def test_record_period_timeseries_total_delta_ignores_reconciled_series():
    audit_state = AverageWeightShadowAuditState()

    delta_periods = _record_period_timeseries_total_delta(
        daily_series=[
            DailyContribution(date=pd.Timestamp("2025-01-01").date(), total_contribution=0.75),
            DailyContribution(date=pd.Timestamp("2025-01-02").date(), total_contribution=0.50),
        ],
        period_total_contribution=1.25,
        average_weight_audit_state=audit_state,
    )

    assert delta_periods == 0
    assert audit_state.timeseries_total_delta_periods == 0


def test_record_period_timeseries_total_delta_records_material_drift():
    audit_state = AverageWeightShadowAuditState()

    delta_periods = _record_period_timeseries_total_delta(
        daily_series=[
            DailyContribution(date=pd.Timestamp("2025-01-01").date(), total_contribution=0.75),
            DailyContribution(date=pd.Timestamp("2025-01-02").date(), total_contribution=0.50),
        ],
        period_total_contribution=1.30,
        average_weight_audit_state=audit_state,
    )

    assert delta_periods == 1
    assert audit_state.timeseries_total_delta_periods == 1


def test_contribution_period_helpers_slice_frames_and_extract_reset_dates():
    daily_contributions_df = pd.DataFrame(
        {
            "position_id": ["A", "A", "A"],
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
            ],
            "perf_reset": [0, 1, 0],
        }
    )
    portfolio_results_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01"),
                pd.Timestamp("2025-01-02"),
                pd.Timestamp("2025-01-03"),
            ],
            "perf_reset": [1, 0, 1],
        }
    )

    period_frames = _slice_contribution_period_frames(
        daily_contributions_df=daily_contributions_df,
        portfolio_results_df=portfolio_results_df,
        start_date=pd.Timestamp("2025-01-02").date(),
        end_date=pd.Timestamp("2025-01-03").date(),
    )

    assert period_frames.period_slice_df["position_id"].tolist() == ["A", "A"]
    assert period_frames.period_slice_df is not daily_contributions_df
    assert _extract_reset_dates(period_frames.period_slice_df) == {pd.Timestamp("2025-01-02").date()}
    assert _extract_reset_dates(period_frames.portfolio_period_slice_df) == {pd.Timestamp("2025-01-03").date()}


def test_contribution_period_methodology_context_builds_shadow_and_alignment_evidence():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A", "A"],
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
            ],
            "daily_weight": [0.50, 0.25],
            "perf_reset": [1, 0],
            "bod_cf": [0.0, 0.0],
            "eod_cf": [0.0, 0.0],
        }
    )
    portfolio_period_slice_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
            ],
            "perf_reset": [0, 1],
            "nip": [0, 0],
            "bod_cf": [0.0, 0.0],
            "eod_cf": [0.0, 0.0],
            "begin_mv": [100.0, 100.0],
        }
    )

    context = _build_contribution_period_methodology_context(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=portfolio_period_slice_df,
    )

    assert context.delta_positions == 1
    assert context.max_shadow_delta_bp == 1250
    assert context.position_reset_dates == {pd.Timestamp("2025-01-01").date()}
    assert context.portfolio_reset_dates == {pd.Timestamp("2025-01-02").date()}
    assert context.portfolio_reset_without_position_reset_days == 1
    assert context.position_reset_without_portfolio_reset_days == 1
    assert context.position_flow_balance_counts["position_flow_residual_days"] == 0
    assert context.average_weight_shadow_df.loc[0, "average_weight"] == pytest.approx(0.375)
    assert context.average_weight_shadow_df.loc[0, "reset_aware_average_weight_shadow"] == pytest.approx(0.25)


def test_contribution_reset_helpers_cover_empty_and_zero_paths(mocker):
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
        }
    )

    assert _calculate_reset_relative_day_counts(pd.DataFrame()) == (0, 0)
    assert _calculate_reset_characterization_counts(pd.DataFrame()) == (0, 0, 0, 0, 0, 0, 0)
    assert (
        _calculate_reset_aware_period_portfolio_return(
            request,
            pd.Timestamp("2025-02-01").date(),
            pd.Timestamp("2025-02-02").date(),
            "ITD",
        )
        == 0.0
    )
    assert (
        _calculate_position_total_return_pct(
            request=request,
            position_data=None,
            period_start_date=pd.Timestamp("2025-01-01").date(),
            period_end_date=pd.Timestamp("2025-01-02").date(),
        )
        == 0.0
    )
    assert _count_carino_invalid_domain_days(pd.DataFrame()) == 0
    assert (
        _count_carino_invalid_domain_days(
            pd.DataFrame({PortfolioColumns.DAILY_ROR.value: ["bad", "-100.0", "-101.0", "2.5"]})
        )
        == 2
    )
    diagnostics = _build_portfolio_engine_diagnostics(pd.DataFrame(), pd.Timestamp("2025-01-01").date())
    assert diagnostics.nip_days == 0
    assert diagnostics.reset_days == 0

    mocker.patch("app.services.contribution_returns.run_engine_for_valuation_points", return_value=pd.DataFrame())
    position_data = request.positions_data[0]
    assert (
        _calculate_position_total_return_pct(
            request=request,
            position_data=position_data,
            period_start_date=pd.Timestamp("2025-01-01").date(),
            period_end_date=pd.Timestamp("2025-01-01").date(),
        )
        == 0.0
    )


def test_calculate_reset_aware_average_weight_shadow_ignores_pre_reset_history_and_nip_days():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A", "A", "A", "A"],
            "perf_date": [
                pd.Timestamp("2025-01-01T10:00:00Z"),
                "2025-01-02",
                pd.Timestamp("2025-01-03T10:00:00Z"),
                "2025-01-04",
            ],
            "daily_weight": [0.50, 0.50, 0.30, 0.40],
        }
    )
    portfolio_period_slice_df = pd.DataFrame(
        {
            "perf_date": [
                "2025-01-01",
                pd.Timestamp("2025-01-02T10:00:00Z"),
                "2025-01-03",
                pd.Timestamp("2025-01-04T10:00:00Z"),
            ],
            "perf_reset": [0, 0, 1, 0],
            "nip": [0, 0, 0, 1],
        }
    )

    shadow_df, delta_position_count, max_shadow_delta_bp, sum_shadow_delta_bp = (
        _calculate_reset_aware_average_weight_shadow(
            period_slice_df,
            portfolio_period_slice_df,
        )
    )

    assert delta_position_count == 1
    assert max_shadow_delta_bp == 1250
    assert sum_shadow_delta_bp == 1250
    assert shadow_df.loc[0, "average_weight"] == 0.425
    assert shadow_df.loc[0, "reset_aware_average_weight_shadow"] == 0.3


def test_calculate_reset_aware_average_weight_shadow_matches_simple_mean_when_no_reset_or_nip_adjustment_is_needed():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A", "A"],
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
            ],
            "daily_weight": [0.50, 0.50],
        }
    )
    portfolio_period_slice_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
            ],
            "perf_reset": [0, 0],
            "nip": [0, 0],
        }
    )

    shadow_df, delta_position_count, max_shadow_delta_bp, sum_shadow_delta_bp = (
        _calculate_reset_aware_average_weight_shadow(
            period_slice_df,
            portfolio_period_slice_df,
        )
    )

    assert delta_position_count == 0
    assert max_shadow_delta_bp == 0
    assert sum_shadow_delta_bp == 0
    assert shadow_df.loc[0, "average_weight"] == 0.5
    assert shadow_df.loc[0, "reset_aware_average_weight_shadow"] == 0.5


def test_calculate_reset_aware_average_weight_shadow_covers_empty_missing_column_and_zero_valid_day_paths():
    empty_shadow_df, delta_count, max_bp, sum_bp = _calculate_reset_aware_average_weight_shadow(
        pd.DataFrame(columns=["position_id", "daily_weight"]),
        pd.DataFrame(),
    )
    assert empty_shadow_df.empty
    assert (delta_count, max_bp, sum_bp) == (0, 0, 0)

    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A"],
            "perf_date": [pd.Timestamp("2025-01-01").date()],
            "daily_weight": [0.4],
        }
    )
    missing_column_shadow_df, *_ = _calculate_reset_aware_average_weight_shadow(
        period_slice_df,
        pd.DataFrame({"perf_date": [pd.Timestamp("2025-01-01").date()]}),
    )
    assert missing_column_shadow_df.loc[0, "reset_aware_average_weight_shadow"] == pytest.approx(0.4)

    zero_valid_shadow_df, *_ = _calculate_reset_aware_average_weight_shadow(
        period_slice_df,
        pd.DataFrame(
            {
                "perf_date": [pd.Timestamp("2025-01-01").date()],
                "perf_reset": [0],
                "nip": [1],
            }
        ),
    )
    assert zero_valid_shadow_df.loc[0, "reset_aware_average_weight_shadow"] == 0.0


def test_build_portfolio_engine_diagnostics_maps_reset_and_nip_characterization_from_engine_frame():
    portfolio_results_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
            ],
            "nip": [0, 1, 0],
            "nip_rule_v1_shadow": [0, 1, 0],
            "nip_rule_v2_shadow": [0, 0, 0],
            "perf_reset": [0, 1, 0],
            "nctrl_4": [0, 0, 1],
            "account_reset": [0, 0, 1],
            "sod_reset": [1, 0, 0],
        }
    )

    diagnostics = _build_portfolio_engine_diagnostics(
        portfolio_results_df,
        pd.Timestamp("2025-01-01").date(),
    )

    assert diagnostics.nip_days == 1
    assert diagnostics.nip_rule_delta_days == 1
    assert diagnostics.reset_days == 1
    assert diagnostics.nctrl4_reset_days == 1
    assert diagnostics.nctrl4_exclusive_reset_days == 0
    assert diagnostics.account_reset_shadow_days == 1
    assert diagnostics.sod_reset_shadow_days == 1
    assert diagnostics.shadow_reset_overlap_days == 0
    assert diagnostics.shadow_only_candidate_reset_days == 2
    assert diagnostics.active_reset_with_shadow_days == 0
    assert diagnostics.candidate_canonical_reset_days == 3
    assert diagnostics.reset_delta_days == 2
    assert diagnostics.nip_days_since_last_reset == 1
    assert diagnostics.valid_days_since_last_reset == 1


def test_calculate_grouped_return_reset_alignment_counts_detects_misaligned_reset_dates():
    instruments_df = pd.DataFrame(
        {
            "position_id": ["A", "A"],
            "perf_date": [pd.Timestamp("2025-01-01T10:00:00Z"), "2025-01-03"],
            "perf_reset": [0, 1],
        }
    )
    portfolio_results_df = pd.DataFrame(
        {
            "perf_date": [
                "2025-01-01",
                pd.Timestamp("2025-01-02T10:00:00Z"),
                "2025-01-03",
            ],
            "perf_reset": [0, 1, 0],
        }
    )

    counts = _calculate_grouped_return_reset_alignment_counts(instruments_df, portfolio_results_df)

    assert counts == {
        "portfolio_reset_days": 1,
        "position_reset_days": 1,
        "portfolio_reset_without_position_reset_days": 1,
        "position_reset_without_portfolio_reset_days": 1,
    }


def test_calculate_position_flow_balance_counts_sizes_non_flow_neutral_days():
    instruments_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01T10:00:00Z"),
                "2025-01-01",
                pd.Timestamp("2025-01-02T11:00:00Z"),
            ],
            "bod_cf": [100, -90, 0],
            "eod_cf": [0, 0, 10],
        }
    )
    portfolio_results_df = pd.DataFrame(
        {
            "perf_date": ["2025-01-01", pd.Timestamp("2025-01-02T12:00:00Z")],
            "begin_mv": [1000, 1000],
            "bod_cf": [0, 0],
            "eod_cf": [0, 0],
        }
    )

    counts = _calculate_position_flow_balance_counts(instruments_df, portfolio_results_df)

    assert counts == {
        "position_flow_residual_days": 2,
        "position_flow_residual_max_bp": 100,
        "position_flow_residual_sum_bp": 200,
    }


def test_contribution_series_helpers_build_and_reconcile_daily_outputs():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A", "A", "B", "B"],
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
            ],
            "smoothed_contribution": [0.01, 0.01, 0.02, 0.00],
            "daily_weight": [0.2, 0.8, 0.0, 0.0],
        }
    )
    raw_daily = _build_daily_contribution_series(period_slice_df)
    by_position = _build_position_contribution_series(period_slice_df)
    adjusted_position_series = _build_residual_adjusted_position_timeseries(
        period_slice_df,
        [
            type(
                "PositionContributionLike",
                (),
                {"position_id": "A", "total_contribution": 3.0},
            )(),
            type(
                "PositionContributionLike",
                (),
                {"position_id": "B", "total_contribution": 1.0},
            )(),
        ],
    )
    adjusted_daily = _build_residual_adjusted_daily_contribution_series(adjusted_position_series)

    assert [point.total_contribution for point in raw_daily] == [3.0, 1.0]
    assert by_position[0].position_id == "A"
    assert [point.contribution for point in by_position[0].series] == [1.0, 1.0]
    assert adjusted_position_series[0].position_id == "A"
    assert [point.contribution for point in adjusted_position_series[0].series] == pytest.approx([1.2, 1.8])
    assert [point.contribution for point in adjusted_position_series[1].series] == pytest.approx([1.5, -0.5])
    assert [point.total_contribution for point in adjusted_daily] == pytest.approx([2.7, 1.3])


def test_contribution_series_helpers_sort_and_handle_empty_shapes():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["B", "A", "A"],
            "perf_date": [
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-01").date(),
            ],
            "smoothed_contribution": [0.03, 0.02, 0.01],
        }
    )

    daily_series = _build_daily_contribution_series(period_slice_df)
    position_series = _build_position_contribution_series(period_slice_df)

    assert [point.date for point in daily_series] == [
        pd.Timestamp("2025-01-01").date(),
        pd.Timestamp("2025-01-02").date(),
    ]
    assert [point.total_contribution for point in daily_series] == [1.0, 5.0]
    assert [series.position_id for series in position_series] == ["A", "B"]
    assert [point.date for point in position_series[0].series] == [
        pd.Timestamp("2025-01-01").date(),
        pd.Timestamp("2025-01-02").date(),
    ]
    assert _build_position_contribution_series(pd.DataFrame(columns=["position_id", "perf_date"])) == []


def test_build_position_contributions_sorts_and_truncates_top_n(mocker):
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
        }
    )
    mocker.patch("app.services.contribution_returns.run_engine_for_valuation_points", return_value=pd.DataFrame())

    contributions = build_position_contributions(
        totals_df=pd.DataFrame(
            [
                {"position_id": "A", "total_contribution": 0.01, "average_weight": 0.25},
                {"position_id": "B", "total_contribution": -0.03, "average_weight": 0.75},
            ]
        ),
        request=request,
        period_start_date=pd.Timestamp("2025-01-01").date(),
        period_end_date=pd.Timestamp("2025-01-02").date(),
        average_weight_column="average_weight",
        top_n=1,
    )

    assert len(contributions) == 1
    assert contributions[0].position_id == "B"
    assert contributions[0].total_return == 0.0


def test_build_residual_adjusted_position_totals_allocates_carino_residual_by_selected_weight():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A", "B"],
            "smoothed_contribution": [0.01, 0.02],
            "smoothed_local_contribution": [0.008, 0.018],
        }
    )
    average_weight_df = pd.DataFrame(
        {
            "position_id": ["A", "B"],
            "average_weight": [0.25, 0.75],
            "reset_aware_average_weight_shadow": [0.50, 0.50],
        }
    )

    totals_result = build_residual_adjusted_position_totals(
        period_slice_df=period_slice_df,
        average_weight_df=average_weight_df,
        total_portfolio_return=0.04,
        smoothing_method="CARINO",
        average_weight_columns=["average_weight", "reset_aware_average_weight_shadow"],
        residual_allocation_weight_column="selected_average_weight",
        selected_average_weight_source_column="reset_aware_average_weight_shadow",
    )

    assert totals_result.residual_allocation_applied
    assert totals_result.totals_df["selected_average_weight"].tolist() == [0.50, 0.50]
    assert totals_result.totals_df["total_contribution"].tolist() == pytest.approx([0.015, 0.025])
    assert totals_result.totals_df["fx_contribution"].tolist() == pytest.approx([0.007, 0.007])


def test_residual_adjusted_position_timeseries_handles_missing_targets_and_missing_weight_signal():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A", "A", "B"],
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-01").date(),
            ],
            "smoothed_contribution": [0.01, 0.02, 0.03],
        }
    )

    adjusted_position_series = _build_residual_adjusted_position_timeseries(
        period_slice_df,
        [
            type("PositionContributionLike", (), {"position_id": "A", "total_contribution": 6.0})(),
        ],
    )

    assert [series.position_id for series in adjusted_position_series] == ["A", "B"]
    assert [point.contribution for point in adjusted_position_series[0].series] == pytest.approx([2.5, 3.5])
    assert [point.contribution for point in adjusted_position_series[1].series] == pytest.approx([0.0])
    assert _build_residual_adjusted_position_timeseries(period_slice_df, []) == []


def test_residual_adjusted_series_helpers_handle_empty_inputs():
    assert _build_residual_adjusted_position_timeseries(pd.DataFrame(), []) == []
    assert _build_residual_adjusted_daily_contribution_series([]) == []


def test_average_weight_shadow_helper_classifies_materiality_and_cutover_readiness():
    assert _classify_average_weight_shadow_period(50) == "noise"
    assert _classify_average_weight_shadow_period(250) == "warning"
    assert _classify_average_weight_shadow_period(600) == "material"
    assert _normalize_reset_aware_average_weight_mode("candidate_periods") == "CANDIDATE_PERIODS"
    assert _normalize_reset_aware_average_weight_mode("unknown") == "OFF"
    assert _calculate_promotion_ready_rate_bp(ready_periods=2, material_periods=4) == 5000
    assert _calculate_promotion_ready_rate_bp(ready_periods=0, material_periods=0) == 0
    assert _calculate_average_weight_sum_residual_bp_from_ratio_series(pd.Series([0.95, 0.05])) == 0
    assert _calculate_average_weight_sum_residual_bp_from_ratio_series(pd.Series([0.50, 0.40])) == 1000
    assert _calculate_average_weight_sum_residual_bp_from_ratio_series(pd.Series(dtype=float)) == 0
    assert _calculate_average_weight_sum_residual_bp([]) == 0

    assert _is_average_weight_shadow_cutover_candidate(
        max_shadow_delta_bp=600,
        average_weight_sum_residual_bp=0,
        position_flow_residual_days=0,
        portfolio_reset_without_position_reset_days=0,
        position_reset_without_portfolio_reset_days=0,
        timeseries_total_delta_periods=0,
    )
    assert _classify_average_weight_shadow_cutover_blockers(
        max_shadow_delta_bp=600,
        average_weight_sum_residual_bp=50,
        position_flow_residual_days=1,
        portfolio_reset_without_position_reset_days=1,
        position_reset_without_portfolio_reset_days=0,
        timeseries_total_delta_periods=1,
    ) == {"weight_residual", "flow_balance", "reset_alignment", "timeseries_reconciliation"}
    ready_assessment = _assess_average_weight_shadow_cutover(
        max_shadow_delta_bp=600,
        average_weight_sum_residual_bp=0,
        position_flow_residual_days=0,
        portfolio_reset_without_position_reset_days=0,
        position_reset_without_portfolio_reset_days=0,
        timeseries_total_delta_periods=0,
    )
    blocked_assessment = _assess_average_weight_shadow_cutover(
        max_shadow_delta_bp=600,
        average_weight_sum_residual_bp=50,
        position_flow_residual_days=1,
        portfolio_reset_without_position_reset_days=1,
        position_reset_without_portfolio_reset_days=0,
        timeseries_total_delta_periods=1,
    )
    assert ready_assessment.is_cutover_candidate
    assert ready_assessment.blocker_reason_codes == set()
    assert not blocked_assessment.is_cutover_candidate
    assert blocked_assessment.blocker_reason_codes == {
        "weight_residual",
        "flow_balance",
        "reset_alignment",
        "timeseries_reconciliation",
    }
    assert (
        _classify_average_weight_methodology_status(
            max_shadow_delta_bp=600,
            is_cutover_candidate=False,
            is_promoted=False,
            blocker_reason_codes={"flow_balance"},
        )
        == "BLOCKED"
    )
    assert (
        _classify_average_weight_methodology_status(
            max_shadow_delta_bp=600,
            is_cutover_candidate=True,
            is_promoted=True,
            blocker_reason_codes=set(),
        )
        == "PROMOTED"
    )
    assert (
        _classify_average_weight_methodology_status(
            max_shadow_delta_bp=600,
            is_cutover_candidate=False,
            is_promoted=False,
            blocker_reason_codes=set(),
        )
        == "UNDER_REVIEW"
    )
    assert (
        _classify_average_weight_methodology_status(
            max_shadow_delta_bp=0,
            is_cutover_candidate=False,
            is_promoted=False,
            blocker_reason_codes=set(),
        )
        == "NO_MATERIAL_SHADOW"
    )
    response_status = _build_average_weight_methodology_status(
        max_shadow_delta_bp=600,
        is_cutover_candidate=False,
        is_promoted=False,
        blocker_reason_codes={"timeseries_reconciliation", "flow_balance"},
    )
    assert response_status.status == "BLOCKED"
    assert response_status.is_material_shadow
    assert response_status.blocker_reason_codes == ["flow_balance", "timeseries_reconciliation"]


def test_build_hierarchy_from_adjusted_position_series_handles_empty_and_unclassified_paths():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "currency_mode": "BOTH",
            "hierarchy": ["sector"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
            "emit": {"include_unclassified": False},
        }
    )

    empty_result = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=pd.DataFrame(),
        position_series=[],
        request=request,
    )
    assert empty_result["levels"] == []
    assert empty_result["summary"]["portfolio_contribution"] == 0.0
    assert empty_result["summary"]["coverage_mv_pct"] == 100.0
    assert empty_result["summary"]["local_contribution"] == 0.0
    assert empty_result["summary"]["fx_contribution"] == 0.0

    filtered_result = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=pd.DataFrame(
            {
                "position_id": ["A"],
                "perf_date": [pd.Timestamp("2025-01-01").date()],
                "daily_weight": [0.4],
            }
        ),
        position_series=[
            type(
                "SeriesLike",
                (),
                {
                    "position_id": "A",
                    "series": [
                        type("PointLike", (), {"date": pd.Timestamp("2025-01-01").date(), "contribution": 1.0})()
                    ],
                },
            )()
        ],
        request=request,
    )
    assert filtered_result["levels"] == []


def test_contribution_endpoint_helpersbuild_contribution_execution_windows_and_offload_flags(mocker):
    stateless_request = ContributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
        }
    )
    stateful_request = ContributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-02-15",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    nested_stateless_request = ContributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
                "positions_data": [{"position_id": "A", "valuation_points": []}],
            },
        }
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"CONTRIBUTION_EXECUTOR_POSITION_COUNT": 2, "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30},
        )(),
    )

    assert should_offload_contribution(stateless_request) is True
    assert should_offload_contribution(nested_stateless_request) is False
    assert should_preemptively_offload_stateful_contribution(stateful_request) is True
    assert should_offload_resolved_contribution(2) is True
    assert build_contribution_execution_window(stateless_request)["position_count"] == 2
    assert build_contribution_execution_window(nested_stateless_request)["position_count"] == 1
    assert build_contribution_execution_window(stateful_request)["position_count"] == 0
    assert (
        build_contribution_execution_window(stateful_request, source_request_fingerprint="fp")[
            "source_request_fingerprint"
        ]
        == "fp"
    )
    assert (
        build_resolved_contribution_execution_window(
            stateful_request,
            position_count=5,
            source_request_fingerprint="fp",
        )["position_count"]
        == 5
    )


def test_contribution_endpoint_helpers_buildaccepted_contribution_response():
    calculation_id = uuid4()
    response = accepted_contribution_response(calculation_id)

    assert response.calculation_id == calculation_id
    assert response.poll_path == f"/performance/executions/{calculation_id}"
    assert response.result_path == f"/performance/contribution/results/{calculation_id}"
