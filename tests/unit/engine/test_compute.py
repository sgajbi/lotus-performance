# tests/unit/engine/test_compute.py
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from engine.compute import _build_engine_diagnostics, _build_reset_events, run_calculations
from engine.config import EngineConfig, PeriodType, PrecisionMode
from engine.diagnostics import EngineDiagnostics
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from engine.schema import PortfolioColumns


def _build_engine_input(*rows: dict[str, object]) -> pd.DataFrame:
    """Builds a compact engine input frame for portfolio-story characterization tests."""
    return pd.DataFrame(rows)


def test_run_calculations_decimal_strict_mode():
    """
    Tests that when PrecisionMode.DECIMAL_STRICT is used, the calculations
    are performed using Decimal objects, not floats.
    """
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
        precision_mode=PrecisionMode.DECIMAL_STRICT,
    )

    data = {
        PortfolioColumns.DAY.value: [1],
        PortfolioColumns.PERF_DATE.value: [pd.to_datetime("2025-01-01")],
        PortfolioColumns.BEGIN_MV.value: [Decimal("1000.0")],
        PortfolioColumns.BOD_CF.value: [Decimal("0.0")],
        PortfolioColumns.EOD_CF.value: [Decimal("0.0")],
        PortfolioColumns.MGMT_FEES.value: [Decimal("-1.23")],
        PortfolioColumns.END_MV.value: [Decimal("1008.77")],
    }
    df = pd.DataFrame(data)

    result_df, _ = run_calculations(df.copy(), config)

    assert isinstance(result_df[PortfolioColumns.DAILY_ROR.value].iloc[0], Decimal)
    expected_ror = Decimal("0.754")
    assert result_df[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(expected_ror)


def test_run_calculations_empty_dataframe():
    """Tests that the engine handles an empty DataFrame without errors."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    empty_df = pd.DataFrame()
    result, diagnostics = run_calculations(empty_df, config)
    assert result.empty
    assert diagnostics == EngineDiagnostics()


def test_run_calculations_float_mode_rounding():
    """Tests that rounding is applied correctly in the default FLOAT64 mode."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    data = {
        PortfolioColumns.PERF_DATE.value: [date(2025, 1, 1)],
        PortfolioColumns.BEGIN_MV.value: [100.0],
        PortfolioColumns.BOD_CF.value: [0.0],
        PortfolioColumns.EOD_CF.value: [0.0],
        PortfolioColumns.MGMT_FEES.value: [0.0],
        PortfolioColumns.END_MV.value: [101.12345678912345],
    }
    df = pd.DataFrame(data)
    result_df, _ = run_calculations(df, config)
    assert result_df[PortfolioColumns.DAILY_ROR.value].iloc[0] == 1.1235


def test_run_calculations_does_not_mutate_caller_dataframe():
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: [date(2025, 1, 1)],
            PortfolioColumns.BEGIN_MV.value: [100.0],
            PortfolioColumns.BOD_CF.value: [0.0],
            PortfolioColumns.EOD_CF.value: [0.0],
            PortfolioColumns.MGMT_FEES.value: [0.0],
            PortfolioColumns.END_MV.value: [101.0],
        }
    )
    original = df.copy(deep=True)

    result_df, _ = run_calculations(df, config)

    assert PortfolioColumns.DAILY_ROR.value in result_df.columns
    pd.testing.assert_frame_equal(df, original)


def test_run_calculations_invalid_date_input():
    """Tests that an invalid date format raises the correct exception."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    data = {
        PortfolioColumns.PERF_DATE.value: ["2025-01-01", "not-a-date"],
        PortfolioColumns.BEGIN_MV.value: [100.0, 100.0],
    }
    df = pd.DataFrame(data)
    with pytest.raises(InvalidEngineInputError, match="One or more 'perf_date' values are invalid or missing."):
        run_calculations(df, config)


def test_run_calculations_unexpected_exception_handling(mocker):
    """Tests that a generic exception during calculation is wrapped and re-raised."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    data = {
        PortfolioColumns.PERF_DATE.value: ["2025-01-01"],
        PortfolioColumns.BEGIN_MV.value: [100.0],
    }
    df = pd.DataFrame(data)
    mocker.patch("engine.compute.calculate_daily_ror", side_effect=Exception("Unexpected boom!"))

    with pytest.raises(EngineCalculationError, match="Engine calculation failed unexpectedly: Unexpected boom!"):
        run_calculations(df, config)


