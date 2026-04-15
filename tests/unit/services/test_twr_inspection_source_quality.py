from datetime import date, timedelta

import pytest

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


def test_run_source_quality_checks_flags_nonpositive_daily_capital_base():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 4, 9),
        metric_basis="NET",
        report_end_date=date(2026, 4, 10),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 9), begin_mv=1000.0, end_mv=1010.0),
            DailyInputData(perf_date=date(2026, 4, 10), begin_mv=100.0, end_mv=105.0, bod_cf=-100.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert {finding.code for finding in result.findings} == {"NONPOSITIVE_DAILY_CAPITAL_BASE_DETECTED"}
    assert result.evidence_summary["nonpositive_capital_base_count"] == 1
    assert result.evidence_summary["largest_abs_daily_move_pct"] == pytest.approx(1.0)
    assert result.artifact_payload["nonpositive_capital_base_count"] == 1
    assert result.artifact_payload["nonpositive_capital_base_samples"] == [
        {
            "perf_date": "2026-04-10",
            "begin_mv": 100.0,
            "bod_cf": -100.0,
            "effective_capital_base": 0.0,
        }
    ]


def test_run_source_quality_checks_flags_canonical_balanced_mandate_move_outlier():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 4, 6),
        metric_basis="NET",
        report_end_date=date(2026, 4, 7),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 6), begin_mv=1000.0, end_mv=1005.0),
            DailyInputData(perf_date=date(2026, 4, 7), begin_mv=1005.0, end_mv=1035.15),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert {finding.code for finding in result.findings} == {"MANDATE_DAILY_MOVE_OUTLIER_DETECTED"}
    finding = result.findings[0]
    assert finding.severity == "warning"
    assert finding.evidence["mandate_profile"] == "canonical_balanced_private_banking"
    assert finding.evidence["threshold_pct"] == 2.0
    assert finding.evidence["outliers"] == [{"perf_date": "2026-04-07", "return_pct": pytest.approx(3.0)}]
    assert result.evidence_summary["mandate_daily_move_outlier_count"] == 1
    assert result.artifact_payload["mandate_daily_move_profile"] == "canonical_balanced_private_banking"
    assert result.artifact_payload["mandate_daily_move_threshold_pct"] == 2.0
    assert result.artifact_payload["mandate_daily_move_outlier_count"] == 1


def test_run_source_quality_checks_keeps_mandate_move_rule_bounded_to_canonical_profile():
    performance_request = PerformanceRequest(
        portfolio_id="NON_CANONICAL_PORTFOLIO",
        performance_start_date=date(2026, 4, 6),
        metric_basis="NET",
        report_end_date=date(2026, 4, 7),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 6), begin_mv=1000.0, end_mv=1005.0),
            DailyInputData(perf_date=date(2026, 4, 7), begin_mv=1005.0, end_mv=1035.15),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert result.findings == []
    assert result.evidence_summary["mandate_daily_move_outlier_count"] == 0
    assert result.artifact_payload["mandate_daily_move_profile"] is None
    assert result.artifact_payload["mandate_daily_move_outliers"] == []


def test_run_source_quality_checks_flags_top_day_return_concentration():
    business_dates: list[date] = []
    current_date = date(2026, 3, 2)
    while len(business_dates) < 20:
        if current_date.weekday() < 5:
            business_dates.append(current_date)
        current_date += timedelta(days=1)

    high_move_dates = {business_dates[4], business_dates[11], business_dates[19]}
    valuation_points = [
        DailyInputData(
            perf_date=perf_date,
            begin_mv=1000.0,
            end_mv=(1050.0 if perf_date in high_move_dates else 1001.0) + (index * 0.01),
        )
        for index, perf_date in enumerate(business_dates)
    ]
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=business_dates[0],
        metric_basis="NET",
        report_end_date=business_dates[-1],
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=valuation_points,
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert {finding.code for finding in result.findings} == {
        "MANDATE_DAILY_MOVE_OUTLIER_DETECTED",
        "RETURN_CONCENTRATION_DETECTED",
    }
    concentration_finding = next(
        finding for finding in result.findings if finding.code == "RETURN_CONCENTRATION_DETECTED"
    )
    assert concentration_finding.evidence["top_n"] == 3
    assert concentration_finding.evidence["threshold"] == 0.8
    assert concentration_finding.evidence["observation_count"] == 20
    assert concentration_finding.evidence["concentration_ratio"] > 0.8
    assert result.evidence_summary["return_concentration_ratio"] > 0.8
    assert result.artifact_payload["return_concentration_observation_count"] == 20
    assert result.artifact_payload["return_concentration_top_n"] == 3
    assert len(result.artifact_payload["return_concentration_top_moves"]) == 3


