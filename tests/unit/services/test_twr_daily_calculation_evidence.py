import pandas as pd

from app.services.twr_service import _build_daily_calculation_evidence
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
    assert evidence.reason_codes == ["FLOW_NEUTRALIZED_DAILY_RETURN"]
    assert evidence.warnings == []


def test_daily_calculation_evidence_gross_excludes_management_fees():
    evidence = _build_daily_calculation_evidence(_row(), metric_basis="GROSS")

    assert evidence.management_fees == 3.0
    assert evidence.performance_pnl == 10.0


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
    assert "BEFORE_EFFECTIVE_PERIOD_START" in evidence.reason_codes
    assert "BEFORE_EFFECTIVE_PERIOD_START" in evidence.warnings


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
