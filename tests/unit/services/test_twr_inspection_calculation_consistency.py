from datetime import date
from types import SimpleNamespace

from app.models.responses import (
    ComparativeAnalyticsBlock,
    ComparativeBreakdownItem,
    ComparativeReturnValue,
    ComparativeSummary,
    SinglePeriodPerformanceResult,
    TWRDailyCalculationEvidence,
)
from app.services.inspection.calculation_consistency import (
    _apply_daily_no_investment_period_status,
    _check_relative_breakdown_frequency,
    _comparative_return_mismatches,
    _daily_calculation_evidence_mismatches,
    _expected_daily_external_flows,
    _expected_daily_return,
    run_twr_calculation_consistency_checks,
)
from common.enums import Frequency


def test_calculation_consistency_flags_relative_breakdown_bucket_alignment_mismatch():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=2.0,
                ),
                benchmark=_analytics_block(
                    period="2026-04",
                    period_start=date(2026, 4, 1),
                    period_end=date(2026, 4, 30),
                    period_return=1.0,
                ),
                relative_performance=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=1.0,
                ),
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert {finding.code for finding in result.findings} == {"RELATIVE_BREAKDOWN_BUCKET_ALIGNMENT_MISMATCH"}
    finding = result.findings[0]
    assert finding.evidence["period"] == "YTD"
    assert finding.evidence["scope"] == "breakdowns.monthly.2026-03"
    assert finding.evidence["relative_bucket"] == {
        "period": "2026-03",
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
    }
    assert finding.evidence["portfolio_bucket"] == finding.evidence["relative_bucket"]
    assert finding.evidence["benchmark_bucket"] == {
        "period": "2026-04",
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
    }


def test_comparative_return_mismatches_distinguish_absent_equal_and_different_components():
    mismatches = _comparative_return_mismatches(
        expected=ComparativeReturnValue(base=1.0, local=None, fx=0.1),
        actual=ComparativeReturnValue(base=1.0, local=0.2, fx=0.3),
    )

    assert mismatches == {
        "local": (None, 0.2),
        "fx": (0.1, 0.3),
    }


def test_calculation_consistency_does_not_compare_misaligned_relative_breakdown_arithmetic():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=2.0,
                ),
                benchmark=_analytics_block(
                    period="2026-04",
                    period_start=date(2026, 4, 1),
                    period_end=date(2026, 4, 30),
                    period_return=1.0,
                ),
                relative_performance=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=99.0,
                ),
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    finding_codes = {finding.code for finding in result.findings}
    assert finding_codes == {
        "RELATIVE_PERFORMANCE_CUMULATIVE_MISMATCH",
        "RELATIVE_PERFORMANCE_SUMMARY_MISMATCH",
        "RELATIVE_BREAKDOWN_BUCKET_ALIGNMENT_MISMATCH",
    }
    assert "RELATIVE_BREAKDOWN_PERIOD_MISMATCH" not in finding_codes


def test_calculation_consistency_flags_relative_block_without_benchmark_block():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=2.0,
                ),
                benchmark=None,
                relative_performance=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=1.0,
                ),
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert {finding.code for finding in result.findings} == {"RELATIVE_PERFORMANCE_BENCHMARK_BLOCK_MISSING"}
    assert result.findings[0].evidence == {
        "period": "YTD",
        "scope": "relative_performance",
        "benchmark_present": False,
        "relative_performance_present": True,
    }


def test_calculation_consistency_flags_relative_breakdown_cardinality_mismatch():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=2.0,
                ),
                benchmark=ComparativeAnalyticsBlock(
                    summary=ComparativeSummary(
                        period_return=ComparativeReturnValue(base=1.0),
                        cumulative_return=ComparativeReturnValue(base=1.0),
                    ),
                    breakdowns={Frequency.MONTHLY: []},
                ),
                relative_performance=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=1.0,
                ),
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    finding_codes = {finding.code for finding in result.findings}
    assert "RELATIVE_BREAKDOWN_CARDINALITY_MISMATCH" in finding_codes
    cardinality_finding = next(
        finding for finding in result.findings if finding.code == "RELATIVE_BREAKDOWN_CARDINALITY_MISMATCH"
    )
    assert cardinality_finding.evidence["relative_count"] == 1
    assert cardinality_finding.evidence["portfolio_count"] == 1
    assert cardinality_finding.evidence["benchmark_count"] == 0


