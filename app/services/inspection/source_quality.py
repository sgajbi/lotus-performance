from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

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
_RETURN_CONCENTRATION_MIN_OBSERVATIONS = 20
_RETURN_CONCENTRATION_TOP_N = 3
_RETURN_CONCENTRATION_THRESHOLD = 0.80
_REPEATED_MOVE_MIN_ABS_PCT = 1.0
_REPEATED_MOVE_MIN_RUN_LENGTH = 3
_MONTHLY_DAY_DOMINANCE_MIN_OBSERVATIONS = 10
_MONTHLY_DAY_DOMINANCE_THRESHOLD = 0.75


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
    daily_moves: list["DailyMove"]
    invalid_capital_bases: list[dict[str, float | str]]


@dataclass(frozen=True)
class DailyMove:
    perf_date: str
    return_pct: float  # monetary-float-allow

    def to_artifact(self) -> dict[str, float | str]:
        return {"perf_date": self.perf_date, "return_pct": self.return_pct}


@dataclass(frozen=True)
class MandateDailyMoveProfile:
    name: str
    threshold_pct: float


@dataclass(frozen=True)
class ReturnConcentrationAssessment:
    observation_count: int
    concentration_ratio: float
    top_moves: list[DailyMove]
    triggered: bool


@dataclass(frozen=True)
class RepeatedMoveRun:
    direction: str
    start_date: str
    end_date: str
    observation_count: int
    moves: list[DailyMove]


@dataclass(frozen=True)
class MonthlyDayDominance:
    month: str
    observation_count: int
    dominance_ratio: float
    dominant_move: DailyMove


@dataclass(frozen=True)
class _SourceQualityEvidenceContext:
    valuation_point_count: int
    weekend_dates: list[str]
    missing_business_dates: list[str]
    stale_runs: list[StaleSeriesRun]
    invalid_capital_bases: list[dict[str, float | str]]
    largest_abs_daily_move_pct: float
    extreme_move_threshold_pct: float
    extreme_moves: list[DailyMove]
    mandate_profile: MandateDailyMoveProfile | None
    mandate_outliers: list[DailyMove]
    return_concentration: ReturnConcentrationAssessment
    repeated_move_runs: list[RepeatedMoveRun]
    monthly_day_dominance: list[MonthlyDayDominance]

    @property
    def stale_observation_count(self) -> int:
        return sum(run.observation_count for run in self.stale_runs)


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
    largest_abs_daily_move_pct = max((abs(move.return_pct) for move in daily_moves), default=0.0)
    threshold = _EXTREME_MOVE_THRESHOLD_PCT[inspection_profile]
    extreme_moves = [move for move in daily_moves if abs(move.return_pct) >= threshold]
    mandate_profile = _resolve_mandate_daily_move_profile(performance_request.portfolio_id)
    mandate_outliers = _find_mandate_daily_move_outliers(
        daily_moves=daily_moves,
        mandate_profile=mandate_profile,
        extreme_threshold_pct=threshold,
    )
    return_concentration = _assess_return_concentration(daily_moves)
    repeated_move_runs = _find_repeated_move_runs(daily_moves)
    monthly_day_dominance = _find_monthly_day_dominance(daily_moves)

    findings = [
        *_build_weekend_findings(weekend_dates),
        *_build_business_gap_findings(missing_business_dates),
        *_build_stale_series_findings(stale_runs),
        *_build_nonpositive_capital_base_findings(invalid_capital_bases),
        *_build_mandate_daily_move_findings(
            mandate_profile=mandate_profile,
            mandate_outliers=mandate_outliers,
        ),
        *_build_return_concentration_findings(return_concentration),
        *_build_repeated_move_pattern_findings(repeated_move_runs),
        *_build_monthly_day_dominance_findings(monthly_day_dominance),
        *_build_extreme_move_findings(
            inspection_profile=inspection_profile,
            threshold=threshold,
            extreme_moves=extreme_moves,
        ),
    ]

    evidence_context = _SourceQualityEvidenceContext(
        valuation_point_count=len(valuation_points),
        weekend_dates=weekend_dates,
        missing_business_dates=missing_business_dates,
        stale_runs=stale_runs,
        invalid_capital_bases=invalid_capital_bases,
        largest_abs_daily_move_pct=largest_abs_daily_move_pct,
        extreme_move_threshold_pct=threshold,
        extreme_moves=extreme_moves,
        mandate_profile=mandate_profile,
        mandate_outliers=mandate_outliers,
        return_concentration=return_concentration,
        repeated_move_runs=repeated_move_runs,
        monthly_day_dominance=monthly_day_dominance,
    )
    return SourceQualityCheckResult(
        findings=findings,
        evidence_summary=_build_source_quality_evidence_summary(evidence_context),
        artifact_payload=_build_source_quality_artifact_payload(evidence_context),
    )


