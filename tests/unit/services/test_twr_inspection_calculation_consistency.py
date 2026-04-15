from datetime import date
from types import SimpleNamespace

from app.models.responses import (
    ComparativeAnalyticsBlock,
    ComparativeBreakdownItem,
    ComparativeReturnValue,
    ComparativeSummary,
    SinglePeriodPerformanceResult,
)
from app.services.inspection.calculation_consistency import run_twr_calculation_consistency_checks
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
