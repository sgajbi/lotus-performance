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
_CANONICAL_BALANCED_PORTFOLIO_IDS = frozenset({"PB_SG_GLOBAL_BAL_001"})
_CANONICAL_BALANCED_DAILY_MOVE_THRESHOLD_PCT = 2.0
_CANONICAL_BALANCED_MANDATE_PROFILE = "canonical_balanced_private_banking"
_STALE_SERIES_MIN_OBSERVATIONS = 3
_STALE_SAMPLE_LIMIT = 10


@dataclass(frozen=True)
class SourceQualityCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]
    artifact_payload: dict[str, object]


@dataclass(frozen=True)
class StaleSeriesRun:
    start_date: str
    end_date: str
    observation_count: int
    begin_mv: float
    end_mv: float


@dataclass(frozen=True)
class DailyMoveInputsAssessment:
    daily_moves: list[dict[str, float | str]]
    invalid_capital_bases: list[dict[str, float | str]]


@dataclass(frozen=True)
class MandateDailyMoveProfile:
    name: str
    threshold_pct: float


def run_source_quality_checks(
    *,
    performance_request: PerformanceRequest,
    inspection_profile: TWRInspectionProfile,
) -> SourceQualityCheckResult:
    valuation_points = sorted(performance_request.valuation_points, key=lambda point: point.perf_date)

    weekend_dates = _find_weekend_dates(valuation_points)
    missing_business_dates = _find_missing_business_dates(valuation_points)
    stale_runs = _find_stale_series_runs(valuation_points)
    daily_move_assessment = _assess_daily_move_inputs(valuation_points)
    daily_moves = daily_move_assessment.daily_moves
    invalid_capital_bases = daily_move_assessment.invalid_capital_bases
    largest_abs_daily_move_pct = max((abs(float(move["return_pct"])) for move in daily_moves), default=0.0)
    threshold = _EXTREME_MOVE_THRESHOLD_PCT[inspection_profile]
    extreme_moves = [move for move in daily_moves if abs(float(move["return_pct"])) >= threshold]
    mandate_profile = _resolve_mandate_daily_move_profile(performance_request.portfolio_id)
    mandate_outliers = _find_mandate_daily_move_outliers(
        daily_moves=daily_moves,
        mandate_profile=mandate_profile,
        extreme_threshold_pct=threshold,
    )

    findings = [
        *_build_weekend_findings(weekend_dates),
        *_build_business_gap_findings(missing_business_dates),
        *_build_stale_series_findings(stale_runs),
        *_build_nonpositive_capital_base_findings(invalid_capital_bases),
        *_build_mandate_daily_move_findings(
            mandate_profile=mandate_profile,
            mandate_outliers=mandate_outliers,
        ),
        *_build_extreme_move_findings(
            inspection_profile=inspection_profile,
            threshold=threshold,
            extreme_moves=extreme_moves,
        ),
    ]

    stale_observation_count = sum(run.observation_count for run in stale_runs)
    artifact_payload = {
        "valuation_point_count": len(valuation_points),
        "weekend_observation_count": len(weekend_dates),
        "weekend_dates": weekend_dates[:_STALE_SAMPLE_LIMIT],
        "missing_business_date_count": len(missing_business_dates),
        "missing_business_dates": missing_business_dates[:_STALE_SAMPLE_LIMIT],
        "stale_series_run_count": len(stale_runs),
        "stale_series_observation_count": stale_observation_count,
        "stale_series_min_observations": _STALE_SERIES_MIN_OBSERVATIONS,
        "stale_series_runs": [
            {
                "start_date": run.start_date,
                "end_date": run.end_date,
                "observation_count": run.observation_count,
                "begin_mv": run.begin_mv,
                "end_mv": run.end_mv,
            }
            for run in stale_runs[:_STALE_SAMPLE_LIMIT]
        ],
        "nonpositive_capital_base_count": len(invalid_capital_bases),
        "nonpositive_capital_base_samples": invalid_capital_bases[:_STALE_SAMPLE_LIMIT],
        "largest_abs_daily_move_pct": largest_abs_daily_move_pct,
        "extreme_daily_move_threshold_pct": threshold,
        "extreme_daily_moves": extreme_moves[:_STALE_SAMPLE_LIMIT],
        "mandate_daily_move_profile": mandate_profile.name if mandate_profile else None,
        "mandate_daily_move_threshold_pct": mandate_profile.threshold_pct if mandate_profile else None,
        "mandate_daily_move_outlier_count": len(mandate_outliers),
        "mandate_daily_move_outliers": mandate_outliers[:_STALE_SAMPLE_LIMIT],
    }
    return SourceQualityCheckResult(
        findings=findings,
        evidence_summary={
            "valuation_point_count": len(valuation_points),
            "weekend_observation_count": len(weekend_dates),
            "missing_business_date_count": len(missing_business_dates),
            "stale_series_run_count": len(stale_runs),
            "stale_series_observation_count": stale_observation_count,
            "nonpositive_capital_base_count": len(invalid_capital_bases),
            "largest_abs_daily_move_pct": largest_abs_daily_move_pct,
            "mandate_daily_move_outlier_count": len(mandate_outliers),
        },
        artifact_payload=artifact_payload,
    )


