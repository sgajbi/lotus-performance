from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as dt_date
from decimal import Decimal, localcontext
from typing import Protocol, Sequence

COMPOSITE_MEMBER_READY_STATUS = "READY"
COMPOSITE_RETURN_QUANTUM = Decimal("0.000000000001")
COMPOSITE_ASSET_QUANTUM = Decimal("0.000001")


class CompositeMemberReturnFactLike(Protocol):
    composite_id: str
    portfolio_id: str
    period_start: dt_date
    period_end: dt_date
    return_value: Decimal
    return_view: object
    beginning_market_value: Decimal
    ending_market_value: Decimal
    reporting_currency: str
    calculation_id: str
    source_snapshot_id: str
    source_fingerprint: str
    restatement_version: str
    status: object
    reason_codes: list[str]


@dataclass(frozen=True)
class CompositeMemberContribution:
    portfolio_id: str
    period_start: dt_date
    period_end: dt_date
    return_value: Decimal
    beginning_market_value: Decimal
    weight: Decimal
    contribution: Decimal
    source_snapshot_id: str
    source_fingerprint: str
    restatement_version: str
    calculation_id: str


@dataclass(frozen=True)
class CompositePeriodResult:
    period_start: dt_date
    period_end: dt_date
    status: str
    return_value: Decimal | None
    cumulative_return: Decimal | None
    beginning_market_value: Decimal
    ending_market_value: Decimal
    member_count: int
    excluded_member_count: int
    dispersion_equal_weight: Decimal | None
    return_view: str | None
    reporting_currency: str | None
    source_fingerprints: list[str]
    restatement_versions: list[str]
    reason_codes: list[str]
    member_contributions: list[CompositeMemberContribution]


@dataclass(frozen=True)
class CompositeCalculationResult:
    composite_id: str
    status: str
    period_results: list[CompositePeriodResult]
    cumulative_return: Decimal | None
    reason_codes: list[str]


def _quantize_decimal(value: Decimal, quantum: Decimal) -> Decimal:
    if value == 0:
        return Decimal("0").quantize(quantum)
    with localcontext() as context:
        context.prec = max(28, value.adjusted() + 18)
        return value.quantize(quantum)


