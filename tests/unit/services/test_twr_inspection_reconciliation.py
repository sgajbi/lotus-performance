from datetime import date
from decimal import Decimal

from app.models.inspection_requests import TWRInspectionProfile
from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.services.inspection import reconciliation
from app.services.inspection.reconciliation import analyze_portfolio_position_reconciliation


def test_analyze_portfolio_position_reconciliation_flags_mixed_epochs_and_gap():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 2, 28),
        metric_basis="NET",
        report_end_date=date(2026, 3, 26),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 2, 28), begin_mv=1200.0, end_mv=1301.904397290752),
            DailyInputData(perf_date=date(2026, 3, 26), begin_mv=1280.0, end_mv=1323.10366113306),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {
                "valuation_date": "2026-02-28",
                "position_id": "SEC_1",
                "valuation_epoch": 1,
                "ending_market_value_portfolio_currency": "600.0",
            },
            {
                "valuation_date": "2026-02-28",
                "position_id": "SEC_1",
                "valuation_epoch": 14,
                "ending_market_value_portfolio_currency": "630.0",
            },
            {
                "valuation_date": "2026-02-28",
                "position_id": "SEC_2",
                "valuation_epoch": 4,
                "ending_market_value_portfolio_currency": "636.641804",
            },
            {
                "valuation_date": "2026-03-26",
                "position_id": "SEC_1",
                "valuation_epoch": 8,
                "ending_market_value_portfolio_currency": "640.0",
            },
            {
                "valuation_date": "2026-03-26",
                "position_id": "SEC_2",
                "valuation_epoch": 8,
                "ending_market_value_portfolio_currency": "646.91398",
            },
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "MIXED_POSITION_EPOCH_SNAPSHOT",
        "PORTFOLIO_POSITION_RECONCILIATION_GAP",
    }
    assert result.evidence_summary["mixed_epoch_date_count"] == 1
    assert result.evidence_summary["reconciliation_gap_date_count"] == 2
    assert Decimal(str(result.evidence_summary["reconciliation_max_gap_amount"])) > Decimal("30")


def test_analyze_portfolio_position_reconciliation_accepts_coherent_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 1, 1),
        metric_basis="NET",
        report_end_date=date(2026, 1, 2),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 1, 1), begin_mv=1000.0, end_mv=1010.0),
            DailyInputData(perf_date=date(2026, 1, 2), begin_mv=1010.0, end_mv=1020.1),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
        position_rows=[
            {
                "valuation_date": "2026-01-01",
                "position_id": "SEC_1",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "606.0",
            },
            {
                "valuation_date": "2026-01-01",
                "position_id": "SEC_2",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "404.0",
            },
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_1",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "612.06",
            },
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_2",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "408.04",
            },
        ],
    )

    assert result.findings == []
    assert result.evidence_summary["mixed_epoch_date_count"] == 0
    assert result.evidence_summary["reconciliation_gap_date_count"] == 0
    assert result.evidence_summary["position_continuity_gap_count"] == 0


def test_analyze_portfolio_position_reconciliation_flags_unexplained_position_begin_carry_break():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2025, 4, 25),
        metric_basis="NET",
        report_end_date=date(2025, 4, 26),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2025, 4, 25), begin_mv=87000.0, end_mv=87129.93),
            DailyInputData(perf_date=date(2025, 4, 26), begin_mv=0.0, end_mv=87800.0),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {
                "valuation_date": "2025-04-25",
                "position_id": "FO_EQ_SAP_DE",
                "valuation_epoch": 1,
                "beginning_market_value_portfolio_currency": "87000.00",
                "ending_market_value_portfolio_currency": "87129.93",
            },
            {
                "valuation_date": "2025-04-26",
                "position_id": "FO_EQ_SAP_DE",
                "valuation_epoch": 1,
                "beginning_market_value_portfolio_currency": "0.00",
                "ending_market_value_portfolio_currency": "87800.00",
            },
        ],
    )

    assert {finding.code for finding in result.findings} == {"POSITION_BEGIN_VALUE_CARRY_FORWARD_BREAK"}
    assert result.evidence_summary["position_continuity_gap_count"] == 1
    assert result.artifact_payload["position_continuity_gap_samples"] == [
        {
            "position_id": "FO_EQ_SAP_DE",
            "previous_valuation_date": "2025-04-25",
            "valuation_date": "2025-04-26",
            "previous_end_value_field": "ending_market_value_portfolio_currency",
            "current_begin_value_field": "beginning_market_value_portfolio_currency",
            "previous_end_value": "87129.93",
            "current_begin_value": "0.00",
            "gap_amount": "-87129.93",
            "gap_pct_of_previous_end": -100.0,
        }
    ]