def test_run_source_quality_checks_requires_enough_observations_for_return_concentration():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 4, 1),
        metric_basis="NET",
        report_end_date=date(2026, 4, 3),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 1), begin_mv=1000.0, end_mv=1001.0),
            DailyInputData(perf_date=date(2026, 4, 2), begin_mv=1000.0, end_mv=1050.0),
            DailyInputData(perf_date=date(2026, 4, 3), begin_mv=1000.0, end_mv=1001.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert "RETURN_CONCENTRATION_DETECTED" not in {finding.code for finding in result.findings}
    assert result.evidence_summary["return_concentration_ratio"] == 0.0
    assert result.artifact_payload["return_concentration_observation_count"] == 3
    assert result.artifact_payload["return_concentration_top_moves"] == []


def test_run_source_quality_checks_flags_repeated_same_direction_daily_move_pattern():
    performance_request = PerformanceRequest(
        portfolio_id="NON_CANONICAL_PORTFOLIO",
        performance_start_date=date(2026, 4, 1),
        metric_basis="NET",
        report_end_date=date(2026, 4, 7),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 1), begin_mv=1000.0, end_mv=1002.0),
            DailyInputData(perf_date=date(2026, 4, 2), begin_mv=1000.0, end_mv=1015.0),
            DailyInputData(perf_date=date(2026, 4, 3), begin_mv=1000.0, end_mv=1016.0),
            DailyInputData(perf_date=date(2026, 4, 6), begin_mv=1000.0, end_mv=1017.0),
            DailyInputData(perf_date=date(2026, 4, 7), begin_mv=1000.0, end_mv=1002.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert {finding.code for finding in result.findings} == {"REPEATED_DAILY_MOVE_PATTERN_DETECTED"}
    finding = result.findings[0]
    assert finding.evidence["min_abs_return_pct"] == 1.0
    assert finding.evidence["min_run_length"] == 3
    assert finding.evidence["run_count"] == 1
    runs = finding.evidence["runs"]
    assert isinstance(runs, list)
    assert len(runs) == 1
    run = runs[0]
    assert run["direction"] == "positive"
    assert run["start_date"] == "2026-04-02"
    assert run["end_date"] == "2026-04-06"
    assert run["observation_count"] == 3
    assert run["moves"] == [
        {"perf_date": "2026-04-02", "return_pct": pytest.approx(1.5)},
        {"perf_date": "2026-04-03", "return_pct": pytest.approx(1.6)},
        {"perf_date": "2026-04-06", "return_pct": pytest.approx(1.7)},
    ]
    assert result.evidence_summary["repeated_move_run_count"] == 1
    assert result.artifact_payload["repeated_move_run_count"] == 1
    assert result.artifact_payload["repeated_move_min_run_length"] == 3


def test_run_source_quality_checks_ignores_alternating_large_daily_moves_for_repeated_pattern():
    performance_request = PerformanceRequest(
        portfolio_id="NON_CANONICAL_PORTFOLIO",
        performance_start_date=date(2026, 4, 1),
        metric_basis="NET",
        report_end_date=date(2026, 4, 6),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 1), begin_mv=1000.0, end_mv=1015.0),
            DailyInputData(perf_date=date(2026, 4, 2), begin_mv=1000.0, end_mv=985.0),
            DailyInputData(perf_date=date(2026, 4, 3), begin_mv=1000.0, end_mv=1016.0),
            DailyInputData(perf_date=date(2026, 4, 6), begin_mv=1000.0, end_mv=984.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert result.findings == []
    assert result.evidence_summary["repeated_move_run_count"] == 0
    assert result.artifact_payload["repeated_move_runs"] == []
