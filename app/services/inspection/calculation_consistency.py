from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Iterable

from app.models.inspection_responses import TWRInspectionFinding
from app.models.responses import (
    ComparativeAnalyticsBlock,
    ComparativeBreakdownItem,
    ComparativeReturnValue,
    PerformanceResponse,
)

_ABS_TOLERANCE = 1e-6


@dataclass(frozen=True)
class CalculationConsistencyCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]


def run_twr_calculation_consistency_checks(response: PerformanceResponse) -> CalculationConsistencyCheckResult:
    findings: list[TWRInspectionFinding] = []
    linked_blocks_checked = 0
    relative_rows_checked = 0

    for period_name, period_result in response.results_by_period.items():
        relative_block = period_result.relative_performance
        portfolio_block = period_result.portfolio
        benchmark_block = period_result.benchmark

        findings.extend(
            _check_benchmark_relative_pairing(
                period_name=period_name,
                benchmark_block=benchmark_block,
                relative_block=relative_block,
            )
        )

        if benchmark_block is not None and relative_block is not None:
            relative_rows_checked += _count_breakdown_rows(relative_block)
            findings.extend(
                _check_relative_block(
                    period_name=period_name,
                    portfolio_block=portfolio_block,
                    benchmark_block=benchmark_block,
                    relative_block=relative_block,
                )
            )

        linked_blocks_checked += 1
        findings.extend(
            _check_block_linking(
                period_name=period_name,
                block_name="portfolio",
                owner_repo="lotus-performance",
                analytics_block=portfolio_block,
            )
        )
        if benchmark_block is not None:
            linked_blocks_checked += 1
            findings.extend(
                _check_block_linking(
                    period_name=period_name,
                    block_name="benchmark",
                    owner_repo="lotus-performance",
                    analytics_block=benchmark_block,
                )
            )

    return CalculationConsistencyCheckResult(
        findings=findings,
        evidence_summary={
            "period_count": len(response.results_by_period),
            "linked_blocks_checked": linked_blocks_checked,
            "relative_rows_checked": relative_rows_checked,
            "consistency_findings": len(findings),
        },
    )


def _count_breakdown_rows(analytics_block: ComparativeAnalyticsBlock) -> int:
    return sum(len(items) for items in analytics_block.breakdowns.values())


def _check_benchmark_relative_pairing(
    *,
    period_name: str,
    benchmark_block: ComparativeAnalyticsBlock | None,
    relative_block: ComparativeAnalyticsBlock | None,
) -> list[TWRInspectionFinding]:
    if benchmark_block is None and relative_block is None:
        return []
    if benchmark_block is None:
        return [
            _build_finding(
                code="RELATIVE_PERFORMANCE_BENCHMARK_BLOCK_MISSING",
                period_name=period_name,
                scope="relative_performance",
                summary="Relative-performance block is present without the benchmark block required to validate it.",
                evidence={"benchmark_present": False, "relative_performance_present": True},
            )
        ]
    if relative_block is None:
        return [
            _build_finding(
                code="BENCHMARK_RELATIVE_PERFORMANCE_BLOCK_MISSING",
                period_name=period_name,
                scope="benchmark",
                summary="Benchmark block is present without the relative-performance block required by the TWR benchmark contract.",
                evidence={"benchmark_present": True, "relative_performance_present": False},
            )
        ]
    return []