def _find_weekend_dates(valuation_points: list[DailyInputData]) -> list[str]:
    return [point.perf_date.isoformat() for point in valuation_points if point.perf_date.weekday() >= 5]


def _build_weekend_findings(weekend_dates: list[str]) -> list[TWRInspectionFinding]:
    if not weekend_dates:
        return []
    return [
        _build_warning_finding(
            code="WEEKEND_OBSERVATIONS_PRESENT",
            category="source_quality",
            summary="Resolved source inputs include weekend observations.",
            explanation="Weekend observations are unusual for standard private-banking TWR source series.",
            evidence={"weekend_dates": weekend_dates, "weekend_count": len(weekend_dates)},
        )
    ]


def _build_business_gap_findings(missing_business_dates: list[str]) -> list[TWRInspectionFinding]:
    if not missing_business_dates:
        return []
    return [
        _build_warning_finding(
            code="BUSINESS_DATE_GAPS_PRESENT",
            category="source_quality",
            summary="Resolved source inputs skip expected business dates.",
            explanation=(
                "The resolved valuation sequence has business-date gaps between the first and last observation. "
                "This can be legitimate around market holidays, but it is still a supportability signal."
            ),
            evidence={
                "missing_business_dates": missing_business_dates[:_STALE_SAMPLE_LIMIT],
                "missing_business_date_count": len(missing_business_dates),
            },
        )
    ]


def _find_stale_series_runs(valuation_points: list[DailyInputData]) -> list[StaleSeriesRun]:
    stale_runs: list[StaleSeriesRun] = []
    current_run: list[DailyInputData] = []
    current_signature: tuple[float, float, float, float, float] | None = None

    for point in valuation_points:
        signature = _stale_signature(point)
        if current_signature is None or signature != current_signature:
            _append_stale_run_if_needed(stale_runs=stale_runs, run_points=current_run)
            current_run = [point]
            current_signature = signature
            continue
        current_run.append(point)

    _append_stale_run_if_needed(stale_runs=stale_runs, run_points=current_run)
    return stale_runs


def _stale_signature(point: DailyInputData) -> tuple[float, float, float, float, float]:
    return (point.begin_mv, point.end_mv, point.bod_cf, point.eod_cf, point.mgmt_fees)


def _append_stale_run_if_needed(
    *,
    stale_runs: list[StaleSeriesRun],
    run_points: list[DailyInputData],
) -> None:
    if len(run_points) < _STALE_SERIES_MIN_OBSERVATIONS:
        return
    first = run_points[0]
    if first.bod_cf != 0 or first.eod_cf != 0 or first.mgmt_fees != 0:
        return
    stale_runs.append(
        StaleSeriesRun(
            start_date=first.perf_date.isoformat(),
            end_date=run_points[-1].perf_date.isoformat(),
            observation_count=len(run_points),
            begin_mv=first.begin_mv,
            end_mv=first.end_mv,
        )
    )


def _build_stale_series_findings(stale_runs: list[StaleSeriesRun]) -> list[TWRInspectionFinding]:
    if not stale_runs:
        return []
    stale_observation_count = sum(run.observation_count for run in stale_runs)
    return [
        _build_warning_finding(
            code="STALE_VALUATION_SERIES_DETECTED",
            category="source_quality",
            summary="Resolved source inputs repeat an unchanged valuation state across multiple observations.",
            explanation=(
                "The inspector found repeated valuation observations with unchanged begin/end market values and "
                "zero cash-flow or fee activity. That bounded pattern is a stale-series signal rather than a "
                "proof of economic flatness."
            ),
            evidence={
                "stale_series_run_count": len(stale_runs),
                "stale_series_observation_count": stale_observation_count,
                "stale_series_runs": [
                    {
                        "start_date": run.start_date,
                        "end_date": run.end_date,
                        "observation_count": run.observation_count,
                        "begin_mv": run.begin_mv,
                        "end_mv": run.end_mv,
                    }
                    for run in stale_runs[:_STALE_SAMPLE_LIMIT]
                ],
                "stale_series_min_observations": _STALE_SERIES_MIN_OBSERVATIONS,
            },
        )
    ]


