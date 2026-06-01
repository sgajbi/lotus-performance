from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.models.source_quality import PerformanceSourceQualityEvidence
from app.services.analytics_observation_dates import latest_observation_date, normalize_observation_date
from app.services.source_cashflow_taxonomy import classify_cashflow_type


def build_portfolio_source_quality_evidence(
    *,
    observations: list[dict[str, object]],
    valid_valuation_point_count: int,
    report_end_date: date | None,
    input_mode: Literal["stateful", "stateless"],
    source_owner: str,
    source_product: str,
) -> PerformanceSourceQualityEvidence:
    skipped_observation_count = 0
    unsupported_cashflow_count = 0
    source_classifications: Counter[str] = Counter()
    values_by_date: dict[str, set[tuple[Decimal, Decimal]]] = defaultdict(set)
    normalized_dates: list[date] = []

    for observation in observations:
        valuation_date = observation.get("valuation_date")
        begin_mv = observation.get("beginning_market_value")
        end_mv = observation.get("ending_market_value")
        if isinstance(observation.get("source_classification"), str):
            source_classifications[str(observation["source_classification"])] += 1
        if not isinstance(valuation_date, str) or begin_mv is None or end_mv is None:
            skipped_observation_count += 1
        else:
            try:
                normalized_dates.append(normalize_observation_date(valuation_date))
                values_by_date[valuation_date].add((Decimal(str(begin_mv)), Decimal(str(end_mv))))
            except (InvalidOperation, TypeError, ValueError):
                skipped_observation_count += 1

        cash_flows = observation.get("cash_flows", [])
        if isinstance(cash_flows, list):
            for flow in cash_flows:
                if not isinstance(flow, dict):
                    continue
                classification = classify_cashflow_type(flow.get("cash_flow_type"))
                if classification.economics_role == "unsupported":
                    unsupported_cashflow_count += 1

    source_conflict_count = sum(max(len(values) - 1, 0) for values in values_by_date.values())
    latest_source_observation_date = latest_observation_date(normalized_dates)
    warnings = _source_quality_warnings(
        skipped_observation_count=skipped_observation_count,
        unsupported_cashflow_count=unsupported_cashflow_count,
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
        skipped_observation_count=skipped_observation_count,
        unsupported_cashflow_count=unsupported_cashflow_count,
        source_conflict_count=source_conflict_count,
        latest_observation_date=latest_source_observation_date,
        report_end_date=report_end_date,
        warnings=warnings,
        source_classification_counts=dict(sorted(source_classifications.items())),
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
    if (
        latest_observation_date is not None
        and report_end_date is not None
        and latest_observation_date < report_end_date
    ):
        warnings.append("STALE_SOURCE_OBSERVATIONS")
    return warnings
