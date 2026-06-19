from datetime import date, timedelta

import pytest

from app.models.inspection_requests import TWRInspectionProfile
from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.services.inspection import source_quality
from app.services.inspection.source_quality import run_source_quality_checks


def test_source_quality_evidence_builders_project_summary_and_artifacts():
    context = source_quality._SourceQualityEvidenceContext(
        valuation_point_count=3,
        weekend_dates=["2026-04-04"],
        missing_business_dates=["2026-04-06"],
        stale_runs=[
            source_quality.StaleSeriesRun(
                start_date="2026-04-01",
                end_date="2026-04-03",
                observation_count=3,
                begin_mv=1000.0,
                end_mv=1000.0,
            )
        ],
        invalid_capital_bases=[{"perf_date": "2026-04-02", "capital_base": 0.0}],
        largest_abs_daily_move_pct=12.0,
        extreme_move_threshold_pct=10.0,
        extreme_moves=[source_quality.DailyMove(perf_date="2026-04-03", return_pct=12.0)],
        mandate_profile=source_quality.MandateDailyMoveProfile(
            name="canonical_balanced_private_banking",
            threshold_pct=2.0,
        ),
        mandate_outliers=[source_quality.DailyMove(perf_date="2026-04-03", return_pct=12.0)],
        return_concentration=source_quality.ReturnConcentrationAssessment(
            observation_count=20,
            concentration_ratio=0.81,
            top_moves=[source_quality.DailyMove(perf_date="2026-04-03", return_pct=12.0)],
            triggered=True,
        ),
        repeated_move_runs=[],
        monthly_day_dominance=[],
    )

    summary = source_quality._build_source_quality_evidence_summary(context)
    artifact = source_quality._build_source_quality_artifact_payload(context)

    assert summary["stale_series_observation_count"] == 3
    assert summary["mandate_daily_move_outlier_count"] == 1
    assert artifact["stale_series_runs"] == [
        {
            "start_date": "2026-04-01",
            "end_date": "2026-04-03",
            "observation_count": 3,
            "begin_mv": 1000.0,
            "end_mv": 1000.0,
        }
    ]
    assert artifact["mandate_daily_move_profile"] == "canonical_balanced_private_banking"
    assert artifact["extreme_daily_moves"] == [{"perf_date": "2026-04-03", "return_pct": 12.0}]


def test_is_unobserved_business_date_detects_missing_weekday_only():
    observed_dates = {"2026-04-03"}

    assert source_quality._is_unobserved_business_date(date(2026, 4, 6), observed_dates)
    assert not source_quality._is_unobserved_business_date(date(2026, 4, 4), observed_dates)
    assert not source_quality._is_unobserved_business_date(date(2026, 4, 3), observed_dates)


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