def _build_source_quality_evidence_summary(context: _SourceQualityEvidenceContext) -> dict[str, object]:
    return {
        "valuation_point_count": context.valuation_point_count,
        "weekend_observation_count": len(context.weekend_dates),
        "missing_business_date_count": len(context.missing_business_dates),
        "stale_series_run_count": len(context.stale_runs),
        "stale_series_observation_count": context.stale_observation_count,
        "nonpositive_capital_base_count": len(context.invalid_capital_bases),
        "largest_abs_daily_move_pct": context.largest_abs_daily_move_pct,
        "mandate_daily_move_outlier_count": len(context.mandate_outliers),
        "return_concentration_ratio": context.return_concentration.concentration_ratio,
        "repeated_move_run_count": len(context.repeated_move_runs),
        "monthly_day_dominance_count": len(context.monthly_day_dominance),
    }


def _build_source_quality_artifact_payload(context: _SourceQualityEvidenceContext) -> dict[str, object]:
    return {
        "valuation_point_count": context.valuation_point_count,
        "weekend_observation_count": len(context.weekend_dates),
        "weekend_dates": context.weekend_dates[:_STALE_SAMPLE_LIMIT],
        "missing_business_date_count": len(context.missing_business_dates),
        "missing_business_dates": context.missing_business_dates[:_STALE_SAMPLE_LIMIT],
        "stale_series_run_count": len(context.stale_runs),
        "stale_series_observation_count": context.stale_observation_count,
        "stale_series_min_observations": _STALE_SERIES_MIN_OBSERVATIONS,
        "stale_series_runs": [
            {
                "start_date": run.start_date,
                "end_date": run.end_date,
                "observation_count": run.observation_count,
                "begin_mv": run.begin_mv,
                "end_mv": run.end_mv,
            }
            for run in context.stale_runs[:_STALE_SAMPLE_LIMIT]
        ],
        "nonpositive_capital_base_count": len(context.invalid_capital_bases),
        "nonpositive_capital_base_samples": context.invalid_capital_bases[:_STALE_SAMPLE_LIMIT],
        "largest_abs_daily_move_pct": context.largest_abs_daily_move_pct,
        "extreme_daily_move_threshold_pct": context.extreme_move_threshold_pct,
        "extreme_daily_moves": _daily_moves_to_artifacts(context.extreme_moves),
        "mandate_daily_move_profile": context.mandate_profile.name if context.mandate_profile else None,
        "mandate_daily_move_threshold_pct": context.mandate_profile.threshold_pct if context.mandate_profile else None,
        "mandate_daily_move_outlier_count": len(context.mandate_outliers),
        "mandate_daily_move_outliers": _daily_moves_to_artifacts(context.mandate_outliers),
        "return_concentration_min_observations": _RETURN_CONCENTRATION_MIN_OBSERVATIONS,
        "return_concentration_top_n": _RETURN_CONCENTRATION_TOP_N,
        "return_concentration_threshold": _RETURN_CONCENTRATION_THRESHOLD,
        "return_concentration_ratio": context.return_concentration.concentration_ratio,
        "return_concentration_observation_count": context.return_concentration.observation_count,
        "return_concentration_top_moves": _daily_moves_to_artifacts(context.return_concentration.top_moves),
        "repeated_move_min_abs_pct": _REPEATED_MOVE_MIN_ABS_PCT,
        "repeated_move_min_run_length": _REPEATED_MOVE_MIN_RUN_LENGTH,
        "repeated_move_run_count": len(context.repeated_move_runs),
        "repeated_move_runs": _repeated_move_runs_to_artifacts(context.repeated_move_runs),
        "monthly_day_dominance_min_observations": _MONTHLY_DAY_DOMINANCE_MIN_OBSERVATIONS,
        "monthly_day_dominance_threshold": _MONTHLY_DAY_DOMINANCE_THRESHOLD,
        "monthly_day_dominance_count": len(context.monthly_day_dominance),
        "monthly_day_dominance_samples": _monthly_day_dominance_to_artifacts(context.monthly_day_dominance),
    }


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
    daily_moves: list[DailyMove],
    mandate_profile: MandateDailyMoveProfile | None,
    extreme_threshold_pct: float,
) -> list[DailyMove]:
    if mandate_profile is None:
        return []
    threshold_pct = mandate_profile.threshold_pct
    return [move for move in daily_moves if threshold_pct <= abs(move.return_pct) < extreme_threshold_pct]


