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
    TWRDailyCalculationEvidence,
)
from common.enums import Frequency

_ABS_TOLERANCE = 1e-6


@dataclass(frozen=True)
class CalculationConsistencyCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]


@dataclass(frozen=True)
class PeriodCalculationConsistencyResult:
    findings: list[TWRInspectionFinding]
    linked_blocks_checked: int
    relative_rows_checked: int
    daily_evidence_rows_checked: int


@dataclass(frozen=True)
class RelativePairingFindingContract:
    code: str
    scope: str
    summary: str
    evidence: dict[str, bool]


@dataclass(frozen=True)
class DailyEvidenceExpectedSemantics:
    linkability_status: str
    episode_status: str
    required_reason_codes: set[str]
    required_warnings: set[str]


@dataclass(frozen=True)
class DailyEvidenceExpectedValues:
    signed_adjusted_capital: float
    adjusted_capital: float
    external_inflows: float
    external_outflows: float
    daily_return: float | None  # monetary-float-allow


@dataclass(frozen=True)
class DailyEvidenceExpectedFlows:
    external_inflows: float
    external_outflows: float


_RELATIVE_PAIRING_FINDING_CONTRACTS: dict[tuple[bool, bool], RelativePairingFindingContract] = {
    (False, True): RelativePairingFindingContract(
        code="RELATIVE_PERFORMANCE_BENCHMARK_BLOCK_MISSING",
        scope="relative_performance",
        summary="Relative-performance block is present without the benchmark block required to validate it.",
        evidence={"benchmark_present": False, "relative_performance_present": True},
    ),
    (True, False): RelativePairingFindingContract(
        code="BENCHMARK_RELATIVE_PERFORMANCE_BLOCK_MISSING",
        scope="benchmark",
        summary="Benchmark block is present without the relative-performance block required by the TWR benchmark contract.",
        evidence={"benchmark_present": True, "relative_performance_present": False},
    ),
}


def run_twr_calculation_consistency_checks(response: PerformanceResponse) -> CalculationConsistencyCheckResult:
    findings: list[TWRInspectionFinding] = []
    linked_blocks_checked = 0
    relative_rows_checked = 0
    daily_evidence_rows_checked = 0

    for period_name, period_result in response.results_by_period.items():
        period_consistency = _check_period_calculation_consistency(
            period_name=period_name,
            portfolio_block=period_result.portfolio,
            benchmark_block=period_result.benchmark,
            relative_block=period_result.relative_performance,
        )
        findings.extend(period_consistency.findings)
        linked_blocks_checked += period_consistency.linked_blocks_checked
        relative_rows_checked += period_consistency.relative_rows_checked
        daily_evidence_rows_checked += period_consistency.daily_evidence_rows_checked

    return CalculationConsistencyCheckResult(
        findings=findings,
        evidence_summary={
            "period_count": len(response.results_by_period),
            "linked_blocks_checked": linked_blocks_checked,
            "relative_rows_checked": relative_rows_checked,
            "daily_calculation_evidence_rows_checked": daily_evidence_rows_checked,
            "consistency_findings": len(findings),
        },
    )


def _check_period_calculation_consistency(
    *,
    period_name: str,
    portfolio_block: ComparativeAnalyticsBlock,
    benchmark_block: ComparativeAnalyticsBlock | None,
    relative_block: ComparativeAnalyticsBlock | None,
) -> PeriodCalculationConsistencyResult:
    findings = _check_benchmark_relative_pairing(
        period_name=period_name,
        benchmark_block=benchmark_block,
        relative_block=relative_block,
    )
    linked_blocks_checked = 1
    relative_rows_checked = 0

    if benchmark_block is not None and relative_block is not None:
        relative_rows_checked = _count_breakdown_rows(relative_block)
        findings.extend(
            _check_relative_block(
                period_name=period_name,
                portfolio_block=portfolio_block,
                benchmark_block=benchmark_block,
                relative_block=relative_block,
            )
        )

    findings.extend(
        _check_block_linking(
            period_name=period_name,
            block_name="portfolio",
            owner_repo="lotus-performance",
            analytics_block=portfolio_block,
        )
    )
    evidence_rows_checked, evidence_findings = _check_portfolio_daily_calculation_evidence(
        period_name=period_name,
        portfolio_block=portfolio_block,
    )
    findings.extend(evidence_findings)

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

    return PeriodCalculationConsistencyResult(
        findings=findings,
        linked_blocks_checked=linked_blocks_checked,
        relative_rows_checked=relative_rows_checked,
        daily_evidence_rows_checked=evidence_rows_checked,
    )