def test_run_calculations_general_exception_handling():
    """Tests that an invalid input type raises an InvalidEngineInputError."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    bad_df = {"not_a": "dataframe"}

    with pytest.raises(InvalidEngineInputError) as exc_info:
        run_calculations(bad_df, config)

    assert "Input must be a pandas DataFrame" in exc_info.value.message


def test_run_calculations_emits_all_reset_reason_codes(mocker):
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: [date(2025, 1, 1)],
            PortfolioColumns.BEGIN_MV.value: [100.0],
            PortfolioColumns.BOD_CF.value: [0.0],
            PortfolioColumns.EOD_CF.value: [0.0],
            PortfolioColumns.MGMT_FEES.value: [0.0],
            PortfolioColumns.END_MV.value: [100.0],
        }
    )

    mocker.patch(
        "engine.compute.calculate_daily_ror", return_value=pd.DataFrame({PortfolioColumns.DAILY_ROR.value: [0.0]})
    )
    mocker.patch("engine.compute.calculate_sign", return_value=pd.Series([1]))
    mocker.patch("engine.compute.calculate_nip", return_value=pd.Series([0]))

    def _mock_cumulative(df_input, _config):  # noqa: ARG001
        df_input[PortfolioColumns.PERF_RESET.value] = 1
        df_input[PortfolioColumns.ACCOUNT_RESET.value] = 1
        df_input[PortfolioColumns.SOD_RESET.value] = 1
        df_input[PortfolioColumns.NCTRL_1.value] = 0
        df_input[PortfolioColumns.NCTRL_2.value] = 1
        df_input[PortfolioColumns.NCTRL_3.value] = 1
        df_input[PortfolioColumns.NCTRL_4.value] = 1
        df_input[PortfolioColumns.FINAL_CUM_ROR.value] = 0.0
        return df_input

    mocker.patch("engine.compute.calculate_cumulative_ror", side_effect=_mock_cumulative)

    _, diagnostics = run_calculations(df, config)
    assert diagnostics.resets
    assert "NCTRL_2" in diagnostics.resets[0].reason
    assert "NCTRL_3" in diagnostics.resets[0].reason
    assert "NCTRL_4" in diagnostics.resets[0].reason


def test_engine_reset_events_preserve_active_reason_codes():
    working_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")],
            PortfolioColumns.PERF_RESET.value: [1, 1],
            PortfolioColumns.NCTRL_1.value: [0, 0],
            PortfolioColumns.NCTRL_2.value: [1, 0],
            PortfolioColumns.NCTRL_3.value: [0, 1],
            PortfolioColumns.NCTRL_4.value: [0, 1],
        }
    )

    reset_events = _build_reset_events(working_df)

    assert [event.date.isoformat() for event in reset_events] == ["2025-01-02", "2025-01-03"]
    assert [event.reason for event in reset_events] == ["NCTRL_2", "NCTRL_3,NCTRL_4"]
    assert [event.impacted_rows for event in reset_events] == [1, 1]


def test_engine_diagnostics_helper_preserves_policy_and_methodology_samples():
    working_df = pd.DataFrame(
        {
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value: [
                pd.Timestamp("2025-01-01"),
                pd.Timestamp("2025-01-01"),
            ]
        }
    )
    final_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: [date(2025, 1, 1), date(2025, 1, 2)],
            PortfolioColumns.NIP.value: [0, 1],
            PortfolioColumns.PERF_RESET.value: [0, 1],
            PortfolioColumns.NCTRL_4.value: [0, 1],
            PortfolioColumns.ACCOUNT_RESET.value: [0, 0],
            PortfolioColumns.SOD_RESET.value: [0, 1],
            PortfolioColumns.SIGN.value: [1, 1],
            "initial_sign_shadow": [1, 1],
            "nip_rule_v1_shadow": [0, 1],
            "nip_rule_v2_shadow": [0, 0],
        }
    )
    policy_diagnostics = EngineDiagnostics(notes=["Applied overrides from the data_policy request."])
    reset_events = _build_reset_events(
        final_df[[PortfolioColumns.PERF_DATE.value, PortfolioColumns.PERF_RESET.value, PortfolioColumns.NCTRL_4.value]]
        .assign(**{PortfolioColumns.PERF_DATE.value: [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02")]})
        .copy()
    )

    diagnostics = _build_engine_diagnostics(
        working_df=working_df,
        final_df=final_df,
        policy_diagnostics=policy_diagnostics,
        reset_events=reset_events,
    )

    assert diagnostics.nip_days == 1
    assert diagnostics.nip_rule_delta_days == 1
    assert diagnostics.reset_days == 1
    assert diagnostics.effective_period_start == date(2025, 1, 1)
    assert diagnostics.notes == ["Applied overrides from the data_policy request."]
    assert diagnostics.resets == reset_events
    assert diagnostics.samples.methodology_shadows


def test_run_calculations_emits_methodology_shadow_diagnostics():
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 3),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)],
            PortfolioColumns.BEGIN_MV.value: [0.0, 100.0, 0.0],
            PortfolioColumns.BOD_CF.value: [0.0, 0.0, 1.0],
            PortfolioColumns.EOD_CF.value: [0.0, 0.0, -1.0],
            PortfolioColumns.MGMT_FEES.value: [0.0, 0.0, 0.0],
            PortfolioColumns.END_MV.value: [0.0, 110.0, 0.0],
            PortfolioColumns.ACCOUNT_PERFORMANCE_RESET.value: [0.0, 1.0, 0.0],
        }
    )

    _, diagnostics = run_calculations(df, config)

    assert diagnostics.nip_rule_delta_days == 1
    assert diagnostics.nip_days_since_last_reset >= 0
    assert diagnostics.valid_days_since_last_reset >= 0
    assert diagnostics.samples.methodology_shadows
    assert any(sample.account_reset_shadow == 1 for sample in diagnostics.samples.methodology_shadows)
    assert any(sample.nip_rule_v1 != sample.nip_rule_v2 for sample in diagnostics.samples.methodology_shadows)


def test_run_calculations_emits_account_and_sod_reset_shadows_without_changing_active_perf_reset():
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 3),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)],
            PortfolioColumns.BEGIN_MV.value: [100.0, 100.0, 100.0],
            PortfolioColumns.BOD_CF.value: [0.0, 10.0, 25.0],
            PortfolioColumns.EOD_CF.value: [0.0, 0.0, 0.0],
            PortfolioColumns.MGMT_FEES.value: [0.0, 0.0, 0.0],
            PortfolioColumns.END_MV.value: [100.0, 100.0, 100.0],
            PortfolioColumns.ACCOUNT_PERFORMANCE_RESET.value: [0.0, 0.0, 1.0],
        }
    )

    result_df, diagnostics = run_calculations(df, config)

    assert result_df[PortfolioColumns.PERF_RESET.value].iloc[2] == 0
    assert result_df[PortfolioColumns.ACCOUNT_RESET.value].iloc[2] == 1
    assert result_df[PortfolioColumns.SOD_RESET.value].iloc[1] == 1
    assert diagnostics.nctrl4_reset_days == 0
    assert diagnostics.nctrl4_exclusive_reset_days == 0
    assert diagnostics.account_reset_shadow_days == 1
    assert diagnostics.sod_reset_shadow_days == 2
    assert diagnostics.shadow_reset_overlap_days == 0
    assert diagnostics.shadow_only_candidate_reset_days == 3
    assert diagnostics.active_reset_with_shadow_days == 0
    assert diagnostics.candidate_canonical_reset_days == 3
    assert diagnostics.reset_delta_days == 3
    assert any(sample.account_reset_shadow == 1 for sample in diagnostics.samples.methodology_shadows)
    assert any(sample.sod_reset_shadow == 1 for sample in diagnostics.samples.methodology_shadows)
    assert any(
        sample.candidate_canonical_perf_reset == 1 and sample.active_perf_reset == 0
        for sample in diagnostics.samples.methodology_shadows
    )


def test_run_calculations_treats_ordinary_subscription_as_continuous_compounding():
    """Ordinary subscriptions into a healthy portfolio should not break geometric linking."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 3),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = _build_engine_input(
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 100.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 101.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: 101.0,
            PortfolioColumns.BOD_CF.value: 25.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 127.26,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 3),
            PortfolioColumns.BEGIN_MV.value: 127.26,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 128.5326,
        },
    )

    result_df, diagnostics = run_calculations(df, config)

    assert int(result_df[PortfolioColumns.PERF_RESET.value].sum()) == 0
    assert diagnostics.reset_days == 0
    assert diagnostics.candidate_canonical_reset_days == 0
    assert diagnostics.reset_delta_days == 0
    assert all(sample.active_perf_reset == 0 for sample in diagnostics.samples.methodology_shadows)
    assert all(sample.candidate_canonical_perf_reset == 0 for sample in diagnostics.samples.methodology_shadows)


