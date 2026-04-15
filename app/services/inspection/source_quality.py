from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.models.inspection_requests import TWRInspectionProfile
from app.models.inspection_responses import TWRInspectionFinding
from app.models.requests import DailyInputData, PerformanceRequest

_EXTREME_MOVE_THRESHOLD_PCT = {
    TWRInspectionProfile.SUPPORT_TRIAGE: 10.0,
    TWRInspectionProfile.CANONICAL_VALIDATION: 10.0,
    TWRInspectionProfile.DEEP_RECONCILIATION: 12.5,
}


@dataclass(frozen=True)
class SourceQualityCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]


def run_source_quality_checks(
    *,
    performance_request: PerformanceRequest,
    inspection_profile: TWRInspectionProfile,
) -> SourceQualityCheckResult:
    findings: list[TWRInspectionFinding] = []
    valuation_points = sorted(performance_request.valuation_points, key=lambda point: point.perf_date)
    weekend_dates = [point.perf_date.isoformat() for point in valuation_points if point.perf_date.weekday() >= 5]
    if weekend_dates:
        findings.append(
            _build_warning_finding(
                code="WEEKEND_OBSERVATIONS_PRESENT",
                category="source_quality",
                summary="Resolved source inputs include weekend observations.",
                explanation="Weekend observations are unusual for standard private-banking TWR source series.",
                evidence={"weekend_dates": weekend_dates, "weekend_count": len(weekend_dates)},
            )
        )

    missing_business_dates = _find_missing_business_dates(valuation_points)
    if missing_business_dates:
        findings.append(
            _build_warning_finding(
                code="BUSINESS_DATE_GAPS_PRESENT",
                category="source_quality",
                summary="Resolved source inputs skip expected business dates.",
                explanation=(
                    "The resolved valuation sequence has business-date gaps between the first and last observation. "
                    "This can be legitimate around market holidays, but it is still a supportability signal."
                ),
                evidence={
                    "missing_business_dates": missing_business_dates[:10],
                    "missing_business_date_count": len(missing_business_dates),
                },
            )
        )

    daily_moves = _calculate_daily_moves(valuation_points)
    largest_abs_daily_move_pct = max((abs(move["return_pct"]) for move in daily_moves), default=0.0)
    threshold = _EXTREME_MOVE_THRESHOLD_PCT[inspection_profile]
    extreme_moves = [move for move in daily_moves if abs(move["return_pct"]) >= threshold]
    if extreme_moves:
        findings.append(
            TWRInspectionFinding(
                code="EXTREME_DAILY_MOVE_DETECTED",
                severity="high",
                category="economic_plausibility",
                owner_repo="lotus-performance",
                summary="Resolved source inputs imply one or more extreme daily moves.",
                explanation=(
                    f"One or more daily moves exceed the {threshold:.2f}% plausibility threshold for "
                    f"{inspection_profile.value}."
                ),
                recommended_action=(
                    "Review the resolved valuation observations, cash-flow classification, and source-economics "
                    "story before treating the TWR result as supportable."
                ),
                evidence={
                    "threshold_pct": threshold,
                    "extreme_moves": extreme_moves[:10],
                },
            )
        )

    return SourceQualityCheckResult(
        findings=findings,
        evidence_summary={
            "valuation_point_count": len(valuation_points),
            "weekend_observation_count": len(weekend_dates),
            "missing_business_date_count": len(missing_business_dates),
            "largest_abs_daily_move_pct": largest_abs_daily_move_pct,
        },
    )


def _calculate_daily_moves(valuation_points: list[DailyInputData]) -> list[dict[str, float | str]]:
    moves: list[dict[str, float | str]] = []
    for point in valuation_points:
        denominator = point.begin_mv + point.bod_cf
        if denominator == 0:
            continue
        numerator = point.end_mv - point.eod_cf - point.mgmt_fees
        return_pct = ((numerator / denominator) - 1.0) * 100.0
        moves.append({"perf_date": point.perf_date.isoformat(), "return_pct": return_pct})
    return moves


def _find_missing_business_dates(valuation_points: list[DailyInputData]) -> list[str]:
    if len(valuation_points) <= 1:
        return []
    expected: list[str] = []
    current = valuation_points[0].perf_date
    last = valuation_points[-1].perf_date
    observed = {point.perf_date.isoformat() for point in valuation_points}
    while current <= last:
        if current.weekday() < 5 and current.isoformat() not in observed:
            expected.append(current.isoformat())
        current += timedelta(days=1)
    return expected


def _build_warning_finding(
    *,
    code: str,
    category: str,
    summary: str,
    explanation: str,
    evidence: dict[str, object],
) -> TWRInspectionFinding:
    return TWRInspectionFinding(
        code=code,
        severity="warning",
        category=category,
        owner_repo="lotus-performance",
        summary=summary,
        explanation=explanation,
        recommended_action="Review the resolved source inputs before relying on supportability conclusions.",
        evidence=evidence,
    )