def test_calculation_consistency_flags_benchmark_block_without_relative_block():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=2.0,
                ),
                benchmark=_analytics_block(
                    period="2026-03",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    period_return=1.0,
                ),
                relative_performance=None,
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert {finding.code for finding in result.findings} == {"BENCHMARK_RELATIVE_PERFORMANCE_BLOCK_MISSING"}
    assert result.findings[0].evidence == {
        "period": "YTD",
        "scope": "benchmark",
        "benchmark_present": True,
        "relative_performance_present": False,
    }


def test_relative_breakdown_frequency_helper_checks_aligned_row_arithmetic():
    portfolio_item = _breakdown_item(
        period="2026-03",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        period_return=3.0,
        cumulative_return=5.0,
    )
    benchmark_item = _breakdown_item(
        period="2026-03",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        period_return=1.0,
        cumulative_return=2.0,
    )
    relative_item = _breakdown_item(
        period="2026-03",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        period_return=99.0,
        cumulative_return=99.0,
    )

    findings = _check_relative_breakdown_frequency(
        period_name="YTD",
        frequency=Frequency.MONTHLY,
        portfolio_items=[portfolio_item],
        benchmark_items=[benchmark_item],
        relative_items=[relative_item],
    )

    assert [finding.code for finding in findings] == [
        "RELATIVE_BREAKDOWN_PERIOD_MISMATCH",
        "RELATIVE_BREAKDOWN_CUMULATIVE_MISMATCH",
    ]
    assert findings[0].evidence["scope"] == "breakdowns.monthly.2026-03.period_return"
    assert findings[0].evidence["mismatches"]["base"] == {"expected": 2.0, "actual": 99.0}
    assert findings[1].evidence["scope"] == "breakdowns.monthly.2026-03.cumulative_return"
    assert findings[1].evidence["mismatches"]["base"] == {"expected": 3.0, "actual": 99.0}


def test_calculation_consistency_flags_portfolio_breakdown_link_mismatch():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=ComparativeAnalyticsBlock(
                    summary=ComparativeSummary(
                        period_return=ComparativeReturnValue(base=99.0),
                        cumulative_return=ComparativeReturnValue(base=99.0),
                    ),
                    breakdowns={
                        Frequency.MONTHLY: [
                            ComparativeBreakdownItem(
                                period="2026-03",
                                period_start=date(2026, 3, 1),
                                period_end=date(2026, 3, 31),
                                period_return=ComparativeReturnValue(base=1.0),
                                cumulative_return=ComparativeReturnValue(base=1.0),
                            ),
                            ComparativeBreakdownItem(
                                period="2026-04",
                                period_start=date(2026, 4, 1),
                                period_end=date(2026, 4, 30),
                                period_return=ComparativeReturnValue(base=1.0),
                                cumulative_return=ComparativeReturnValue(base=2.01),
                            ),
                        ]
                    },
                )
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert {finding.code for finding in result.findings} == {"PORTFOLIO_BREAKDOWN_LINK_MISMATCH"}
    assert result.findings[0].evidence["bucket_count"] == 2


def test_calculation_consistency_checks_daily_calculation_evidence():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_daily_evidence_block(
                    evidence=TWRDailyCalculationEvidence(
                        begin_mv=1000.0,
                        end_mv=1013.0,
                        bod_cf=0.0,
                        eod_cf=0.0,
                        external_inflows=0.0,
                        external_outflows=0.0,
                        management_fees=3.0,
                        signed_adjusted_capital=1000.0,
                        adjusted_capital=1000.0,
                        performance_pnl=13.0,
                        daily_return=1.3,
                        status="calculated",
                        reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
                        warnings=[],
                    )
                )
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert result.findings == []
    assert result.evidence_summary["daily_calculation_evidence_rows_checked"] == 1