def test_run_calculations_treats_fee_only_day_as_continuous_compounding():
    """Management fees reduce return but should not create a new performance episode by themselves."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 3),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = _build_engine_input(
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 1000.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 1010.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: 1010.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: -5.0,
            PortfolioColumns.END_MV.value: 1015.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 3),
            PortfolioColumns.BEGIN_MV.value: 1015.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 1020.0,
        },
    )

    result_df, diagnostics = run_calculations(df, config)

    assert int(result_df[PortfolioColumns.PERF_RESET.value].sum()) == 0
    assert diagnostics.reset_days == 0
    assert diagnostics.candidate_canonical_reset_days == 0
    assert diagnostics.reset_delta_days == 0


def test_run_calculations_counts_legacy_offsetting_cashflow_days_as_nip_rule_deltas_only():
    """Legacy offsetting-flow NIP cases should stay visible while the canonical NIP rule is undecided."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = _build_engine_input(
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 0.0,
            PortfolioColumns.BOD_CF.value: 1.0,
            PortfolioColumns.EOD_CF.value: -1.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 0.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: 100.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 101.0,
        },
    )

    result_df, diagnostics = run_calculations(df, config)

    assert diagnostics.nip_rule_delta_days == 1
    assert result_df[PortfolioColumns.NIP.value].tolist() == [1, 0]
    assert diagnostics.samples.methodology_shadows[0].nip_rule_v1 == 1
    assert diagnostics.samples.methodology_shadows[0].nip_rule_v2 == 0


