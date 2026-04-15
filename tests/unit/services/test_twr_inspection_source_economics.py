from datetime import date

from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.services.inspection.source_economics import analyze_source_economics


def test_analyze_source_economics_flags_fee_normalization_gap_and_duplicate_signal():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 12),
        metric_basis="NET",
        report_end_date=date(2026, 3, 12),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 12),
                begin_mv=1200.0,
                end_mv=1190.0,
                bod_cf=0.0,
                eod_cf=-275.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-12",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1190.0",
                "fees": "-275.0",
                "cash_flows": [
                    {"amount": "-275.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED",
        "DUPLICATE_FEE_SOURCE_SIGNAL",
    }
    assert result.evidence_summary["fee_cashflow_date_count"] == 1
    assert result.evidence_summary["fee_normalization_gap_count"] == 1
    assert result.evidence_summary["duplicate_fee_signal_count"] == 1


def test_analyze_source_economics_flags_external_flow_normalization_and_source_conflicts():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 5),
        metric_basis="NET",
        report_end_date=date(2026, 3, 26),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 5),
                begin_mv=1200.0,
                end_mv=1600.0,
                bod_cf=80000.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
            DailyInputData(
                perf_date=date(2026, 3, 26),
                begin_mv=1600.0,
                end_mv=1300.0,
                bod_cf=0.0,
                eod_cf=-50000.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-05",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1600.0",
                "bod_cashflow": "40000.0",
                "cash_flows": [
                    {"amount": "40000.0", "timing": "bod", "cash_flow_type": "external_flow"},
                ],
            },
            {
                "valuation_date": "2026-03-26",
                "beginning_market_value": "1600.0",
                "ending_market_value": "1300.0",
                "eod_cashflow": "-25000.0",
                "cash_flows": [
                    {"amount": "-20000.0", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            },
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
        "DUPLICATE_EXTERNAL_CASHFLOW_SOURCE_SIGNAL",
        "EXTERNAL_CASHFLOW_SOURCE_TOTAL_MISMATCH",
    }
    assert result.evidence_summary["external_cashflow_date_count"] == 2
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 2
    assert result.evidence_summary["duplicate_external_cashflow_signal_count"] == 1
    assert result.evidence_summary["external_cashflow_source_mismatch_count"] == 1


def test_analyze_source_economics_flags_positive_fee_source_signal():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 13),
        metric_basis="NET",
        report_end_date=date(2026, 3, 13),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 13),
                begin_mv=1200.0,
                end_mv=1210.0,
                bod_cf=0.0,
                eod_cf=5.0,
                mgmt_fees=5.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-13",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1210.0",
                "fees": "5.0",
                "cash_flows": [
                    {"amount": "5.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "DUPLICATE_FEE_SOURCE_SIGNAL",
        "POSITIVE_FEE_SOURCE_SIGNAL",
    }
    assert result.evidence_summary["positive_fee_signal_count"] == 1