def _build_nonpositive_capital_base_findings(
    invalid_capital_bases: list[dict[str, float | str]],
) -> list[TWRInspectionFinding]:
    if not invalid_capital_bases:
        return []
    return [
        TWRInspectionFinding(
            code="NONPOSITIVE_DAILY_CAPITAL_BASE_DETECTED",
            severity="high",
            category="economic_plausibility",
            owner_repo="lotus-performance",
            summary="Resolved source inputs contain one or more observations with a nonpositive daily capital base.",
            explanation=(
                "For one or more observations, `begin_mv + bod_cf` is zero or negative. That makes the daily "
                "capital base nonpositive, so the inspector cannot interpret daily move plausibility normally."
            ),
            recommended_action=(
                "Review the resolved beginning market value and beginning cash-flow classification before "
                "treating the TWR result as supportable."
            ),
            evidence={
                "nonpositive_capital_base_count": len(invalid_capital_bases),
                "invalid_capital_base_samples": invalid_capital_bases[:_STALE_SAMPLE_LIMIT],
            },
        )
    ]


def _resolve_mandate_daily_move_profile(portfolio_id: str) -> MandateDailyMoveProfile | None:
    if portfolio_id not in _CANONICAL_BALANCED_PORTFOLIO_IDS:
        return None
    return MandateDailyMoveProfile(
        name=_CANONICAL_BALANCED_MANDATE_PROFILE,
        threshold_pct=_CANONICAL_BALANCED_DAILY_MOVE_THRESHOLD_PCT,
    )


def _find_mandate_daily_move_outliers(
    *,
    daily_moves: list[dict[str, float | str]],
    mandate_profile: MandateDailyMoveProfile | None,
    extreme_threshold_pct: float,
) -> list[dict[str, float | str]]:
    if mandate_profile is None:
        return []
    threshold_pct = mandate_profile.threshold_pct
    return [move for move in daily_moves if threshold_pct <= abs(float(move["return_pct"])) < extreme_threshold_pct]


def _build_mandate_daily_move_findings(
    *,
    mandate_profile: MandateDailyMoveProfile | None,
    mandate_outliers: list[dict[str, float | str]],
) -> list[TWRInspectionFinding]:
    if mandate_profile is None or not mandate_outliers:
        return []
    return [
        TWRInspectionFinding(
            code="MANDATE_DAILY_MOVE_OUTLIER_DETECTED",
            severity="warning",
            category="economic_plausibility",
            owner_repo="lotus-performance",
            summary="Resolved source inputs imply daily moves outside the bounded mandate plausibility band.",
            explanation=(
                f"One or more daily moves exceed the {mandate_profile.threshold_pct:.2f}% warning threshold for "
                f"{mandate_profile.name}, while remaining below the generic extreme-move threshold."
            ),
            recommended_action=(
                "Review the valuation, fee, and external cash-flow story for the sampled dates before "
                "using the result as canonical support evidence."
            ),
            evidence={
                "mandate_profile": mandate_profile.name,
                "threshold_pct": mandate_profile.threshold_pct,
                "outlier_count": len(mandate_outliers),
                "outliers": mandate_outliers[:_STALE_SAMPLE_LIMIT],
            },
        )
    ]


def _build_extreme_move_findings(
    *,
    inspection_profile: TWRInspectionProfile,
    threshold: float,
    extreme_moves: list[dict[str, float | str]],
) -> list[TWRInspectionFinding]:
    if not extreme_moves:
        return []
    return [
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
                "extreme_moves": extreme_moves[:_STALE_SAMPLE_LIMIT],
            },
        )
    ]


def _assess_daily_move_inputs(valuation_points: list[DailyInputData]) -> DailyMoveInputsAssessment:
    moves: list[dict[str, float | str]] = []
    invalid_capital_bases: list[dict[str, float | str]] = []
    for point in valuation_points:
        denominator = point.begin_mv + point.bod_cf
        if denominator <= 0:
            invalid_capital_bases.append(
                {
                    "perf_date": point.perf_date.isoformat(),
                    "begin_mv": point.begin_mv,
                    "bod_cf": point.bod_cf,
                    "effective_capital_base": denominator,
                }
            )
            continue
        numerator = point.end_mv - point.eod_cf - point.mgmt_fees
        return_pct = ((numerator / denominator) - 1.0) * 100.0
        moves.append({"perf_date": point.perf_date.isoformat(), "return_pct": return_pct})
    return DailyMoveInputsAssessment(daily_moves=moves, invalid_capital_bases=invalid_capital_bases)


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