def test_run_source_quality_checks_flags_monthly_single_day_dominance():
    valuation_points = [
        DailyInputData(
            perf_date=date(2026, 3, day),
            begin_mv=1000.0,
            end_mv=1001.0 + (index * 0.01),
        )
        for index, day in enumerate([2, 3, 4, 5, 6, 9, 10, 11, 12, 13])
    ]
    valuation_points.append(DailyInputData(perf_date=date(2026, 3, 16), begin_mv=1000.0, end_mv=1080.0))
    performance_request = PerformanceRequest(
        portfolio_id="NON_CANONICAL_PORTFOLIO",
        performance_start_date=date(2026, 3, 2),
        metric_basis="NET",
        report_end_date=date(2026, 3, 16),
        analyses=[Analysis(period="MTD", frequencies=["daily"])],
        valuation_points=valuation_points,
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert {finding.code for finding in result.findings} == {"MONTHLY_RETURN_DAY_DOMINANCE_DETECTED"}
    finding = result.findings[0]
    assert finding.evidence["min_observations"] == 10
    assert finding.evidence["threshold"] == 0.75
    assert finding.evidence["dominance_count"] == 1
    samples = finding.evidence["samples"]
    assert isinstance(samples, list)
    assert len(samples) == 1
    sample = samples[0]
    assert sample["month"] == "2026-03"
    assert sample["observation_count"] == 11
    assert sample["dominance_ratio"] > 0.75
    assert sample["dominant_move"] == {"perf_date": "2026-03-16", "return_pct": pytest.approx(8.0)}
    assert result.evidence_summary["monthly_day_dominance_count"] == 1
    assert result.artifact_payload["monthly_day_dominance_count"] == 1


def test_economic_plausibility_finding_builders_preserve_contract_metadata():
    concentration_findings = source_quality._build_return_concentration_findings(
        source_quality.ReturnConcentrationAssessment(
            observation_count=20,
            concentration_ratio=0.81,
            top_moves=[source_quality.DailyMove(perf_date="2026-03-16", return_pct=8.0)],
            triggered=True,
        )
    )
    dominance_findings = source_quality._build_monthly_day_dominance_findings(
        [
            source_quality.MonthlyDayDominance(
                month="2026-03",
                observation_count=11,
                dominance_ratio=0.8,
                dominant_move=source_quality.DailyMove(perf_date="2026-03-16", return_pct=8.0),
            )
        ]
    )

    assert [(finding.severity, finding.category, finding.owner_repo) for finding in concentration_findings] == [
        ("warning", "economic_plausibility", "lotus-performance")
    ]
    assert [(finding.severity, finding.category, finding.owner_repo) for finding in dominance_findings] == [
        ("warning", "economic_plausibility", "lotus-performance")
    ]
    assert concentration_findings[0].code == "RETURN_CONCENTRATION_DETECTED"
    assert concentration_findings[0].evidence["top_moves"] == [{"perf_date": "2026-03-16", "return_pct": 8.0}]
    assert dominance_findings[0].code == "MONTHLY_RETURN_DAY_DOMINANCE_DETECTED"
    assert dominance_findings[0].evidence["samples"] == [
        {
            "month": "2026-03",
            "observation_count": 11,
            "dominance_ratio": 0.8,
            "dominant_move": {"perf_date": "2026-03-16", "return_pct": 8.0},
        }
    ]


def test_run_source_quality_checks_requires_enough_monthly_observations_for_day_dominance():
    performance_request = PerformanceRequest(
        portfolio_id="NON_CANONICAL_PORTFOLIO",
        performance_start_date=date(2026, 3, 2),
        metric_basis="NET",
        report_end_date=date(2026, 3, 6),
        analyses=[Analysis(period="MTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 3, 2), begin_mv=1000.0, end_mv=1080.0),
            DailyInputData(perf_date=date(2026, 3, 3), begin_mv=1000.0, end_mv=1001.0),
            DailyInputData(perf_date=date(2026, 3, 4), begin_mv=1000.0, end_mv=1001.0),
            DailyInputData(perf_date=date(2026, 3, 5), begin_mv=1000.0, end_mv=1001.0),
            DailyInputData(perf_date=date(2026, 3, 6), begin_mv=1000.0, end_mv=1001.0),
        ],
    )

    result = run_source_quality_checks(
        performance_request=performance_request,
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert "MONTHLY_RETURN_DAY_DOMINANCE_DETECTED" not in {finding.code for finding in result.findings}
    assert result.evidence_summary["monthly_day_dominance_count"] == 0
    assert result.artifact_payload["monthly_day_dominance_samples"] == []


def test_monthly_day_dominance_detects_single_dominant_move():
    month_moves = [source_quality.DailyMove(perf_date=f"2026-03-{day:02d}", return_pct=1.0) for day in range(1, 10)]
    dominant_move = source_quality.DailyMove(perf_date="2026-03-10", return_pct=40.0)
    month_moves.append(dominant_move)

    dominance = source_quality._monthly_day_dominance(month="2026-03", month_moves=month_moves)

    assert dominance == source_quality.MonthlyDayDominance(
        month="2026-03",
        observation_count=10,
        dominance_ratio=40.0 / 49.0,
        dominant_move=dominant_move,
    )


def test_monthly_day_dominance_requires_enough_observations_and_movement():
    assert (
        source_quality._monthly_day_dominance(
            month="2026-03",
            month_moves=[
                source_quality.DailyMove(perf_date=f"2026-03-{day:02d}", return_pct=10.0) for day in range(1, 10)
            ],
        )
        is None
    )
    assert (
        source_quality._monthly_day_dominance(
            month="2026-03",
            month_moves=[
                source_quality.DailyMove(perf_date=f"2026-03-{day:02d}", return_pct=0.0) for day in range(1, 11)
            ],
        )
        is None
    )