def _build_mandate_daily_move_findings(
    *,
    mandate_profile: MandateDailyMoveProfile | None,
    mandate_outliers: list[DailyMove],
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
                "outliers": _daily_moves_to_artifacts(mandate_outliers),
            },
        )
    ]


def _assess_return_concentration(daily_moves: list[DailyMove]) -> ReturnConcentrationAssessment:
    if len(daily_moves) < _RETURN_CONCENTRATION_MIN_OBSERVATIONS:
        return ReturnConcentrationAssessment(
            observation_count=len(daily_moves),
            concentration_ratio=0.0,
            top_moves=[],
            triggered=False,
        )
    moves_by_abs_return = sorted(daily_moves, key=lambda move: abs(move.return_pct), reverse=True)
    total_abs_return = sum(abs(move.return_pct) for move in daily_moves)
    top_moves = moves_by_abs_return[:_RETURN_CONCENTRATION_TOP_N]
    top_abs_return = sum(abs(move.return_pct) for move in top_moves)
    concentration_ratio = top_abs_return / total_abs_return if total_abs_return > 0 else 0.0
    return ReturnConcentrationAssessment(
        observation_count=len(daily_moves),
        concentration_ratio=concentration_ratio,
        top_moves=top_moves,
        triggered=concentration_ratio >= _RETURN_CONCENTRATION_THRESHOLD,
    )


def _build_return_concentration_findings(
    return_concentration: ReturnConcentrationAssessment,
) -> list[TWRInspectionFinding]:
    if not return_concentration.triggered:
        return []
    return [
        TWRInspectionFinding(
            code="RETURN_CONCENTRATION_DETECTED",
            severity="warning",
            category="economic_plausibility",
            owner_repo="lotus-performance",
            summary="Resolved source inputs concentrate most absolute daily movement in a small number of dates.",
            explanation=(
                f"The top {_RETURN_CONCENTRATION_TOP_N} absolute daily moves explain at least "
                f"{_RETURN_CONCENTRATION_THRESHOLD:.0%} of total absolute movement across the inspected window."
            ),
            recommended_action=(
                "Review the sampled dates for valuation, fee, external cash-flow, or upstream source-state events "
                "before treating the TWR path as operationally robust."
            ),
            evidence={
                "top_n": _RETURN_CONCENTRATION_TOP_N,
                "threshold": _RETURN_CONCENTRATION_THRESHOLD,
                "observation_count": return_concentration.observation_count,
                "concentration_ratio": return_concentration.concentration_ratio,
                "top_moves": _daily_moves_to_artifacts(return_concentration.top_moves),
            },
        )
    ]


