import pandas as pd

from app.api.endpoints.contribution import _as_numeric
from app.services.contribution_service import (
    _build_portfolio_engine_diagnostics,
    _calculate_grouped_return_reset_alignment_counts,
    _calculate_reset_aware_average_weight_shadow,
)


def test_contribution_as_numeric_returns_default_for_non_numeric():
    assert _as_numeric("not-a-number", default=3) == 3


def test_calculate_reset_aware_average_weight_shadow_ignores_pre_reset_history_and_nip_days():
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["A", "A", "A", "A"],
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
                pd.Timestamp("2025-01-04").date(),
            ],
            "daily_weight": [0.50, 0.50, 0.30, 0.40],
        }
    )
    portfolio_period_slice_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
                pd.Timestamp("2025-01-04").date(),
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
            "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-03").date()],
            "perf_reset": [0, 1],
        }
    )
    portfolio_results_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
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
