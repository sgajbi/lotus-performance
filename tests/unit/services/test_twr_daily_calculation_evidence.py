import pandas as pd
import pytest

from app.services.twr_service import (
    _build_daily_calculation_evidence,
    _calculate_total_return_from_reset_slice,
    _classify_daily_calculation_evidence,
    _daily_calculation_evidence_inputs,
    _iter_frequency_windows,
)
from common.enums import Frequency
from engine.schema import PortfolioColumns


def _row(**overrides):
    base = {
        PortfolioColumns.PERF_DATE.value: "2025-01-02",
        PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value: "2025-01-01",
        PortfolioColumns.BEGIN_MV.value: 1000.0,
        PortfolioColumns.BOD_CF.value: 0.0,
        PortfolioColumns.EOD_CF.value: 0.0,
        PortfolioColumns.MGMT_FEES.value: 3.0,
        PortfolioColumns.END_MV.value: 1010.0,
        PortfolioColumns.DAILY_ROR.value: 1.3,
        PortfolioColumns.PERF_RESET.value: 0,
        PortfolioColumns.NIP.value: 0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_daily_calculation_evidence_net_includes_management_fees():
    evidence = _build_daily_calculation_evidence(_row(), metric_basis="NET")

    assert evidence.performance_pnl == 13.0
    assert evidence.daily_return == 1.3
    assert evidence.status == "calculated"
    assert evidence.signed_adjusted_capital == 1000.0
    assert evidence.linkability_status == "linkable"
    assert evidence.episode_status == "open"
    assert evidence.reason_codes == ["FLOW_NEUTRALIZED_DAILY_RETURN"]
    assert evidence.warnings == []


def test_daily_calculation_evidence_gross_excludes_management_fees():
    evidence = _build_daily_calculation_evidence(_row(), metric_basis="GROSS")

    assert evidence.management_fees == 3.0
    assert evidence.performance_pnl == 10.0


def test_daily_calculation_evidence_inputs_compute_flow_neutralized_values():
    inputs = _daily_calculation_evidence_inputs(_row(), metric_basis="NET")

    assert inputs.begin_mv == 1000.0
    assert inputs.end_mv == 1010.0
    assert inputs.signed_adjusted_capital == 1000.0
    assert inputs.adjusted_capital == 1000.0
    assert inputs.performance_pnl == 13.0
    assert inputs.daily_return == 1.3


def test_classify_daily_calculation_evidence_marks_no_investment_without_reset_boundary():
    row = _row(**{PortfolioColumns.NIP.value: 1})
    inputs = _daily_calculation_evidence_inputs(row, metric_basis="NET")

    classification = _classify_daily_calculation_evidence(row, inputs=inputs)

    assert classification.linkability_status == "not_calculated"
    assert classification.episode_status == "no_investment"
    assert "NO_INVESTMENT_PERIOD" in classification.reason_codes


def test_daily_calculation_evidence_zero_adjusted_capital_is_not_calculated():
    evidence = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.BEGIN_MV.value: 0.0,
                PortfolioColumns.BOD_CF.value: 0.0,
                PortfolioColumns.END_MV.value: 0.0,
                PortfolioColumns.DAILY_ROR.value: 0.0,
            }
        ),
        metric_basis="NET",
    )

    assert evidence.adjusted_capital == 0.0
    assert evidence.status == "not_calculated"
    assert evidence.linkability_status == "not_calculated"
    assert "ZERO_ADJUSTED_CAPITAL" in evidence.reason_codes
    assert "ZERO_ADJUSTED_CAPITAL" in evidence.warnings


def test_daily_calculation_evidence_before_effective_start_is_not_calculated():
    evidence = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.PERF_DATE.value: "2024-12-31",
                PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value: "2025-01-01",
            }
        ),
        metric_basis="NET",
    )

    assert evidence.status == "not_calculated"
    assert evidence.linkability_status == "not_calculated"
    assert evidence.episode_status == "not_in_period"
    assert "BEFORE_EFFECTIVE_PERIOD_START" in evidence.reason_codes
    assert "BEFORE_EFFECTIVE_PERIOD_START" in evidence.warnings


def test_daily_calculation_evidence_normalizes_mixed_date_like_boundaries():
    evidence = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.PERF_DATE.value: pd.Timestamp("2025-01-02T15:00:00Z"),
                PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value: "2025-01-03",
            }
        ),
        metric_basis="NET",
    )

    assert evidence.status == "not_calculated"
    assert evidence.episode_status == "not_in_period"
    assert "BEFORE_EFFECTIVE_PERIOD_START" in evidence.reason_codes


def test_daily_calculation_evidence_records_reset_and_no_investment_reason_codes():
    evidence = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.PERF_RESET.value: 1,
                PortfolioColumns.NIP.value: 1,
            }
        ),
        metric_basis="NET",
    )

    assert "RESET_DAY" in evidence.reason_codes
    assert "NO_INVESTMENT_PERIOD" in evidence.reason_codes
    assert evidence.linkability_status == "reset_boundary"
    assert evidence.episode_status == "reset_boundary"


