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


def test_analyze_source_economics_flags_fee_source_total_mismatch():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 14),
        metric_basis="NET",
        report_end_date=date(2026, 3, 14),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 14),
                begin_mv=1210.0,
                end_mv=1198.0,
                bod_cf=0.0,
                eod_cf=-8.0,
                mgmt_fees=-8.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-14",
                "beginning_market_value": "1210.0",
                "ending_market_value": "1198.0",
                "fees": "-10.0",
                "cash_flows": [
                    {"amount": "-8.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"FEE_SOURCE_TOTAL_MISMATCH"}
    assert result.evidence_summary["fee_source_mismatch_count"] == 1


def test_analyze_source_economics_flags_explicit_fee_normalization_mismatch_without_detailed_fee_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 17),
        metric_basis="NET",
        report_end_date=date(2026, 3, 17),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 17),
                begin_mv=1200.0,
                end_mv=1188.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=-8.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-17",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1188.0",
                "fees": "-10.0",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED"}
    assert result.evidence_summary["fee_normalization_gap_count"] == 1


def test_analyze_source_economics_flags_explicit_external_normalization_mismatch_without_detailed_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 18),
        metric_basis="NET",
        report_end_date=date(2026, 3, 18),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 18),
                begin_mv=1200.0,
                end_mv=5188.0,
                bod_cf=3000.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-18",
                "beginning_market_value": "1200.0",
                "ending_market_value": "5188.0",
                "bod_cashflow": "4000.0",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH"}
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 1


def test_analyze_source_economics_flags_external_timing_bucket_contradiction():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 19),
        metric_basis="NET",
        report_end_date=date(2026, 3, 19),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 19),
                begin_mv=5188.0,
                end_mv=3188.0,
                bod_cf=0.0,
                eod_cf=-2000.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-19",
                "beginning_market_value": "5188.0",
                "ending_market_value": "3188.0",
                "bod_cashflow": "-2000.0",
                "cash_flows": [
                    {"amount": "-2000.0", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
        "EXTERNAL_CASHFLOW_TIMING_BUCKET_CONTRADICTION",
    }
    assert result.evidence_summary["external_cashflow_timing_contradiction_count"] == 1


def test_analyze_source_economics_flags_invalid_cashflow_amount_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3188.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3188.0",
                "cash_flows": [
                    {"amount": "n/a", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_CASHFLOW_AMOUNT_PRESENT"}
    assert result.evidence_summary["invalid_cashflow_amount_date_count"] == 1
    assert result.artifact_payload["invalid_cashflow_amount_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [{"timing": "eod", "amount": "n/a", "cash_flow_type": "external_flow"}],
        }
    ]


def test_analyze_source_economics_flags_invalid_explicit_source_amounts():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3188.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3188.0",
                "management_fees": "oops",
                "ending_cash_flow": "bad",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_EXPLICIT_SOURCE_AMOUNT_PRESENT"}
    assert result.evidence_summary["invalid_explicit_source_amount_date_count"] == 1
    assert result.artifact_payload["invalid_explicit_source_amount_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [
                {"field": "ending_cash_flow", "semantic": "eod_cashflow_total", "raw_value": "bad"},
                {"field": "management_fees", "semantic": "fee_total", "raw_value": "oops"},
            ],
        }
    ]