def _count_breakdown_rows(analytics_block: ComparativeAnalyticsBlock) -> int:
    return sum(len(items) for items in analytics_block.breakdowns.values())


def _check_benchmark_relative_pairing(
    *,
    period_name: str,
    benchmark_block: ComparativeAnalyticsBlock | None,
    relative_block: ComparativeAnalyticsBlock | None,
) -> list[TWRInspectionFinding]:
    contract = _RELATIVE_PAIRING_FINDING_CONTRACTS.get((benchmark_block is not None, relative_block is not None))
    if contract is None:
        return []
    return [
        _build_finding(
            code=contract.code,
            period_name=period_name,
            scope=contract.scope,
            summary=contract.summary,
            evidence=dict(contract.evidence),
        )
    ]


def _check_relative_block(
    *,
    period_name: str,
    portfolio_block: ComparativeAnalyticsBlock,
    benchmark_block: ComparativeAnalyticsBlock,
    relative_block: ComparativeAnalyticsBlock,
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []
    findings.extend(
        _check_relative_summary(
            period_name=period_name,
            portfolio_block=portfolio_block,
            benchmark_block=benchmark_block,
            relative_block=relative_block,
        )
    )
    for frequency, relative_items in relative_block.breakdowns.items():
        findings.extend(
            _check_relative_breakdown_frequency(
                period_name=period_name,
                frequency=frequency,
                portfolio_items=portfolio_block.breakdowns.get(frequency, []),
                benchmark_items=benchmark_block.breakdowns.get(frequency, []),
                relative_items=relative_items,
            )
        )
    return findings


def _check_relative_summary(
    *,
    period_name: str,
    portfolio_block: ComparativeAnalyticsBlock,
    benchmark_block: ComparativeAnalyticsBlock,
    relative_block: ComparativeAnalyticsBlock,
) -> list[TWRInspectionFinding]:
    findings = _compare_return_values(
        code="RELATIVE_PERFORMANCE_SUMMARY_MISMATCH",
        period_name=period_name,
        scope="summary.period_return",
        expected=_subtract_return_values(
            portfolio_block.summary.period_return,
            benchmark_block.summary.period_return,
        ),
        actual=relative_block.summary.period_return,
    )
    if (
        portfolio_block.summary.cumulative_return is None
        or benchmark_block.summary.cumulative_return is None
        or relative_block.summary.cumulative_return is None
    ):
        return findings
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
    return findings


def _check_relative_breakdown_frequency(
    *,
    period_name: str,
    frequency: Frequency,
    portfolio_items: list[ComparativeBreakdownItem],
    benchmark_items: list[ComparativeBreakdownItem],
    relative_items: list[ComparativeBreakdownItem],
) -> list[TWRInspectionFinding]:
    cardinality_finding = _relative_breakdown_cardinality_finding(
        period_name=period_name,
        frequency=frequency,
        portfolio_items=portfolio_items,
        benchmark_items=benchmark_items,
        relative_items=relative_items,
    )
    if cardinality_finding is not None:
        return [cardinality_finding]

    findings: list[TWRInspectionFinding] = []
    for relative_item, portfolio_item, benchmark_item in zip(relative_items, portfolio_items, benchmark_items):
        findings.extend(
            _check_relative_breakdown_item(
                period_name=period_name,
                frequency=frequency,
                relative_item=relative_item,
                portfolio_item=portfolio_item,
                benchmark_item=benchmark_item,
            )
        )
    return findings


def _relative_breakdown_cardinality_finding(
    *,
    period_name: str,
    frequency: Frequency,
    portfolio_items: list[ComparativeBreakdownItem],
    benchmark_items: list[ComparativeBreakdownItem],
    relative_items: list[ComparativeBreakdownItem],
) -> TWRInspectionFinding | None:
    if len(relative_items) == len(portfolio_items) == len(benchmark_items):
        return None
    return _build_finding(
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


def _check_relative_breakdown_item(
    *,
    period_name: str,
    frequency: Frequency,
    relative_item: ComparativeBreakdownItem,
    portfolio_item: ComparativeBreakdownItem,
    benchmark_item: ComparativeBreakdownItem,
) -> list[TWRInspectionFinding]:
    row_scope = f"breakdowns.{frequency.value}.{relative_item.period}"
    alignment_mismatch = _find_breakdown_alignment_mismatch(
        relative_item=relative_item,
        portfolio_item=portfolio_item,
        benchmark_item=benchmark_item,
    )
    if alignment_mismatch is not None:
        return [
            _build_finding(
                code="RELATIVE_BREAKDOWN_BUCKET_ALIGNMENT_MISMATCH",
                period_name=period_name,
                scope=row_scope,
                summary="Relative-performance breakdown rows do not align to portfolio and benchmark buckets.",
                evidence=alignment_mismatch,
            )
        ]

    findings = _compare_return_values(
        code="RELATIVE_BREAKDOWN_PERIOD_MISMATCH",
        period_name=period_name,
        scope=f"{row_scope}.period_return",
        expected=_subtract_return_values(portfolio_item.period_return, benchmark_item.period_return),
        actual=relative_item.period_return,
    )
    cumulative_comparison = _relative_breakdown_cumulative_comparison(
        relative_item=relative_item,
        portfolio_item=portfolio_item,
        benchmark_item=benchmark_item,
    )
    if cumulative_comparison is None:
        return findings
    findings.extend(
        _compare_return_values(
            code="RELATIVE_BREAKDOWN_CUMULATIVE_MISMATCH",
            period_name=period_name,
            scope=f"{row_scope}.cumulative_return",
            expected=cumulative_comparison[0],
            actual=cumulative_comparison[1],
        )
    )
    return findings


def _relative_breakdown_cumulative_comparison(
    *,
    relative_item: ComparativeBreakdownItem,
    portfolio_item: ComparativeBreakdownItem,
    benchmark_item: ComparativeBreakdownItem,
) -> tuple[ComparativeReturnValue, ComparativeReturnValue] | None:
    if (
        relative_item.cumulative_return is None
        or portfolio_item.cumulative_return is None
        or benchmark_item.cumulative_return is None
    ):
        return None
    return (
        _subtract_return_values(
            portfolio_item.cumulative_return,
            benchmark_item.cumulative_return,
        ),
        relative_item.cumulative_return,
    )


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
        finding = _block_linking_mismatch_for_frequency(
            period_name=period_name,
            block_name=block_name,
            owner_repo=owner_repo,
            frequency=frequency,
            items=items,
            summary_return=analytics_block.summary.period_return.base,
        )
        if finding is not None:
            findings.append(finding)
    return findings


def _block_linking_mismatch_for_frequency(
    *,
    period_name: str,
    block_name: str,
    owner_repo: str,
    frequency: Frequency,
    items: list[ComparativeBreakdownItem],
    summary_return: float,  # monetary-float-allow
) -> TWRInspectionFinding | None:
    if len(items) <= 1:
        return None
    linked_return = _link_returns(item.period_return.base for item in items)
    if isclose(linked_return, summary_return, abs_tol=_ABS_TOLERANCE):
        return None
    return _block_linking_mismatch_finding(
        period_name=period_name,
        block_name=block_name,
        owner_repo=owner_repo,
        frequency=frequency,
        linked_return=linked_return,
        actual_return=summary_return,
        bucket_count=len(items),
    )


def _block_linking_mismatch_finding(
    *,
    period_name: str,
    block_name: str,
    owner_repo: str,
    frequency: Frequency,
    linked_return: float,  # monetary-float-allow
    actual_return: float,  # monetary-float-allow
    bucket_count: int,
) -> TWRInspectionFinding:
    return TWRInspectionFinding(
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
            "bucket_count": bucket_count,
        },
    )


def _check_portfolio_daily_calculation_evidence(
    *,
    period_name: str,
    portfolio_block: ComparativeAnalyticsBlock,
) -> tuple[int, list[TWRInspectionFinding]]:
    findings: list[TWRInspectionFinding] = []
    rows_checked = 0
    for frequency, items in portfolio_block.breakdowns.items():
        if frequency.value != "daily":
            continue
        for item in items:
            item_rows_checked, item_findings = _check_daily_breakdown_calculation_evidence(
                period_name=period_name,
                frequency=frequency,
                item=item,
            )
            rows_checked += item_rows_checked
            findings.extend(item_findings)
    return rows_checked, findings


def _check_daily_breakdown_calculation_evidence(
    *,
    period_name: str,
    frequency: Frequency,
    item: ComparativeBreakdownItem,
) -> tuple[int, list[TWRInspectionFinding]]:
    evidence = item.calculation_evidence
    if evidence is None:
        return 0, []
    mismatches = _daily_calculation_evidence_mismatches(evidence=evidence, item=item)
    if not mismatches:
        return 1, []
    scope = f"breakdowns.{frequency.value}.{item.period}.calculation_evidence"
    return 1, [
        _build_finding(
            code="DAILY_CALCULATION_EVIDENCE_MISMATCH",
            period_name=period_name,
            scope=scope,
            summary="Daily TWR calculation evidence does not reconcile to its served return contract.",
            evidence={
                "daily_period": item.period,
                "mismatches": mismatches,
                "calculation_method": evidence.calculation_method,
                "denominator_basis": evidence.denominator_basis,
            },
        )
    ]


def _expected_daily_calculation_values(evidence: TWRDailyCalculationEvidence) -> DailyEvidenceExpectedValues:
    adjusted_capital = evidence.begin_mv + evidence.bod_cf
    expected_flows = _expected_daily_external_flows(evidence)
    return DailyEvidenceExpectedValues(
        signed_adjusted_capital=adjusted_capital,
        adjusted_capital=abs(adjusted_capital),
        external_inflows=expected_flows.external_inflows,
        external_outflows=expected_flows.external_outflows,
        daily_return=_expected_daily_return(evidence),
    )


def _expected_daily_external_flows(evidence: TWRDailyCalculationEvidence) -> DailyEvidenceExpectedFlows:
    flows = _daily_external_flow_values(evidence)
    return DailyEvidenceExpectedFlows(
        external_inflows=sum(_external_inflow_value(value) for value in flows),
        external_outflows=sum(_external_outflow_value(value) for value in flows),
    )


def _daily_external_flow_values(evidence: TWRDailyCalculationEvidence) -> tuple[float, float]:  # monetary-float-allow
    return (evidence.bod_cf, evidence.eod_cf)


def _external_inflow_value(value: float) -> float:  # monetary-float-allow
    return max(value, 0.0)


def _external_outflow_value(value: float) -> float:  # monetary-float-allow
    return abs(min(value, 0.0))


def _expected_daily_return(evidence: TWRDailyCalculationEvidence) -> float | None:  # monetary-float-allow
    if evidence.status != "calculated" or evidence.adjusted_capital == 0:
        return None
    return evidence.performance_pnl / evidence.adjusted_capital * 100


def _daily_calculation_evidence_mismatches(
    *,
    evidence: TWRDailyCalculationEvidence,
    item: ComparativeBreakdownItem,
) -> dict[str, dict[str, object] | object]:
    expected = _expected_daily_calculation_values(evidence)
    mismatches: dict[str, dict[str, object] | object] = {}
    mismatches.update(
        _daily_calculation_numeric_mismatches(
            expected=expected,
            evidence=evidence,
            item=item,
        )
    )
    status_mismatch = _daily_zero_capital_status_mismatch(evidence)
    if status_mismatch is not None:
        mismatches["status"] = status_mismatch
    semantic_mismatches = _daily_evidence_semantic_mismatches(evidence)
    if semantic_mismatches:
        mismatches["semantics"] = semantic_mismatches
    return mismatches


def _daily_calculation_numeric_mismatches(
    *,
    expected: DailyEvidenceExpectedValues,
    evidence: TWRDailyCalculationEvidence,
    item: ComparativeBreakdownItem,
) -> dict[str, dict[str, object]]:
    mismatches: dict[str, dict[str, object]] = {}
    _record_numeric_mismatch(
        mismatches=mismatches,
        field="signed_adjusted_capital",
        expected=expected.signed_adjusted_capital,
        actual=evidence.signed_adjusted_capital,
    )
    _record_numeric_mismatch(
        mismatches=mismatches,
        field="adjusted_capital",
        expected=expected.adjusted_capital,
        actual=evidence.adjusted_capital,
    )
    _record_numeric_mismatch(
        mismatches=mismatches,
        field="external_inflows",
        expected=expected.external_inflows,
        actual=evidence.external_inflows,
    )
    _record_numeric_mismatch(
        mismatches=mismatches,
        field="external_outflows",
        expected=expected.external_outflows,
        actual=evidence.external_outflows,
    )
    if expected.daily_return is not None:
        _record_numeric_mismatch(
            mismatches=mismatches,
            field="daily_return",
            expected=expected.daily_return,
            actual=evidence.daily_return,
        )
        _record_numeric_mismatch(
            mismatches=mismatches,
            field="period_return.base",
            expected=evidence.daily_return,
            actual=item.period_return.base,
        )
    return mismatches


def _daily_zero_capital_status_mismatch(evidence: TWRDailyCalculationEvidence) -> dict[str, object] | None:
    if evidence.status != "calculated" or evidence.adjusted_capital != 0:
        return None
    return {
        "expected": "not_calculated",
        "actual": evidence.status,
        "reason": "zero_adjusted_capital",
    }


def _daily_evidence_semantic_mismatches(evidence: TWRDailyCalculationEvidence) -> dict[str, object]:
    expected = _expected_daily_evidence_semantics(evidence)
    mismatches: dict[str, object] = {}
    mismatches.update(_daily_status_semantic_mismatches(expected=expected, evidence=evidence))
    mismatches.update(_daily_required_semantic_mismatches(expected=expected, evidence=evidence))
    return mismatches


def _daily_status_semantic_mismatches(
    *,
    expected: DailyEvidenceExpectedSemantics,
    evidence: TWRDailyCalculationEvidence,
) -> dict[str, dict[str, object]]:
    mismatches: dict[str, dict[str, object]] = {}
    if evidence.linkability_status != expected.linkability_status:
        mismatches["linkability_status"] = {
            "expected": expected.linkability_status,
            "actual": evidence.linkability_status,
        }
    if evidence.episode_status != expected.episode_status:
        mismatches["episode_status"] = {
            "expected": expected.episode_status,
            "actual": evidence.episode_status,
        }
    return mismatches


def _daily_required_semantic_mismatches(
    *,
    expected: DailyEvidenceExpectedSemantics,
    evidence: TWRDailyCalculationEvidence,
) -> dict[str, list[str]]:
    mismatches: dict[str, list[str]] = {}
    reason_codes = set(evidence.reason_codes)
    missing_reason_codes = sorted(expected.required_reason_codes - reason_codes)
    if missing_reason_codes:
        mismatches["missing_reason_codes"] = missing_reason_codes

    warnings = set(evidence.warnings)
    missing_warnings = sorted(expected.required_warnings - warnings)
    if missing_warnings:
        mismatches["missing_warnings"] = missing_warnings
    return mismatches


def _expected_daily_evidence_semantics(evidence: TWRDailyCalculationEvidence) -> DailyEvidenceExpectedSemantics:
    reason_codes = set(evidence.reason_codes)
    required_reason_codes = {"FLOW_NEUTRALIZED_DAILY_RETURN"}
    required_warnings: set[str] = set()
    linkability_status = _expected_daily_capital_linkability_status(
        evidence,
        required_reason_codes=required_reason_codes,
        required_warnings=required_warnings,
    )
    linkability_status, episode_status = _expected_daily_period_statuses(
        reason_codes=reason_codes,
        linkability_status=linkability_status,
        required_warnings=required_warnings,
    )
    _add_daily_market_event_reason_codes(
        evidence,
        required_reason_codes=required_reason_codes,
    )
    linkability_status = _expected_daily_return_linkability_status(
        evidence,
        linkability_status=linkability_status,
        required_reason_codes=required_reason_codes,
        required_warnings=required_warnings,
    )

    return DailyEvidenceExpectedSemantics(
        linkability_status=linkability_status,
        episode_status=episode_status,
        required_reason_codes=required_reason_codes,
        required_warnings=required_warnings,
    )


def _expected_daily_capital_linkability_status(
    evidence: TWRDailyCalculationEvidence,
    *,
    required_reason_codes: set[str],
    required_warnings: set[str],
) -> str:
    if evidence.status == "not_calculated":
        linkability_status = "not_calculated"
    else:
        linkability_status = "linkable"

    if evidence.adjusted_capital == 0:
        required_reason_codes.add("ZERO_ADJUSTED_CAPITAL")
        required_warnings.add("ZERO_ADJUSTED_CAPITAL")
        return "not_calculated"
    if evidence.signed_adjusted_capital < 0:
        required_reason_codes.add("NEGATIVE_ADJUSTED_CAPITAL_INPUT")
        required_warnings.add("NEGATIVE_ADJUSTED_CAPITAL_INPUT")
    elif evidence.adjusted_capital < 1e-8:
        required_reason_codes.add("NEAR_ZERO_ADJUSTED_CAPITAL")
        required_warnings.add("NEAR_ZERO_ADJUSTED_CAPITAL")
    return linkability_status


def _expected_daily_period_statuses(
    *,
    reason_codes: set[str],
    linkability_status: str,
    required_warnings: set[str],
) -> tuple[str, str]:
    episode_status = "open"
    if "BEFORE_EFFECTIVE_PERIOD_START" in reason_codes:
        required_warnings.add("BEFORE_EFFECTIVE_PERIOD_START")
        linkability_status = "not_calculated"
        episode_status = "not_in_period"

    if "RESET_DAY" in reason_codes:
        episode_status = "reset_boundary"
        if linkability_status == "linkable":
            linkability_status = "reset_boundary"
    if "NO_INVESTMENT_PERIOD" in reason_codes:
        linkability_status, episode_status = _apply_daily_no_investment_period_status(
            linkability_status=linkability_status,
            episode_status=episode_status,
        )
    return linkability_status, episode_status


def _apply_daily_no_investment_period_status(*, linkability_status: str, episode_status: str) -> tuple[str, str]:
    if episode_status == "open":
        episode_status = "no_investment"
    if linkability_status == "linkable":
        linkability_status = "not_calculated"
    return linkability_status, episode_status


def _add_daily_market_event_reason_codes(
    evidence: TWRDailyCalculationEvidence,
    *,
    required_reason_codes: set[str],
) -> None:
    if evidence.end_mv == 0 and evidence.eod_cf < 0:
        required_reason_codes.add("FULL_WITHDRAWAL_DAY")
    if evidence.begin_mv <= 0 and evidence.bod_cf > 0:
        required_reason_codes.add("REFUNDING_DAY")


def _expected_daily_return_linkability_status(
    evidence: TWRDailyCalculationEvidence,
    *,
    linkability_status: str,
    required_reason_codes: set[str],
    required_warnings: set[str],
) -> str:
    if evidence.daily_return == -100:
        required_reason_codes.add("FULL_LOSS_RETURN")
        required_warnings.add("FULL_LOSS_RETURN")
        if linkability_status == "linkable":
            return "not_linkable"
    elif evidence.daily_return < -100:
        required_reason_codes.add("BELOW_FULL_LOSS_RETURN")
        required_warnings.add("BELOW_FULL_LOSS_RETURN")
        if linkability_status == "linkable":
            return "not_linkable"
    return linkability_status


def _record_numeric_mismatch(
    *,
    mismatches: dict[str, dict[str, object]],
    field: str,
    expected: float,
    actual: float,
) -> None:
    if isclose(expected, actual, abs_tol=_ABS_TOLERANCE):
        return
    mismatches[field] = {"expected": expected, "actual": actual}


def _compare_return_values(
    *,
    code: str,
    period_name: str,
    scope: str,
    expected: ComparativeReturnValue,
    actual: ComparativeReturnValue,
) -> list[TWRInspectionFinding]:
    mismatches = _comparative_return_mismatches(expected=expected, actual=actual)
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


def _comparative_return_mismatches(
    *,
    expected: ComparativeReturnValue,
    actual: ComparativeReturnValue,
) -> dict[str, tuple[float | None, float | None]]:
    mismatches: dict[str, tuple[float | None, float | None]] = {}
    for component in ("base", "local", "fx"):
        expected_value = getattr(expected, component)
        actual_value = getattr(actual, component)
        mismatch = _comparative_return_component_mismatch(
            expected_value=expected_value,
            actual_value=actual_value,
        )
        if mismatch is not None:
            mismatches[component] = mismatch
    return mismatches


def _comparative_return_component_mismatch(
    *,
    expected_value: float | None,  # monetary-float-allow
    actual_value: float | None,  # monetary-float-allow
) -> tuple[float | None, float | None] | None:
    if _comparative_return_components_match(
        expected_value=expected_value,
        actual_value=actual_value,
    ):
        return None
    return expected_value, actual_value


def _comparative_return_components_match(
    *,
    expected_value: float | None,  # monetary-float-allow
    actual_value: float | None,  # monetary-float-allow
) -> bool:
    if expected_value is None and actual_value is None:
        return True
    if expected_value is None or actual_value is None:
        return False
    return isclose(expected_value, actual_value, abs_tol=_ABS_TOLERANCE)


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