def test_calculation_consistency_flags_daily_calculation_evidence_mismatch():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_daily_evidence_block(
                    evidence=TWRDailyCalculationEvidence(
                        begin_mv=1000.0,
                        end_mv=1013.0,
                        bod_cf=100.0,
                        eod_cf=-50.0,
                        external_inflows=0.0,
                        external_outflows=0.0,
                        management_fees=3.0,
                        signed_adjusted_capital=1000.0,
                        adjusted_capital=1000.0,
                        performance_pnl=13.0,
                        daily_return=99.0,
                        status="calculated",
                        reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
                        warnings=[],
                    )
                )
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    finding_codes = {finding.code for finding in result.findings}
    assert finding_codes == {"DAILY_CALCULATION_EVIDENCE_MISMATCH"}
    finding = result.findings[0]
    assert finding.evidence["scope"] == "breakdowns.daily.2026-03-01.calculation_evidence"
    assert finding.evidence["mismatches"]["signed_adjusted_capital"] == {"expected": 1100.0, "actual": 1000.0}
    assert finding.evidence["mismatches"]["adjusted_capital"] == {"expected": 1100.0, "actual": 1000.0}
    assert finding.evidence["mismatches"]["external_inflows"] == {"expected": 100.0, "actual": 0.0}
    assert finding.evidence["mismatches"]["external_outflows"] == {"expected": 50.0, "actual": 0.0}
    assert finding.evidence["mismatches"]["daily_return"]["actual"] == 99.0
    assert finding.evidence["mismatches"]["period_return.base"]["actual"] == 1.3


def test_daily_calculation_evidence_mismatches_capture_numeric_status_and_semantics():
    block = _daily_evidence_block(
        evidence=TWRDailyCalculationEvidence(
            begin_mv=0.0,
            end_mv=0.0,
            bod_cf=0.0,
            eod_cf=0.0,
            external_inflows=1.0,
            external_outflows=1.0,
            management_fees=0.0,
            signed_adjusted_capital=1.0,
            adjusted_capital=0.0,
            performance_pnl=0.0,
            daily_return=0.0,
            status="calculated",
            reason_codes=[],
            warnings=[],
        )
    )
    item = block.breakdowns[Frequency.DAILY][0]

    mismatches = _daily_calculation_evidence_mismatches(evidence=item.calculation_evidence, item=item)

    assert mismatches["signed_adjusted_capital"] == {"expected": 0.0, "actual": 1.0}
    assert mismatches["external_inflows"] == {"expected": 0, "actual": 1.0}
    assert mismatches["external_outflows"] == {"expected": 0, "actual": 1.0}
    assert mismatches["status"] == {
        "expected": "not_calculated",
        "actual": "calculated",
        "reason": "zero_adjusted_capital",
    }
    assert mismatches["semantics"]["missing_reason_codes"] == [
        "FLOW_NEUTRALIZED_DAILY_RETURN",
        "ZERO_ADJUSTED_CAPITAL",
    ]


def test_expected_daily_flow_and_return_helpers_project_evidence_policy():
    evidence = TWRDailyCalculationEvidence(
        begin_mv=1000.0,
        end_mv=1013.0,
        bod_cf=100.0,
        eod_cf=-50.0,
        external_inflows=100.0,
        external_outflows=50.0,
        management_fees=3.0,
        signed_adjusted_capital=1100.0,
        adjusted_capital=1100.0,
        performance_pnl=13.0,
        daily_return=1.1818181818,
        status="calculated",
        reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
        warnings=[],
    )

    flows = _expected_daily_external_flows(evidence)

    assert flows.external_inflows == 100.0
    assert flows.external_outflows == 50.0
    assert _expected_daily_return(evidence) == 13.0 / 1100.0 * 100


def test_expected_daily_return_is_absent_when_daily_evidence_is_not_calculable():
    evidence = TWRDailyCalculationEvidence(
        begin_mv=0.0,
        end_mv=0.0,
        bod_cf=0.0,
        eod_cf=0.0,
        external_inflows=0.0,
        external_outflows=0.0,
        management_fees=0.0,
        signed_adjusted_capital=0.0,
        adjusted_capital=0.0,
        performance_pnl=0.0,
        daily_return=0.0,
        status="calculated",
        reason_codes=["ZERO_ADJUSTED_CAPITAL"],
        warnings=[],
    )

    assert _expected_daily_return(evidence) is None