def test_analyze_portfolio_position_reconciliation_does_not_flag_activity_explained_begin_change():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2025, 5, 18),
        metric_basis="NET",
        report_end_date=date(2025, 5, 19),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2025, 5, 18), begin_mv=1000.0, end_mv=1000.0),
            DailyInputData(perf_date=date(2025, 5, 19), begin_mv=5000.0, end_mv=5100.0, bod_cf=4000.0),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {
                "valuation_date": "2025-05-18",
                "position_id": "FO_FUND_NEW",
                "valuation_epoch": 1,
                "beginning_market_value_portfolio_currency": "1000.00",
                "ending_market_value_portfolio_currency": "1000.00",
            },
            {
                "valuation_date": "2025-05-19",
                "position_id": "FO_FUND_NEW",
                "valuation_epoch": 1,
                "beginning_market_value_portfolio_currency": "5000.00",
                "ending_market_value_portfolio_currency": "5100.00",
                "internal_trade_flow": "4000.00",
            },
        ],
    )

    assert "POSITION_BEGIN_VALUE_CARRY_FORWARD_BREAK" not in {finding.code for finding in result.findings}
    assert result.evidence_summary["position_continuity_gap_count"] == 0


def test_analyze_portfolio_position_reconciliation_uses_position_currency_for_continuity():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2025, 4, 19),
        metric_basis="NET",
        report_end_date=date(2025, 4, 21),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2025, 4, 19), begin_mv=359876.765, end_mv=359876.765),
            DailyInputData(perf_date=date(2025, 4, 21), begin_mv=359938.74, end_mv=271241.238912),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {
                "valuation_date": "2025-04-19",
                "position_id": "PB_SG_GLOBAL_BAL_001:CASH_EUR_BOOK_OPERATING",
                "valuation_epoch": 1,
                "beginning_market_value_position_currency": "335000.00",
                "ending_market_value_position_currency": "335000.00",
                "beginning_market_value_portfolio_currency": "359876.765",
                "ending_market_value_portfolio_currency": "359876.765",
            },
            {
                "valuation_date": "2025-04-21",
                "position_id": "PB_SG_GLOBAL_BAL_001:CASH_EUR_BOOK_OPERATING",
                "valuation_epoch": 1,
                "beginning_market_value_position_currency": "335000.00",
                "ending_market_value_position_currency": "252448.00",
                "beginning_market_value_portfolio_currency": "359938.74",
                "ending_market_value_portfolio_currency": "271241.238912",
            },
        ],
    )

    assert "POSITION_BEGIN_VALUE_CARRY_FORWARD_BREAK" not in {finding.code for finding in result.findings}
    assert result.evidence_summary["position_continuity_gap_count"] == 0