def _check_relative_block(
    *,
    period_name: str,
    portfolio_block: ComparativeAnalyticsBlock,
    benchmark_block: ComparativeAnalyticsBlock,
    relative_block: ComparativeAnalyticsBlock,
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []
    findings.extend(
        _compare_return_values(
            code="RELATIVE_PERFORMANCE_SUMMARY_MISMATCH",
            period_name=period_name,
            scope="summary.period_return",
            expected=_subtract_return_values(
                portfolio_block.summary.period_return,
                benchmark_block.summary.period_return,
            ),
            actual=relative_block.summary.period_return,
        )
    )
    if (
        portfolio_block.summary.cumulative_return is not None
        and benchmark_block.summary.cumulative_return is not None
        and relative_block.summary.cumulative_return is not None
    ):
        findings.extend(
            _compare_return_values(
                code="RELATIVE_PERFORMANCE_CUMULATIVE_MISMATCH",
                period_name=period_name,
                scope="summary.cumulative_return",
                expected=_subtract_return_values(
                    portfolio_block.summary.cumulative_return,
                    benchmark_block.summary.cumulative_return,
                ),
                actual=relative_block.summary.cumulative_return,
            )
        )
    for frequency, relative_items in relative_block.breakdowns.items():
        portfolio_items = portfolio_block.breakdowns.get(frequency, [])
        benchmark_items = benchmark_block.breakdowns.get(frequency, [])
        if len(relative_items) != len(portfolio_items) or len(relative_items) != len(benchmark_items):
            findings.append(
                _build_finding(
                    code="RELATIVE_BREAKDOWN_CARDINALITY_MISMATCH",
                    period_name=period_name,
                    scope=f"breakdowns.{frequency.value}",
                    summary="Relative-performance breakdown cardinality does not match portfolio and benchmark blocks.",
                    evidence={
                        "relative_count": len(relative_items),
                        "portfolio_count": len(portfolio_items),
                        "benchmark_count": len(benchmark_items),
                    },
                )
            )
            continue
        for relative_item, portfolio_item, benchmark_item in zip(relative_items, portfolio_items, benchmark_items):
            row_scope = f"breakdowns.{frequency.value}.{relative_item.period}"
            alignment_mismatch = _find_breakdown_alignment_mismatch(
                relative_item=relative_item,
                portfolio_item=portfolio_item,
                benchmark_item=benchmark_item,
            )
            if alignment_mismatch is not None:
                findings.append(
                    _build_finding(
                        code="RELATIVE_BREAKDOWN_BUCKET_ALIGNMENT_MISMATCH",
                        period_name=period_name,
                        scope=row_scope,
                        summary="Relative-performance breakdown rows do not align to portfolio and benchmark buckets.",
                        evidence=alignment_mismatch,
                    )
                )
                continue
            findings.extend(
                _compare_return_values(
                    code="RELATIVE_BREAKDOWN_PERIOD_MISMATCH",
                    period_name=period_name,
                    scope=f"{row_scope}.period_return",
                    expected=_subtract_return_values(portfolio_item.period_return, benchmark_item.period_return),
                    actual=relative_item.period_return,
                )
            )
            if (
                relative_item.cumulative_return is not None
                and portfolio_item.cumulative_return is not None
                and benchmark_item.cumulative_return is not None
            ):
                findings.extend(
                    _compare_return_values(
                        code="RELATIVE_BREAKDOWN_CUMULATIVE_MISMATCH",
                        period_name=period_name,
                        scope=f"{row_scope}.cumulative_return",
                        expected=_subtract_return_values(
                            portfolio_item.cumulative_return,
                            benchmark_item.cumulative_return,
                        ),
                        actual=relative_item.cumulative_return,
                    )
                )
    return findings


def _find_breakdown_alignment_mismatch(
    *,
    relative_item: ComparativeBreakdownItem,
    portfolio_item: ComparativeBreakdownItem,
    benchmark_item: ComparativeBreakdownItem,
) -> dict[str, object] | None:
    relative_bucket = _breakdown_bucket_identity(relative_item)
    portfolio_bucket = _breakdown_bucket_identity(portfolio_item)
    benchmark_bucket = _breakdown_bucket_identity(benchmark_item)
    if relative_bucket == portfolio_bucket == benchmark_bucket:
        return None
    return {
        "relative_bucket": relative_bucket,
        "portfolio_bucket": portfolio_bucket,
        "benchmark_bucket": benchmark_bucket,
    }


def _breakdown_bucket_identity(item: ComparativeBreakdownItem) -> dict[str, str]:
    return {
        "period": item.period,
        "period_start": item.period_start.isoformat(),
        "period_end": item.period_end.isoformat(),
    }


def _check_block_linking(
    *,
    period_name: str,
    block_name: str,
    owner_repo: str,
    analytics_block: ComparativeAnalyticsBlock,
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []
    for frequency, items in analytics_block.breakdowns.items():
        if len(items) <= 1:
            continue
        linked_return = _link_returns(item.period_return.base for item in items)
        actual_return = analytics_block.summary.period_return.base
        if not isclose(linked_return, actual_return, abs_tol=_ABS_TOLERANCE):
            findings.append(
                TWRInspectionFinding(
                    code=f"{block_name.upper()}_BREAKDOWN_LINK_MISMATCH",
                    severity="high",
                    category="math_consistency",
                    owner_repo=owner_repo,
                    summary=f"{block_name.capitalize()} breakdowns do not geometrically link to the served summary return.",
                    explanation=(
                        f"The {block_name} {frequency.value} breakdowns for period {period_name} compound to "
                        f"{linked_return:.10f}, while the served summary return is {actual_return:.10f}."
                    ),
                    recommended_action="Inspect TWR response construction and breakdown-linking logic in lotus-performance.",
                    evidence={
                        "period": period_name,
                        "frequency": frequency.value,
                        "linked_return_base": linked_return,
                        "summary_return_base": actual_return,
                        "bucket_count": len(items),
                    },
                )
            )
    return findings


def _compare_return_values(
    *,
    code: str,
    period_name: str,
    scope: str,
    expected: ComparativeReturnValue,
    actual: ComparativeReturnValue,
) -> list[TWRInspectionFinding]:
    mismatches: dict[str, tuple[float | None, float | None]] = {}
    for component in ("base", "local", "fx"):
        expected_value = getattr(expected, component)
        actual_value = getattr(actual, component)
        if expected_value is None and actual_value is None:
            continue
        if (
            expected_value is None
            or actual_value is None
            or not isclose(
                expected_value,
                actual_value,
                abs_tol=_ABS_TOLERANCE,
            )
        ):
            mismatches[component] = (expected_value, actual_value)
    if not mismatches:
        return []
    return [
        _build_finding(
            code=code,
            period_name=period_name,
            scope=scope,
            summary="Relative-performance arithmetic does not match portfolio minus benchmark.",
            evidence={
                "mismatches": {
                    component: {"expected": values[0], "actual": values[1]} for component, values in mismatches.items()
                }
            },
        )
    ]


def _subtract_return_values(
    portfolio_value: ComparativeReturnValue,
    benchmark_value: ComparativeReturnValue,
) -> ComparativeReturnValue:
    return ComparativeReturnValue(
        base=portfolio_value.base - benchmark_value.base,
        local=(
            None
            if portfolio_value.local is None or benchmark_value.local is None
            else portfolio_value.local - benchmark_value.local
        ),
        fx=(
            None
            if portfolio_value.fx is None or benchmark_value.fx is None
            else portfolio_value.fx - benchmark_value.fx
        ),
    )


def _link_returns(values: Iterable[float]) -> float:  # monetary-float-allow
    running = 1.0
    for value in values:
        running *= 1 + (value / 100.0)
    return (running - 1) * 100.0


def _build_finding(
    *,
    code: str,
    period_name: str,
    scope: str,
    summary: str,
    evidence: dict[str, object],
) -> TWRInspectionFinding:
    return TWRInspectionFinding(
        code=code,
        severity="high",
        category="math_consistency",
        owner_repo="lotus-performance",
        summary=summary,
        explanation=f"Calculation-consistency check failed for {period_name} at {scope}.",
        recommended_action="Inspect TWR calculation and response assembly in lotus-performance.",
        evidence={
            "period": period_name,
            "scope": scope,
            **evidence,
        },
    )