def test_calculation_consistency_flags_calculated_status_with_zero_adjusted_capital():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_daily_evidence_block(
                    evidence=TWRDailyCalculationEvidence(
                        begin_mv=0.0,
                        end_mv=0.0,
                        bod_cf=0.0,
                        eod_cf=0.0,
                        external_inflows=0.0,
                        external_outflows=0.0,
                        management_fees=0.0,
                        signed_adjusted_capital=0.0,
                        adjusted_capital=0.0,
                        performance_pnl=0.0,
                        daily_return=0.0,
                        status="calculated",
                        reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
                        warnings=[],
                    )
                )
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert {finding.code for finding in result.findings} == {"DAILY_CALCULATION_EVIDENCE_MISMATCH"}
    assert result.findings[0].evidence["mismatches"]["status"] == {
        "expected": "not_calculated",
        "actual": "calculated",
        "reason": "zero_adjusted_capital",
    }


def test_calculation_consistency_flags_missing_daily_semantic_reason_codes():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_daily_evidence_block(
                    evidence=TWRDailyCalculationEvidence(
                        begin_mv=1000.0,
                        end_mv=0.0,
                        bod_cf=0.0,
                        eod_cf=-100.0,
                        external_inflows=0.0,
                        external_outflows=100.0,
                        management_fees=0.0,
                        signed_adjusted_capital=1000.0,
                        adjusted_capital=1000.0,
                        performance_pnl=-900.0,
                        daily_return=-90.0,
                        status="calculated",
                        linkability_status="linkable",
                        episode_status="open",
                        reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
                        warnings=[],
                    )
                )
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert {finding.code for finding in result.findings} == {"DAILY_CALCULATION_EVIDENCE_MISMATCH"}
    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {"missing_reason_codes": ["FULL_WITHDRAWAL_DAY"]}


def test_calculation_consistency_skips_daily_rows_without_calculation_evidence():
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=ComparativeAnalyticsBlock(
                    summary=ComparativeSummary(
                        period_return=ComparativeReturnValue(base=1.0),
                        cumulative_return=ComparativeReturnValue(base=1.0),
                    ),
                    breakdowns={
                        Frequency.DAILY: [
                            ComparativeBreakdownItem(
                                period="2026-03-01",
                                period_start=date(2026, 3, 1),
                                period_end=date(2026, 3, 1),
                                period_return=ComparativeReturnValue(base=1.0),
                                cumulative_return=ComparativeReturnValue(base=1.0),
                            )
                        ]
                    },
                )
            )
        }
    )

    result = run_twr_calculation_consistency_checks(response)

    assert result.findings == []
    assert result.evidence_summary["daily_calculation_evidence_rows_checked"] == 0


def test_calculation_consistency_flags_negative_adjusted_capital_semantics():
    result = _inspect_daily_evidence(
        TWRDailyCalculationEvidence(
            begin_mv=-1000.0,
            end_mv=-987.0,
            bod_cf=0.0,
            eod_cf=0.0,
            external_inflows=0.0,
            external_outflows=0.0,
            management_fees=0.0,
            signed_adjusted_capital=-1000.0,
            adjusted_capital=1000.0,
            performance_pnl=13.0,
            daily_return=1.3,
            status="calculated",
            reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
            warnings=[],
        )
    )

    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {
        "missing_reason_codes": ["NEGATIVE_ADJUSTED_CAPITAL_INPUT"],
        "missing_warnings": ["NEGATIVE_ADJUSTED_CAPITAL_INPUT"],
    }