def _find_repeated_move_runs(daily_moves: list[DailyMove]) -> list[RepeatedMoveRun]:
    runs: list[RepeatedMoveRun] = []
    current_run: list[DailyMove] = []
    current_direction: str | None = None

    for move in daily_moves:
        direction = _large_move_direction(move)
        if direction is None:
            _append_repeated_move_run_if_needed(
                runs=runs,
                run_moves=current_run,
                direction=current_direction,
            )
            current_run = []
            current_direction = None
            continue
        if current_direction is None or direction != current_direction:
            _append_repeated_move_run_if_needed(
                runs=runs,
                run_moves=current_run,
                direction=current_direction,
            )
            current_run = [move]
            current_direction = direction
            continue
        current_run.append(move)

    _append_repeated_move_run_if_needed(
        runs=runs,
        run_moves=current_run,
        direction=current_direction,
    )
    return runs


def _large_move_direction(move: DailyMove) -> str | None:
    if abs(move.return_pct) < _REPEATED_MOVE_MIN_ABS_PCT:
        return None
    return "positive" if move.return_pct > 0 else "negative"


def _append_repeated_move_run_if_needed(
    *,
    runs: list[RepeatedMoveRun],
    run_moves: list[DailyMove],
    direction: str | None,
) -> None:
    if direction is None or len(run_moves) < _REPEATED_MOVE_MIN_RUN_LENGTH:
        return
    runs.append(
        RepeatedMoveRun(
            direction=direction,
            start_date=run_moves[0].perf_date,
            end_date=run_moves[-1].perf_date,
            observation_count=len(run_moves),
            moves=list(run_moves),
        )
    )


def _build_repeated_move_pattern_findings(repeated_move_runs: list[RepeatedMoveRun]) -> list[TWRInspectionFinding]:
    if not repeated_move_runs:
        return []
    return [
        TWRInspectionFinding(
            code="REPEATED_DAILY_MOVE_PATTERN_DETECTED",
            severity="warning",
            category="economic_plausibility",
            owner_repo="lotus-performance",
            summary="Resolved source inputs contain repeated same-direction large daily moves.",
            explanation=(
                f"The inspector found at least {_REPEATED_MOVE_MIN_RUN_LENGTH} consecutive same-direction daily "
                f"moves with absolute return at or above {_REPEATED_MOVE_MIN_ABS_PCT:.2f}%."
            ),
            recommended_action=(
                "Review the repeated-move dates for valuation restatement, source-state carry-forward, fee, or "
                "external cash-flow events before relying on the TWR path as supportable."
            ),
            evidence={
                "min_abs_return_pct": _REPEATED_MOVE_MIN_ABS_PCT,
                "min_run_length": _REPEATED_MOVE_MIN_RUN_LENGTH,
                "run_count": len(repeated_move_runs),
                "runs": _repeated_move_runs_to_artifacts(repeated_move_runs),
            },
        )
    ]


def _find_monthly_day_dominance(daily_moves: list[DailyMove]) -> list[MonthlyDayDominance]:
    moves_by_month: dict[str, list[DailyMove]] = {}
    for move in daily_moves:
        moves_by_month.setdefault(move.perf_date[:7], []).append(move)

    dominance_samples: list[MonthlyDayDominance] = []
    for month, month_moves in sorted(moves_by_month.items()):
        dominance = _monthly_day_dominance(month=month, month_moves=month_moves)
        if dominance is not None:
            dominance_samples.append(dominance)
    return dominance_samples


def _monthly_day_dominance(
    *,
    month: str,
    month_moves: list[DailyMove],
) -> MonthlyDayDominance | None:
    if len(month_moves) < _MONTHLY_DAY_DOMINANCE_MIN_OBSERVATIONS:
        return None
    total_abs_return = sum(abs(move.return_pct) for move in month_moves)
    if total_abs_return <= 0:
        return None
    dominant_move = max(month_moves, key=lambda move: abs(move.return_pct))
    dominance_ratio = abs(dominant_move.return_pct) / total_abs_return
    if dominance_ratio < _MONTHLY_DAY_DOMINANCE_THRESHOLD:
        return None
    return MonthlyDayDominance(
        month=month,
        observation_count=len(month_moves),
        dominance_ratio=dominance_ratio,
        dominant_move=dominant_move,
    )


