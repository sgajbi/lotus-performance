from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as dt_date
from decimal import Decimal, localcontext

from app.models.composites import CompositeMemberReturnFact, CompositeMemberReturnStatus

COMPOSITE_RETURN_QUANTUM = Decimal("0.000000000001")
COMPOSITE_ASSET_QUANTUM = Decimal("0.000001")


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


def calculate_asset_weighted_composite_twr(
    *,
    composite_id: str,
    member_return_facts: list[CompositeMemberReturnFact],
) -> CompositeCalculationResult:
    grouped_facts: dict[tuple[dt_date, dt_date], list[CompositeMemberReturnFact]] = defaultdict(list)
    for fact in member_return_facts:
        if fact.composite_id != composite_id:
            continue
        grouped_facts[(fact.period_start, fact.period_end)].append(fact)

    period_results: list[CompositePeriodResult] = []
    cumulative_growth = Decimal("1")
    aggregate_reason_codes: set[str] = set()

    for period_start, period_end in sorted(grouped_facts):
        facts = grouped_facts[(period_start, period_end)]
        ready_facts = [fact for fact in facts if fact.status == CompositeMemberReturnStatus.READY]
        excluded_facts = [fact for fact in facts if fact.status != CompositeMemberReturnStatus.READY]
        reason_codes = sorted({code for fact in excluded_facts for code in fact.reason_codes})
        aggregate_reason_codes.update(reason_codes)

        beginning_assets = sum((fact.beginning_market_value for fact in ready_facts), Decimal("0"))
        ending_assets = sum((fact.ending_market_value for fact in ready_facts), Decimal("0"))
        if not ready_facts:
            period_results.append(
                CompositePeriodResult(
                    period_start=period_start,
                    period_end=period_end,
                    status="BLOCKED",
                    return_value=None,
                    cumulative_return=None,
                    beginning_market_value=Decimal("0").quantize(COMPOSITE_ASSET_QUANTUM),
                    ending_market_value=Decimal("0").quantize(COMPOSITE_ASSET_QUANTUM),
                    member_count=0,
                    excluded_member_count=len(excluded_facts),
                    dispersion_equal_weight=None,
                    reason_codes=reason_codes or ["no_ready_member_return_facts"],
                    member_contributions=[],
                )
            )
            aggregate_reason_codes.add("no_ready_member_return_facts")
            continue

        if beginning_assets <= 0:
            period_results.append(
                CompositePeriodResult(
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
                    reason_codes=reason_codes + ["nonpositive_composite_beginning_assets"],
                    member_contributions=[],
                )
            )
            aggregate_reason_codes.add("nonpositive_composite_beginning_assets")
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