def _sample_standard_deviation(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    return _quantize_decimal(variance.sqrt(), COMPOSITE_RETURN_QUANTUM)


def _blocked_composite_period_result(
    *,
    period_start: dt_date,
    period_end: dt_date,
    beginning_assets: Decimal,
    ending_assets: Decimal,
    ready_facts: Sequence[CompositeMemberReturnFactLike],
    excluded_facts: Sequence[CompositeMemberReturnFactLike],
    reason_codes: list[str],
    return_view: str | None = None,
    reporting_currency: str | None = None,
    source_fingerprints: list[str] | None = None,
    restatement_versions: list[str] | None = None,
) -> CompositePeriodResult:
    return CompositePeriodResult(
        period_start=period_start,
        period_end=period_end,
        status="BLOCKED",
        return_value=None,
        cumulative_return=None,
        beginning_market_value=_quantize_decimal(beginning_assets, COMPOSITE_ASSET_QUANTUM),
        ending_market_value=_quantize_decimal(ending_assets, COMPOSITE_ASSET_QUANTUM),
        member_count=len(ready_facts),
        excluded_member_count=len(excluded_facts),
        dispersion_equal_weight=None,
        return_view=return_view,
        reporting_currency=reporting_currency,
        source_fingerprints=source_fingerprints or [],
        restatement_versions=restatement_versions or [],
        reason_codes=reason_codes,
        member_contributions=[],
    )


def calculate_asset_weighted_composite_twr(
    *,
    composite_id: str,
    member_return_facts: Sequence[CompositeMemberReturnFactLike],
) -> CompositeCalculationResult:
    grouped_facts: dict[tuple[dt_date, dt_date], list[CompositeMemberReturnFactLike]] = defaultdict(list)
    for fact in member_return_facts:
        if fact.composite_id != composite_id:
            continue
        grouped_facts[(fact.period_start, fact.period_end)].append(fact)

    period_results: list[CompositePeriodResult] = []
    cumulative_growth = Decimal("1")
    aggregate_reason_codes: set[str] = set()

    for period_start, period_end in sorted(grouped_facts):
        facts = grouped_facts[(period_start, period_end)]
        ready_facts = [fact for fact in facts if str(fact.status) == COMPOSITE_MEMBER_READY_STATUS]
        excluded_facts = [fact for fact in facts if str(fact.status) != COMPOSITE_MEMBER_READY_STATUS]
        reason_codes = sorted({code for fact in excluded_facts for code in fact.reason_codes})
        aggregate_reason_codes.update(reason_codes)

        beginning_assets = sum((fact.beginning_market_value for fact in ready_facts), Decimal("0"))
        ending_assets = sum((fact.ending_market_value for fact in ready_facts), Decimal("0"))
        ready_return_views = sorted({str(fact.return_view) for fact in ready_facts})
        ready_reporting_currencies = sorted({fact.reporting_currency for fact in ready_facts})
        ready_source_fingerprints = sorted({fact.source_fingerprint for fact in ready_facts})
        ready_restatement_versions = sorted({fact.restatement_version for fact in ready_facts})
        if not ready_facts:
            period_results.append(
                _blocked_composite_period_result(
                    period_start=period_start,
                    period_end=period_end,
                    beginning_assets=Decimal("0"),
                    ending_assets=Decimal("0"),
                    ready_facts=ready_facts,
                    excluded_facts=excluded_facts,
                    reason_codes=reason_codes or ["no_ready_member_return_facts"],
                )
            )
            aggregate_reason_codes.add("no_ready_member_return_facts")
            continue

        if beginning_assets <= 0:
            period_results.append(
                _blocked_composite_period_result(
                    period_start=period_start,
                    period_end=period_end,
                    beginning_assets=beginning_assets,
                    ending_assets=ending_assets,
                    ready_facts=ready_facts,
                    excluded_facts=excluded_facts,
                    return_view=ready_return_views[0] if len(ready_return_views) == 1 else None,
                    reporting_currency=ready_reporting_currencies[0] if len(ready_reporting_currencies) == 1 else None,
                    source_fingerprints=ready_source_fingerprints,
                    restatement_versions=ready_restatement_versions,
                    reason_codes=reason_codes + ["nonpositive_composite_beginning_assets"],
                )
            )
            aggregate_reason_codes.add("nonpositive_composite_beginning_assets")
            continue

        if len(ready_return_views) > 1:
            period_results.append(
                _blocked_composite_period_result(
                    period_start=period_start,
                    period_end=period_end,
                    beginning_assets=beginning_assets,
                    ending_assets=ending_assets,
                    ready_facts=ready_facts,
                    excluded_facts=excluded_facts,
                    return_view=None,
                    reporting_currency=ready_reporting_currencies[0] if len(ready_reporting_currencies) == 1 else None,
                    source_fingerprints=ready_source_fingerprints,
                    restatement_versions=ready_restatement_versions,
                    reason_codes=reason_codes + ["mixed_member_return_views"],
                )
            )
            aggregate_reason_codes.add("mixed_member_return_views")
            continue

        if len(ready_reporting_currencies) > 1:
            period_results.append(
                _blocked_composite_period_result(
                    period_start=period_start,
                    period_end=period_end,
                    beginning_assets=beginning_assets,
                    ending_assets=ending_assets,
                    ready_facts=ready_facts,
                    excluded_facts=excluded_facts,
                    return_view=ready_return_views[0],
                    reporting_currency=None,
                    source_fingerprints=ready_source_fingerprints,
                    restatement_versions=ready_restatement_versions,
                    reason_codes=reason_codes + ["mixed_member_reporting_currencies"],
                )
            )
            aggregate_reason_codes.add("mixed_member_reporting_currencies")
            continue

        member_contributions: list[CompositeMemberContribution] = []
        weighted_return = Decimal("0")
        for fact in sorted(ready_facts, key=lambda item: item.portfolio_id):
            weight = fact.beginning_market_value / beginning_assets
            contribution = fact.return_value * weight
            weighted_return += contribution
            member_contributions.append(
                CompositeMemberContribution(
                    portfolio_id=fact.portfolio_id,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    return_value=_quantize_decimal(fact.return_value, COMPOSITE_RETURN_QUANTUM),
                    beginning_market_value=_quantize_decimal(fact.beginning_market_value, COMPOSITE_ASSET_QUANTUM),
                    weight=_quantize_decimal(weight, COMPOSITE_RETURN_QUANTUM),
                    contribution=_quantize_decimal(contribution, COMPOSITE_RETURN_QUANTUM),
                    source_snapshot_id=fact.source_snapshot_id,
                    source_fingerprint=fact.source_fingerprint,
                    restatement_version=fact.restatement_version,
                    calculation_id=fact.calculation_id,
                )
            )

        cumulative_growth *= Decimal("1") + weighted_return
        cumulative_return = cumulative_growth - Decimal("1")
        status = "READY" if not excluded_facts else "DEGRADED"
        period_results.append(
            CompositePeriodResult(
                period_start=period_start,
                period_end=period_end,
                status=status,
                return_value=_quantize_decimal(weighted_return, COMPOSITE_RETURN_QUANTUM),
                cumulative_return=_quantize_decimal(cumulative_return, COMPOSITE_RETURN_QUANTUM),
                beginning_market_value=_quantize_decimal(beginning_assets, COMPOSITE_ASSET_QUANTUM),
                ending_market_value=_quantize_decimal(ending_assets, COMPOSITE_ASSET_QUANTUM),
                member_count=len(ready_facts),
                excluded_member_count=len(excluded_facts),
                dispersion_equal_weight=_sample_standard_deviation([fact.return_value for fact in ready_facts]),
                return_view=ready_return_views[0],
                reporting_currency=ready_reporting_currencies[0],
                source_fingerprints=ready_source_fingerprints,
                restatement_versions=ready_restatement_versions,
                reason_codes=reason_codes,
                member_contributions=member_contributions,
            )
        )

    if not period_results:
        return CompositeCalculationResult(
            composite_id=composite_id,
            status="BLOCKED",
            period_results=[],
            cumulative_return=None,
            reason_codes=["no_member_return_facts"],
        )

    terminal_cumulative = next(
        (period.cumulative_return for period in reversed(period_results) if period.cumulative_return is not None),
        None,
    )
    if all(period.status == "READY" for period in period_results):
        status = "READY"
    elif any(period.status == "READY" or period.status == "DEGRADED" for period in period_results):
        status = "DEGRADED"
    else:
        status = "BLOCKED"

    return CompositeCalculationResult(
        composite_id=composite_id,
        status=status,
        period_results=period_results,
        cumulative_return=terminal_cumulative,
        reason_codes=sorted(aggregate_reason_codes),
    )