def _build_monthly_day_dominance_findings(
    monthly_day_dominance: list[MonthlyDayDominance],
) -> list[TWRInspectionFinding]:
    if not monthly_day_dominance:
        return []
    return [
        TWRInspectionFinding(
            code="MONTHLY_RETURN_DAY_DOMINANCE_DETECTED",
            severity="warning",
            category="economic_plausibility",
            owner_repo="lotus-performance",
            summary="Resolved source inputs have a month where one day dominates absolute movement.",
            explanation=(
                f"For at least one month with {_MONTHLY_DAY_DOMINANCE_MIN_OBSERVATIONS} or more daily moves, "
                f"one day explains at least {_MONTHLY_DAY_DOMINANCE_THRESHOLD:.0%} of total absolute movement."
            ),
            recommended_action=(
                "Review the dominant day for valuation restatement, cash-flow timing, fee, or source-state events "
                "before treating the monthly TWR path as operationally robust."
            ),
            evidence={
                "min_observations": _MONTHLY_DAY_DOMINANCE_MIN_OBSERVATIONS,
                "threshold": _MONTHLY_DAY_DOMINANCE_THRESHOLD,
                "dominance_count": len(monthly_day_dominance),
                "samples": _monthly_day_dominance_to_artifacts(monthly_day_dominance),
            },
        )
    ]


def _build_extreme_move_findings(
    *,
    inspection_profile: TWRInspectionProfile,
    threshold: float,
    extreme_moves: list[DailyMove],
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
                "extreme_moves": _daily_moves_to_artifacts(extreme_moves),
            },
        )
    ]


def _assess_daily_move_inputs(valuation_points: list[DailyInputData]) -> DailyMoveInputsAssessment:
    moves: list[DailyMove] = []
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
        moves.append(DailyMove(perf_date=point.perf_date.isoformat(), return_pct=return_pct))
    return DailyMoveInputsAssessment(daily_moves=moves, invalid_capital_bases=invalid_capital_bases)


def _daily_moves_to_artifacts(daily_moves: list[DailyMove]) -> list[dict[str, float | str]]:
    return [move.to_artifact() for move in daily_moves[:_STALE_SAMPLE_LIMIT]]


def _repeated_move_runs_to_artifacts(repeated_move_runs: list[RepeatedMoveRun]) -> list[dict[str, object]]:
    return [
        {
            "direction": run.direction,
            "start_date": run.start_date,
            "end_date": run.end_date,
            "observation_count": run.observation_count,
            "moves": _daily_moves_to_artifacts(run.moves),
        }
        for run in repeated_move_runs[:_STALE_SAMPLE_LIMIT]
    ]


def _monthly_day_dominance_to_artifacts(
    monthly_day_dominance: list[MonthlyDayDominance],
) -> list[dict[str, object]]:
    return [
        {
            "month": dominance.month,
            "observation_count": dominance.observation_count,
            "dominance_ratio": dominance.dominance_ratio,
            "dominant_move": dominance.dominant_move.to_artifact(),
        }
        for dominance in monthly_day_dominance[:_STALE_SAMPLE_LIMIT]
    ]


def _find_missing_business_dates(valuation_points: list[DailyInputData]) -> list[str]:
    if len(valuation_points) <= 1:
        return []
    expected: list[str] = []
    current = valuation_points[0].perf_date
    last = valuation_points[-1].perf_date
    observed = {point.perf_date.isoformat() for point in valuation_points}
    while current <= last:
        if _is_unobserved_business_date(current, observed):
            expected.append(current.isoformat())
        current += timedelta(days=1)
    return expected


def _is_unobserved_business_date(candidate_date: date, observed_iso_dates: set[str]) -> bool:
    return candidate_date.weekday() < 5 and candidate_date.isoformat() not in observed_iso_dates


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