def test_daily_calculation_evidence_records_negative_and_near_zero_denominator_semantics():
    negative = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.BEGIN_MV.value: -1000.0,
                PortfolioColumns.END_MV.value: -990.0,
                PortfolioColumns.DAILY_ROR.value: 1.3,
            }
        ),
        metric_basis="NET",
    )
    near_zero = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.BEGIN_MV.value: 0.000000001,
                PortfolioColumns.END_MV.value: 0.000000001,
                PortfolioColumns.MGMT_FEES.value: 0.0,
                PortfolioColumns.DAILY_ROR.value: 0.0,
            }
        ),
        metric_basis="NET",
    )

    assert negative.signed_adjusted_capital == -1000.0
    assert negative.adjusted_capital == 1000.0
    assert "NEGATIVE_ADJUSTED_CAPITAL_INPUT" in negative.reason_codes
    assert "NEGATIVE_ADJUSTED_CAPITAL_INPUT" in negative.warnings
    assert near_zero.status == "calculated"
    assert "NEAR_ZERO_ADJUSTED_CAPITAL" in near_zero.reason_codes
    assert "NEAR_ZERO_ADJUSTED_CAPITAL" in near_zero.warnings


def test_daily_calculation_evidence_records_full_loss_and_below_full_loss_linkability():
    full_loss = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.END_MV.value: 0.0,
                PortfolioColumns.DAILY_ROR.value: -100.0,
            }
        ),
        metric_basis="GROSS",
    )
    below_full_loss = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.END_MV.value: -10.0,
                PortfolioColumns.DAILY_ROR.value: -101.0,
            }
        ),
        metric_basis="GROSS",
    )

    assert full_loss.linkability_status == "not_linkable"
    assert "FULL_LOSS_RETURN" in full_loss.reason_codes
    assert "FULL_LOSS_RETURN" in full_loss.warnings
    assert below_full_loss.linkability_status == "not_linkable"
    assert "BELOW_FULL_LOSS_RETURN" in below_full_loss.reason_codes
    assert "BELOW_FULL_LOSS_RETURN" in below_full_loss.warnings


def test_daily_calculation_evidence_records_full_withdrawal_and_refunding_semantics():
    full_withdrawal = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.END_MV.value: 0.0,
                PortfolioColumns.EOD_CF.value: -1000.0,
                PortfolioColumns.DAILY_ROR.value: 100.0,
            }
        ),
        metric_basis="GROSS",
    )
    refunding = _build_daily_calculation_evidence(
        _row(
            **{
                PortfolioColumns.BEGIN_MV.value: 0.0,
                PortfolioColumns.BOD_CF.value: 1000.0,
                PortfolioColumns.END_MV.value: 1000.0,
                PortfolioColumns.DAILY_ROR.value: 0.0,
            }
        ),
        metric_basis="GROSS",
    )

    assert "FULL_WITHDRAWAL_DAY" in full_withdrawal.reason_codes
    assert "REFUNDING_DAY" in refunding.reason_codes


def test_reset_slice_total_return_normalizes_mixed_date_like_boundaries():
    daily_results_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: pd.Timestamp("2025-01-01T21:00:00Z"),
                PortfolioColumns.FINAL_CUM_ROR.value: 10.0,
                PortfolioColumns.DAILY_ROR.value: 10.0,
                PortfolioColumns.PERF_RESET.value: 0,
            },
            {
                PortfolioColumns.PERF_DATE.value: "2025-01-02",
                PortfolioColumns.FINAL_CUM_ROR.value: 21.0,
                PortfolioColumns.DAILY_ROR.value: 10.0,
                PortfolioColumns.PERF_RESET.value: 1,
            },
        ]
    )

    decomposition = _calculate_total_return_from_reset_slice(
        daily_results_df.iloc[[1]].copy(),
        daily_results_df,
    )

    assert decomposition.base == pytest.approx(10.0)
    assert decomposition.local == decomposition.base
    assert decomposition.fx == 0.0


def test_frequency_windows_normalize_mixed_date_like_values_for_resampling():
    period_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: [
                pd.Timestamp("2025-01-03T10:00:00Z"),
                "2025-01-31",
                pd.Timestamp("2025-02-28T10:00:00Z"),
            ],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0, 3.0],
            PortfolioColumns.PERF_RESET.value: [0, 0, 0],
        }
    )

    windows = _iter_frequency_windows(
        period_df,
        date_column=PortfolioColumns.PERF_DATE.value,
        frequency=Frequency.MONTHLY,
    )

    assert [(label, start_date.isoformat(), end_date.isoformat()) for label, start_date, end_date, _ in windows] == [
        ("2025-01", "2025-01-03", "2025-01-31"),
        ("2025-02", "2025-02-28", "2025-02-28"),
    ]