def test_run_calculations_counts_reset_relative_valid_days_from_last_active_reset_only():
    """Reset-relative day counts should ignore pre-reset history when a new performance episode begins."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 4),
        metric_basis="GROSS",
        period_type=PeriodType.ITD,
    )
    df = _build_engine_input(
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 1000.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 500.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: 500.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: -50.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 3),
            PortfolioColumns.BEGIN_MV.value: -50.0,
            PortfolioColumns.BOD_CF.value: 1000.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 1050.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 4),
            PortfolioColumns.BEGIN_MV.value: 1050.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 1155.0,
        },
    )

    _, diagnostics = run_calculations(df, config)

    assert diagnostics.nip_days_since_last_reset == 0
    assert diagnostics.valid_days_since_last_reset == 2


def test_run_calculations_keeps_shadow_account_reset_out_of_active_reset_relative_valid_day_count():
    """Active reset-relative day counts should not jump to a shadow-only account reset boundary yet."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 4),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    df = _build_engine_input(
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 100.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 100.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: 100.0,
            PortfolioColumns.BOD_CF.value: 10.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 100.0,
            PortfolioColumns.ACCOUNT_PERFORMANCE_RESET.value: 1.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 3),
            PortfolioColumns.BEGIN_MV.value: 0.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 0.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 4),
            PortfolioColumns.BEGIN_MV.value: 100.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 101.0,
        },
    )

    _, diagnostics = run_calculations(df, config)

    assert diagnostics.nip_days_since_last_reset == 1
    assert diagnostics.valid_days_since_last_reset == 3


def test_run_calculations_characterizes_liquidation_and_recapitalization_as_a_new_episode():
    """A wipeout followed by recapitalization is the clearest case for a reset boundary."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 4),
        metric_basis="GROSS",
        period_type=PeriodType.ITD,
    )
    df = _build_engine_input(
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 1000.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 500.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: 500.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: -50.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 3),
            PortfolioColumns.BEGIN_MV.value: -50.0,
            PortfolioColumns.BOD_CF.value: 1000.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 1050.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 4),
            PortfolioColumns.BEGIN_MV.value: 1050.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 1155.0,
        },
    )

    _, diagnostics = run_calculations(df, config)

    reset_reasons_by_date = {event.date.isoformat(): event.reason for event in diagnostics.resets}

    assert diagnostics.reset_days == 2
    assert diagnostics.nctrl4_reset_days == 1
    assert diagnostics.nctrl4_exclusive_reset_days == 1
    assert diagnostics.account_reset_shadow_days == 0
    assert diagnostics.sod_reset_shadow_days == 1
    assert diagnostics.shadow_reset_overlap_days == 0
    assert diagnostics.shadow_only_candidate_reset_days == 0
    assert diagnostics.active_reset_with_shadow_days == 1
    assert "NCTRL_1" in reset_reasons_by_date["2025-01-02"]
    assert "NCTRL_4" in reset_reasons_by_date["2025-01-03"]
    assert any(sample.active_perf_reset == 1 for sample in diagnostics.samples.methodology_shadows)


def test_run_calculations_characterizes_when_active_and_shadow_reset_reasons_describe_the_same_boundary():
    """The collapse day can reset actively while also carrying shadow pressure from the recapitalizing next open."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        metric_basis="GROSS",
        period_type=PeriodType.ITD,
    )
    df = _build_engine_input(
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 1000.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: -50.0,
        },
        {
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: -50.0,
            PortfolioColumns.BOD_CF.value: 1000.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
            PortfolioColumns.END_MV.value: 1050.0,
        },
    )

    _, diagnostics = run_calculations(df, config)

    assert diagnostics.reset_days == 2
    assert diagnostics.nctrl4_reset_days == 1
    assert diagnostics.nctrl4_exclusive_reset_days == 1
    assert diagnostics.sod_reset_shadow_days == 1
    assert diagnostics.shadow_only_candidate_reset_days == 0
    assert diagnostics.active_reset_with_shadow_days == 1