def test_calculation_consistency_flags_near_zero_adjusted_capital_semantics():
    result = _inspect_daily_evidence(
        TWRDailyCalculationEvidence(
            begin_mv=0.000000001,
            end_mv=0.000000001,
            bod_cf=0.0,
            eod_cf=0.0,
            external_inflows=0.0,
            external_outflows=0.0,
            management_fees=0.0,
            signed_adjusted_capital=0.000000001,
            adjusted_capital=0.000000001,
            performance_pnl=0.0,
            daily_return=0.0,
            status="calculated",
            reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
            warnings=[],
        ),
        period_return=0.0,
    )

    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {
        "missing_reason_codes": ["NEAR_ZERO_ADJUSTED_CAPITAL"],
        "missing_warnings": ["NEAR_ZERO_ADJUSTED_CAPITAL"],
    }


def test_calculation_consistency_flags_episode_status_mismatch_for_reset_and_nip():
    result = _inspect_daily_evidence(
        TWRDailyCalculationEvidence(
            begin_mv=1000.0,
            end_mv=1013.0,
            bod_cf=0.0,
            eod_cf=0.0,
            external_inflows=0.0,
            external_outflows=0.0,
            management_fees=0.0,
            signed_adjusted_capital=1000.0,
            adjusted_capital=1000.0,
            performance_pnl=13.0,
            daily_return=1.3,
            status="calculated",
            linkability_status="linkable",
            episode_status="open",
            reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN", "RESET_DAY", "NO_INVESTMENT_PERIOD"],
            warnings=[],
        )
    )

    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {
        "linkability_status": {"expected": "reset_boundary", "actual": "linkable"},
        "episode_status": {"expected": "reset_boundary", "actual": "open"},
    }


def test_no_investment_period_status_policy_only_overrides_open_linkable_days():
    assert _apply_daily_no_investment_period_status(
        linkability_status="linkable",
        episode_status="open",
    ) == ("not_calculated", "no_investment")
    assert _apply_daily_no_investment_period_status(
        linkability_status="reset_boundary",
        episode_status="reset_boundary",
    ) == ("reset_boundary", "reset_boundary")


def test_calculation_consistency_flags_effective_period_exclusion_warning():
    result = _inspect_daily_evidence(
        TWRDailyCalculationEvidence(
            begin_mv=1000.0,
            end_mv=1000.0,
            bod_cf=0.0,
            eod_cf=0.0,
            external_inflows=0.0,
            external_outflows=0.0,
            management_fees=0.0,
            signed_adjusted_capital=1000.0,
            adjusted_capital=1000.0,
            performance_pnl=0.0,
            daily_return=0.0,
            status="not_calculated",
            linkability_status="linkable",
            episode_status="open",
            reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN", "BEFORE_EFFECTIVE_PERIOD_START"],
            warnings=[],
        ),
        period_return=0.0,
    )

    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {
        "linkability_status": {"expected": "not_calculated", "actual": "linkable"},
        "episode_status": {"expected": "not_in_period", "actual": "open"},
        "missing_warnings": ["BEFORE_EFFECTIVE_PERIOD_START"],
    }


def test_calculation_consistency_preserves_period_semantic_priority_order():
    result = _inspect_daily_evidence(
        TWRDailyCalculationEvidence(
            begin_mv=1000.0,
            end_mv=1000.0,
            bod_cf=0.0,
            eod_cf=0.0,
            external_inflows=0.0,
            external_outflows=0.0,
            management_fees=0.0,
            signed_adjusted_capital=1000.0,
            adjusted_capital=1000.0,
            performance_pnl=0.0,
            daily_return=0.0,
            status="not_calculated",
            linkability_status="linkable",
            episode_status="open",
            reason_codes=[
                "FLOW_NEUTRALIZED_DAILY_RETURN",
                "BEFORE_EFFECTIVE_PERIOD_START",
                "RESET_DAY",
                "NO_INVESTMENT_PERIOD",
            ],
            warnings=[],
        ),
        period_return=0.0,
    )

    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {
        "linkability_status": {"expected": "not_calculated", "actual": "linkable"},
        "episode_status": {"expected": "reset_boundary", "actual": "open"},
        "missing_warnings": ["BEFORE_EFFECTIVE_PERIOD_START"],
    }


