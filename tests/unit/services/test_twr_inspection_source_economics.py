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