def test_reconciliation_handles_malformed_position_payload_edges():
    rows = reconciliation._position_rows_from_payload({"rows": {"not": "a-list"}})
    assert rows == []

    result = analyze_portfolio_position_reconciliation(
        performance_request=PerformanceRequest(
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            performance_start_date=date(2026, 1, 1),
            metric_basis="NET",
            report_end_date=date(2026, 1, 3),
            analyses=[Analysis(period="YTD", frequencies=["daily"])],
            valuation_points=[
                DailyInputData(perf_date=date(2026, 1, 1), begin_mv=1000.0, end_mv=1000.0),
                DailyInputData(perf_date=date(2026, 1, 2), begin_mv=1000.0, end_mv=1000.0),
                DailyInputData(perf_date=date(2026, 1, 3), begin_mv=1000.0, end_mv=1000.0),
            ],
        ),
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {"valuation_date": None, "position_id": "IGNORED", "ending_market_value_portfolio_currency": "10"},
            {"valuation_date": "2026-01-01", "position_id": "SEC_1", "snapshot_epoch": "bad"},
            {
                "valuation_date": "2026-01-01",
                "position_id": "SEC_1",
                "valuation_epoch": 1,
                "ending_market_value_reporting_currency": "1000.00",
            },
            {
                "valuation_date": "2026-01-01",
                "position_id": "SEC_1",
                "valuation_epoch": 1,
                "ending_market_value_reporting_currency": "1000.00",
            },
            {
                "valuation_date": "2026-01-01",
                "position_id": "SEC_1",
                "valuation_epoch": 1,
                "ending_market_value_reporting_currency": "1000.00",
            },
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_1",
                "beginning_market_value_reporting_currency": "0.00",
                "ending_market_value_reporting_currency": "1000.00",
                "cash_flows": [{"amount": "1000.00"}],
            },
            {
                "valuation_date": "2026-01-03",
                "position_id": "SEC_1",
                "beginning_market_value_reporting_currency": "0.00",
                "ending_market_value_reporting_currency": "1000.00",
                "trade_amount": "1000.00",
            },
        ],
    )

    assert result.evidence_summary["duplicate_snapshot_row_count"] == 1
    assert result.artifact_payload["duplicate_snapshot_samples"][0]["duplicate_count"] == 3
    assert result.evidence_summary["invalid_position_epoch_row_count"] == 1
    assert result.evidence_summary["position_continuity_gap_count"] == 0


def test_analyze_portfolio_position_reconciliation_flags_invalid_selected_position_values():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 1, 2),
        metric_basis="NET",
        report_end_date=date(2026, 1, 2),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 1, 2), begin_mv=1000.0, end_mv=612.06),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_1",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "612.06",
            },
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_2",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "n/a",
            },
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_POSITION_END_VALUE_PRESENT"}
    assert result.evidence_summary["invalid_position_value_date_count"] == 1
    assert result.evidence_summary["invalid_position_value_row_count"] == 1
    assert result.artifact_payload["invalid_position_value_samples"] == [
        {
            "valuation_date": "2026-01-02",
            "position_id": "SEC_2",
            "valuation_epoch": 5,
            "end_value_field": "ending_market_value_portfolio_currency",
            "raw_end_value": "n/a",
        }
    ]


def test_analyze_portfolio_position_reconciliation_flags_invalid_epoch_values():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 1, 2),
        metric_basis="NET",
        report_end_date=date(2026, 1, 2),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 1, 2), begin_mv=1000.0, end_mv=400.0),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_2",
                "valuation_epoch": "latest",
                "ending_market_value_portfolio_currency": "400.0",
            },
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_POSITION_EPOCH_PRESENT"}
    assert result.evidence_summary["invalid_position_epoch_date_count"] == 1
    assert result.evidence_summary["invalid_position_epoch_row_count"] == 1
    assert result.artifact_payload["invalid_position_epoch_samples"] == [
        {
            "valuation_date": "2026-01-02",
            "position_id": "SEC_2",
            "epoch_field": "valuation_epoch",
            "raw_epoch_value": "latest",
        }
    ]


def test_analyze_portfolio_position_reconciliation_flags_duplicate_snapshot_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 1, 2),
        metric_basis="NET",
        report_end_date=date(2026, 1, 2),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 1, 2), begin_mv=1000.0, end_mv=400.0),
        ],
    )

    result = analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.DEEP_RECONCILIATION,
        position_rows=[
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_2",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "400.0",
            },
            {
                "valuation_date": "2026-01-02",
                "position_id": "SEC_2",
                "valuation_epoch": 5,
                "ending_market_value_portfolio_currency": "400.0",
            },
        ],
    )

    assert {finding.code for finding in result.findings} == {"DUPLICATE_POSITION_SNAPSHOT_ROW_PRESENT"}
    assert result.evidence_summary["duplicate_snapshot_date_count"] == 1
    assert result.evidence_summary["duplicate_snapshot_row_count"] == 1
    assert result.artifact_payload["duplicate_snapshot_samples"] == [
        {
            "valuation_date": "2026-01-02",
            "position_id": "SEC_2",
            "valuation_epoch": 5,
            "duplicate_count": 2,
        }
    ]
