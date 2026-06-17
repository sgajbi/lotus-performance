from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.models.source_quality import PerformanceSourceQualityEvidence
from app.services.analytics_observation_dates import latest_observation_date, normalize_observation_date
from app.services.source_cashflow_taxonomy import classify_cashflow_type


@dataclass(frozen=True)
class _SourceQualityObservationSummary:
    skipped_observation_count: int
    unsupported_cashflow_count: int
    source_classifications: Counter[str]
    values_by_date: dict[str, set[tuple[Decimal, Decimal]]]
    normalized_dates: list[date]


def build_portfolio_source_quality_evidence(
    *,
    observations: list[dict[str, object]],
    valid_valuation_point_count: int,
    report_end_date: date | None,
    input_mode: Literal["stateful", "stateless"],
    source_owner: str,
    source_product: str,
) -> PerformanceSourceQualityEvidence:
    observation_summary = _summarize_source_quality_observations(observations)
    source_conflict_count = sum(max(len(values) - 1, 0) for values in observation_summary.values_by_date.values())
    latest_source_observation_date = latest_observation_date(observation_summary.normalized_dates)
    warnings = _source_quality_warnings(
        skipped_observation_count=observation_summary.skipped_observation_count,
        unsupported_cashflow_count=observation_summary.unsupported_cashflow_count,
        source_conflict_count=source_conflict_count,
        latest_observation_date=latest_source_observation_date,
        report_end_date=report_end_date,
    )
    quality_state = "clean"
    if "STALE_SOURCE_OBSERVATIONS" in warnings:
        quality_state = "stale"
    elif warnings:
        quality_state = "degraded"

    return PerformanceSourceQualityEvidence(
        source_product=source_product,
        source_owner=source_owner,
        input_mode=input_mode,
        quality_state=quality_state,
        observation_count=len(observations),
        valid_valuation_point_count=valid_valuation_point_count,
        skipped_observation_count=observation_summary.skipped_observation_count,
        unsupported_cashflow_count=observation_summary.unsupported_cashflow_count,
        source_conflict_count=source_conflict_count,
        latest_observation_date=latest_source_observation_date,
        report_end_date=report_end_date,
        warnings=warnings,
        source_classification_counts=dict(sorted(observation_summary.source_classifications.items())),
    )


def _summarize_source_quality_observations(
    observations: list[dict[str, object]],
) -> _SourceQualityObservationSummary:
    skipped_observation_count = 0
    unsupported_cashflow_count = 0
    source_classifications: Counter[str] = Counter()
    values_by_date: dict[str, set[tuple[Decimal, Decimal]]] = defaultdict(set)
    normalized_dates: list[date] = []

    for observation in observations:
        skipped_observation_count += _record_source_quality_observation(
            observation,
            source_classifications=source_classifications,
            values_by_date=values_by_date,
            normalized_dates=normalized_dates,
        )
        unsupported_cashflow_count += _unsupported_cashflow_count(observation.get("cash_flows", []))

    return _SourceQualityObservationSummary(
        skipped_observation_count=skipped_observation_count,
        unsupported_cashflow_count=unsupported_cashflow_count,
        source_classifications=source_classifications,
        values_by_date=values_by_date,
        normalized_dates=normalized_dates,
    )


def _record_source_quality_observation(
    observation: dict[str, object],
    *,
    source_classifications: Counter[str],
    values_by_date: dict[str, set[tuple[Decimal, Decimal]]],
    normalized_dates: list[date],
) -> int:
    valuation_date = observation.get("valuation_date")
    begin_mv = observation.get("beginning_market_value")
    end_mv = observation.get("ending_market_value")
    if isinstance(observation.get("source_classification"), str):
        source_classifications[str(observation["source_classification"])] += 1
    if not isinstance(valuation_date, str) or begin_mv is None or end_mv is None:
        return 1
    return _record_source_values_by_date(
        valuation_date=valuation_date,
        beginning_market_value=begin_mv,
        ending_market_value=end_mv,
        values_by_date=values_by_date,
        normalized_dates=normalized_dates,
    )


def _record_source_values_by_date(
    *,
    valuation_date: str,
    beginning_market_value: object,
    ending_market_value: object,
    values_by_date: dict[str, set[tuple[Decimal, Decimal]]],
    normalized_dates: list[date],
) -> int:
    try:
        normalized_dates.append(normalize_observation_date(valuation_date))
        values_by_date[valuation_date].add((Decimal(str(beginning_market_value)), Decimal(str(ending_market_value))))
    except (InvalidOperation, TypeError, ValueError):
        return 1
    return 0


def _unsupported_cashflow_count(cash_flows: object) -> int:
    if not isinstance(cash_flows, list):
        return 0
    return sum(
        1
        for flow in cash_flows
        if isinstance(flow, dict) and classify_cashflow_type(flow.get("cash_flow_type")).economics_role == "unsupported"
    )


def _source_quality_warnings(
    *,
    skipped_observation_count: int,
    unsupported_cashflow_count: int,
    source_conflict_count: int,
    latest_observation_date: date | None,
    report_end_date: date | None,
) -> list[str]:
    warnings: list[str] = []
    if skipped_observation_count > 0:
        warnings.append("MISSING_VALUATION_POINTS")
    if unsupported_cashflow_count > 0:
        warnings.append("UNSUPPORTED_CASHFLOW_LABELS")
    if source_conflict_count > 0:
        warnings.append("SOURCE_DATE_CONFLICTS")
    if _has_stale_source_observations(
        latest_observation_date=latest_observation_date,
        report_end_date=report_end_date,
    ):
        warnings.append("STALE_SOURCE_OBSERVATIONS")
    return warnings


def _has_stale_source_observations(
    *,
    latest_observation_date: date | None,
    report_end_date: date | None,
) -> bool:
    if latest_observation_date is None or report_end_date is None:
        return False
    return latest_observation_date < report_end_date