def test_analyze_source_economics_flags_noncanonical_cashflow_type_labels():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3191.0,
                bod_cf=0.0,
                eod_cf=3.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3191.0",
                "cash_flows": [
                    {"amount": "3.0", "timing": "eod", "cash_flow_type": "dividend"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"NONCANONICAL_CASHFLOW_TYPE_PRESENT"}
    assert result.evidence_summary["noncanonical_cashflow_type_date_count"] == 1


def test_analyze_source_economics_flags_missing_cashflow_type_labels():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3193.0,
                bod_cf=0.0,
                eod_cf=5.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3193.0",
                "cash_flows": [
                    {"amount": "5.0", "timing": "eod"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"MISSING_CASHFLOW_TYPE_PRESENT"}
    assert result.evidence_summary["missing_cashflow_type_date_count"] == 1
    assert result.artifact_payload["missing_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [{"timing": "eod", "amount": 5.0}],
        }
    ]
    assert result.artifact_payload["missing_cashflow_type_date_count"] == 1


def test_analyze_source_economics_treats_blank_cashflow_type_as_missing_label():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 22),
        metric_basis="NET",
        report_end_date=date(2026, 3, 22),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 22),
                begin_mv=3193.0,
                end_mv=3197.0,
                bod_cf=0.0,
                eod_cf=4.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-22",
                "beginning_market_value": "3193.0",
                "ending_market_value": "3197.0",
                "cash_flows": [
                    {"amount": "4.0", "timing": "eod", "cash_flow_type": "   "},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"MISSING_CASHFLOW_TYPE_PRESENT"}
    assert result.evidence_summary["missing_cashflow_type_date_count"] == 1
    assert result.evidence_summary["noncanonical_cashflow_type_date_count"] == 0
    assert result.artifact_payload["missing_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-22",
            "rows": [{"timing": "eod", "amount": 4.0}],
        }
    ]
    assert result.artifact_payload["noncanonical_cashflow_types"] == []


def test_analyze_source_economics_flags_invalid_cashflow_timing_labels():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 23),
        metric_basis="NET",
        report_end_date=date(2026, 3, 23),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 23),
                begin_mv=3197.0,
                end_mv=3201.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-23",
                "beginning_market_value": "3197.0",
                "ending_market_value": "3201.0",
                "cash_flows": [
                    {"amount": "4.0", "timing": "intraday", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_CASHFLOW_TIMING_PRESENT"}
    assert result.evidence_summary["invalid_cashflow_timing_date_count"] == 1
    assert result.evidence_summary["missing_cashflow_type_date_count"] == 0
    assert result.artifact_payload["invalid_cashflow_timing_samples"] == [
        {
            "valuation_date": "2026-03-23",
            "rows": [{"timing": "intraday", "amount": 4.0, "cash_flow_type": "external_flow"}],
        }
    ]
    assert result.artifact_payload["invalid_cashflow_timing_date_count"] == 1


def test_analyze_source_economics_artifact_captures_timing_and_taxonomy_samples():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 21),
        metric_basis="NET",
        report_end_date=date(2026, 3, 21),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 21),
                begin_mv=3191.0,
                end_mv=1191.0,
                bod_cf=0.0,
                eod_cf=-2000.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-21",
                "beginning_market_value": "3191.0",
                "ending_market_value": "1191.0",
                "bod_cashflow": "-2000.0",
                "cash_flows": [
                    {"amount": "-2000.0", "timing": "eod", "cash_flow_type": "dividend"},
                ],
            }
        ],
    )

    assert result.artifact_payload["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert result.artifact_payload["portfolio_observation_count"] == 1
    assert result.artifact_payload["external_cashflow_date_count"] == 1
    assert result.artifact_payload["external_cashflow_dates"] == ["2026-03-21"]
    assert result.artifact_payload["external_cashflow_timing_contradiction_count"] == 1
    assert result.artifact_payload["external_cashflow_timing_contradiction_samples"] == [
        {
            "valuation_date": "2026-03-21",
            "explicit_timing": "bod",
            "opposite_detailed_timing": "eod",
            "explicit_cashflow_amount": -2000.0,
            "opposite_detailed_cashflow_amount": -2000.0,
        }
    ]
    assert result.artifact_payload["noncanonical_cashflow_type_date_count"] == 1
    assert result.artifact_payload["noncanonical_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-21",
            "cash_flow_types": ["dividend"],
        }
    ]
    assert result.artifact_payload["missing_cashflow_type_date_count"] == 0
    assert result.artifact_payload["noncanonical_cashflow_types"] == ["dividend"]