def test_calculation_consistency_flags_full_loss_and_refunding_semantics():
    result = _inspect_daily_evidence(
        TWRDailyCalculationEvidence(
            begin_mv=0.0,
            end_mv=0.0,
            bod_cf=1000.0,
            eod_cf=0.0,
            external_inflows=1000.0,
            external_outflows=0.0,
            management_fees=0.0,
            signed_adjusted_capital=1000.0,
            adjusted_capital=1000.0,
            performance_pnl=-1000.0,
            daily_return=-100.0,
            status="calculated",
            linkability_status="linkable",
            episode_status="open",
            reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
            warnings=[],
        ),
        period_return=-100.0,
    )

    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {
        "linkability_status": {"expected": "not_linkable", "actual": "linkable"},
        "missing_reason_codes": ["FULL_LOSS_RETURN", "REFUNDING_DAY"],
        "missing_warnings": ["FULL_LOSS_RETURN"],
    }


def test_calculation_consistency_flags_below_full_loss_semantics():
    result = _inspect_daily_evidence(
        TWRDailyCalculationEvidence(
            begin_mv=1000.0,
            end_mv=-10.0,
            bod_cf=0.0,
            eod_cf=0.0,
            external_inflows=0.0,
            external_outflows=0.0,
            management_fees=0.0,
            signed_adjusted_capital=1000.0,
            adjusted_capital=1000.0,
            performance_pnl=-1010.0,
            daily_return=-101.0,
            status="calculated",
            linkability_status="linkable",
            episode_status="open",
            reason_codes=["FLOW_NEUTRALIZED_DAILY_RETURN"],
            warnings=[],
        ),
        period_return=-101.0,
    )

    semantics = result.findings[0].evidence["mismatches"]["semantics"]
    assert semantics == {
        "linkability_status": {"expected": "not_linkable", "actual": "linkable"},
        "missing_reason_codes": ["BELOW_FULL_LOSS_RETURN"],
        "missing_warnings": ["BELOW_FULL_LOSS_RETURN"],
    }


def _breakdown_item(
    *,
    period: str,
    period_start: date,
    period_end: date,
    period_return: float,
    cumulative_return: float,
) -> ComparativeBreakdownItem:
    return ComparativeBreakdownItem(
        period=period,
        period_start=period_start,
        period_end=period_end,
        period_return=ComparativeReturnValue(base=period_return),
        cumulative_return=ComparativeReturnValue(base=cumulative_return),
    )


def _analytics_block(
    *,
    period: str,
    period_start: date,
    period_end: date,
    period_return: float,
) -> ComparativeAnalyticsBlock:
    return ComparativeAnalyticsBlock(
        summary=ComparativeSummary(
            period_return=ComparativeReturnValue(base=period_return),
            cumulative_return=ComparativeReturnValue(base=period_return),
        ),
        breakdowns={
            Frequency.MONTHLY: [
                ComparativeBreakdownItem(
                    period=period,
                    period_start=period_start,
                    period_end=period_end,
                    period_return=ComparativeReturnValue(base=period_return),
                    cumulative_return=ComparativeReturnValue(base=period_return),
                )
            ]
        },
    )


def _inspect_daily_evidence(
    evidence: TWRDailyCalculationEvidence,
    *,
    period_return: float = 1.3,
):
    response = SimpleNamespace(
        results_by_period={
            "YTD": SinglePeriodPerformanceResult(
                portfolio=_daily_evidence_block(evidence=evidence, period_return=period_return)
            )
        }
    )
    return run_twr_calculation_consistency_checks(response)


def _daily_evidence_block(
    *,
    evidence: TWRDailyCalculationEvidence,
    period_return: float = 1.3,
) -> ComparativeAnalyticsBlock:
    return ComparativeAnalyticsBlock(
        summary=ComparativeSummary(
            period_return=ComparativeReturnValue(base=period_return),
            cumulative_return=ComparativeReturnValue(base=period_return),
        ),
        breakdowns={
            Frequency.DAILY: [
                ComparativeBreakdownItem(
                    period="2026-03-01",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 1),
                    period_return=ComparativeReturnValue(base=period_return),
                    cumulative_return=ComparativeReturnValue(base=period_return),
                    calculation_evidence=evidence,
                )
            ]
        },
    )
