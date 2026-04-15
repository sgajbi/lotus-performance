from datetime import date

from app.models.inspection_requests import TWRInspectionProfile
from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.services.inspection.source_quality import run_source_quality_checks


def test_run_source_quality_checks_flags_stale_valuation_series():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 4, 1),
        metric_basis="NET",
        report_end_date=date(2026, 4, 3),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 1), begin_mv=1000.0, end_mv=1000.0),
            DailyInputData(perf_date=date(2026, 4, 2), begin_mv=1000.0, end_mv=1000.0),
            DailyInputData(perf_date=date(2026, 4, 3), begin_mv=1000.0, end_mv=1000.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert {finding.code for finding in result.findings} == {"STALE_VALUATION_SERIES_DETECTED"}
    assert result.evidence_summary["stale_series_run_count"] == 1
    assert result.evidence_summary["stale_series_observation_count"] == 3
    stale_finding = result.findings[0]
    assert stale_finding.evidence["stale_series_runs"] == [
        {
            "start_date": "2026-04-01",
            "end_date": "2026-04-03",
            "observation_count": 3,
            "begin_mv": 1000.0,
            "end_mv": 1000.0,
        }
    ]
    assert result.artifact_payload["stale_series_run_count"] == 1
    assert result.artifact_payload["stale_series_observation_count"] == 3
    assert result.artifact_payload["stale_series_runs"] == stale_finding.evidence["stale_series_runs"]


def test_run_source_quality_checks_does_not_flag_stale_series_when_cash_or_fees_change():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 4, 6),
        metric_basis="NET",
        report_end_date=date(2026, 4, 8),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 6), begin_mv=1000.0, end_mv=1000.0, bod_cf=0.0, eod_cf=0.0),
            DailyInputData(perf_date=date(2026, 4, 7), begin_mv=1000.0, end_mv=1000.0, bod_cf=0.0, eod_cf=10.0),
            DailyInputData(perf_date=date(2026, 4, 8), begin_mv=1000.0, end_mv=1000.0, bod_cf=0.0, eod_cf=0.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert "STALE_VALUATION_SERIES_DETECTED" not in {finding.code for finding in result.findings}
    assert result.evidence_summary["stale_series_run_count"] == 0
    assert result.evidence_summary["stale_series_observation_count"] == 0
    assert result.artifact_payload["stale_series_runs"] == []


def test_run_source_quality_checks_combines_source_quality_signals_coherently():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 4, 2),
        metric_basis="NET",
        report_end_date=date(2026, 4, 7),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 2), begin_mv=1000.0, end_mv=1000.0),
            DailyInputData(perf_date=date(2026, 4, 3), begin_mv=1000.0, end_mv=1000.0),
            DailyInputData(perf_date=date(2026, 4, 4), begin_mv=1000.0, end_mv=1000.0),
            DailyInputData(perf_date=date(2026, 4, 7), begin_mv=1000.0, end_mv=1250.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert {finding.code for finding in result.findings} == {
        "WEEKEND_OBSERVATIONS_PRESENT",
        "BUSINESS_DATE_GAPS_PRESENT",
        "STALE_VALUATION_SERIES_DETECTED",
        "EXTREME_DAILY_MOVE_DETECTED",
    }
    assert result.evidence_summary["weekend_observation_count"] == 1
    assert result.evidence_summary["missing_business_date_count"] == 1
    assert result.evidence_summary["stale_series_run_count"] == 1
    assert result.evidence_summary["largest_abs_daily_move_pct"] >= 20.0
    assert result.artifact_payload["weekend_dates"] == ["2026-04-04"]
    assert result.artifact_payload["missing_business_dates"] == ["2026-04-06"]
    assert result.artifact_payload["extreme_daily_move_threshold_pct"] == 10.0
    assert result.artifact_payload["extreme_daily_moves"] == [
        {
            "perf_date": "2026-04-07",
            "return_pct": 25.0,
        }
    ]
