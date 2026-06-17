from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
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


@dataclass(frozen=True)
class _CompositePeriodFactSet:
    period_start: dt_date
    period_end: dt_date
    ready_facts: list[CompositeMemberReturnFactLike]
    excluded_facts: list[CompositeMemberReturnFactLike]
    reason_codes: list[str]
    beginning_assets: Decimal
    ending_assets: Decimal
    ready_return_views: list[str]
    ready_reporting_currencies: list[str]
    ready_source_fingerprints: list[str]
    ready_restatement_versions: list[str]


@dataclass(frozen=True)
class _CompositePeriodFactMetadata:
    reason_codes: list[str]
    beginning_assets: Decimal
    ending_assets: Decimal
    ready_return_views: list[str]
    ready_reporting_currencies: list[str]
    ready_source_fingerprints: list[str]
    ready_restatement_versions: list[str]


@dataclass(frozen=True)
class _InvalidReadyCompositePeriodContext:
    period_start: dt_date
    period_end: dt_date
    ready_facts: Sequence[CompositeMemberReturnFactLike]
    excluded_facts: Sequence[CompositeMemberReturnFactLike]


@dataclass(frozen=True)
class _InvalidReadyCompositePeriodInputs:
    context: _InvalidReadyCompositePeriodContext
    beginning_assets: Decimal
    ending_assets: Decimal
    reason_codes: list[str]
    ready_return_views: list[str]
    ready_reporting_currencies: list[str]
    ready_source_fingerprints: list[str]
    ready_restatement_versions: list[str]


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


def _build_ready_member_contributions(
    *,
    ready_facts: Sequence[CompositeMemberReturnFactLike],
    beginning_assets: Decimal,
) -> tuple[Decimal, list[CompositeMemberContribution]]:
    weighted_return = Decimal("0")
    member_contributions: list[CompositeMemberContribution] = []
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
    return weighted_return, member_contributions


def _single_composite_metadata_value(values: Sequence[str]) -> str | None:
    return values[0] if len(values) == 1 else None


def _blocked_invalid_ready_composite_period_result(
    context: _InvalidReadyCompositePeriodContext,
    *,
    beginning_assets: Decimal,
    ending_assets: Decimal,
    aggregate_reason_code: str,
    reason_codes: list[str],
    return_view: str | None = None,
    reporting_currency: str | None = None,
    source_fingerprints: list[str] | None = None,
    restatement_versions: list[str] | None = None,
) -> tuple[CompositePeriodResult, str]:
    return (
        _blocked_composite_period_result(
            period_start=context.period_start,
            period_end=context.period_end,
            beginning_assets=beginning_assets,
            ending_assets=ending_assets,
            ready_facts=context.ready_facts,
            excluded_facts=context.excluded_facts,
            return_view=return_view,
            reporting_currency=reporting_currency,
            source_fingerprints=source_fingerprints,
            restatement_versions=restatement_versions,
            reason_codes=reason_codes,
        ),
        aggregate_reason_code,
    )


def _no_ready_member_return_facts_block(
    inputs: _InvalidReadyCompositePeriodInputs,
) -> tuple[CompositePeriodResult, str] | None:
    if inputs.context.ready_facts:
        return None
    return _blocked_invalid_ready_composite_period_result(
        inputs.context,
        beginning_assets=Decimal("0"),
        ending_assets=Decimal("0"),
        aggregate_reason_code="no_ready_member_return_facts",
        reason_codes=inputs.reason_codes or ["no_ready_member_return_facts"],
    )


def _nonpositive_composite_beginning_assets_block(
    inputs: _InvalidReadyCompositePeriodInputs,
) -> tuple[CompositePeriodResult, str] | None:
    if inputs.beginning_assets > 0:
        return None
    return _blocked_invalid_ready_composite_period_result(
        inputs.context,
        beginning_assets=inputs.beginning_assets,
        ending_assets=inputs.ending_assets,
        aggregate_reason_code="nonpositive_composite_beginning_assets",
        reason_codes=inputs.reason_codes + ["nonpositive_composite_beginning_assets"],
        return_view=_single_composite_metadata_value(inputs.ready_return_views),
        reporting_currency=_single_composite_metadata_value(inputs.ready_reporting_currencies),
        source_fingerprints=inputs.ready_source_fingerprints,
        restatement_versions=inputs.ready_restatement_versions,
    )


def _mixed_member_return_views_block(
    inputs: _InvalidReadyCompositePeriodInputs,
) -> tuple[CompositePeriodResult, str] | None:
    if len(inputs.ready_return_views) <= 1:
        return None
    return _blocked_invalid_ready_composite_period_result(
        inputs.context,
        beginning_assets=inputs.beginning_assets,
        ending_assets=inputs.ending_assets,
        aggregate_reason_code="mixed_member_return_views",
        reason_codes=inputs.reason_codes + ["mixed_member_return_views"],
        reporting_currency=_single_composite_metadata_value(inputs.ready_reporting_currencies),
        source_fingerprints=inputs.ready_source_fingerprints,
        restatement_versions=inputs.ready_restatement_versions,
    )


def _mixed_member_reporting_currencies_block(
    inputs: _InvalidReadyCompositePeriodInputs,
) -> tuple[CompositePeriodResult, str] | None:
    if len(inputs.ready_reporting_currencies) <= 1:
        return None
    return _blocked_invalid_ready_composite_period_result(
        inputs.context,
        beginning_assets=inputs.beginning_assets,
        ending_assets=inputs.ending_assets,
        aggregate_reason_code="mixed_member_reporting_currencies",
        reason_codes=inputs.reason_codes + ["mixed_member_reporting_currencies"],
        return_view=inputs.ready_return_views[0],
        source_fingerprints=inputs.ready_source_fingerprints,
        restatement_versions=inputs.ready_restatement_versions,
    )


def _blocked_invalid_ready_period_result(
    inputs: _InvalidReadyCompositePeriodInputs,
) -> tuple[CompositePeriodResult, str] | None:
    block_policies: tuple[
        Callable[[_InvalidReadyCompositePeriodInputs], tuple[CompositePeriodResult, str] | None],
        ...,
    ] = (
        _no_ready_member_return_facts_block,
        _nonpositive_composite_beginning_assets_block,
        _mixed_member_return_views_block,
        _mixed_member_reporting_currencies_block,
    )
    for block_policy in block_policies:
        blocked_result = block_policy(inputs)
        if blocked_result is not None:
            return blocked_result
    return None


def _blocked_composite_period_result_for_invalid_ready_facts(
    *,
    period_start: dt_date,
    period_end: dt_date,
    beginning_assets: Decimal,
    ending_assets: Decimal,
    ready_facts: Sequence[CompositeMemberReturnFactLike],
    excluded_facts: Sequence[CompositeMemberReturnFactLike],
    reason_codes: list[str],
    ready_return_views: list[str],
    ready_reporting_currencies: list[str],
    ready_source_fingerprints: list[str],
    ready_restatement_versions: list[str],
) -> tuple[CompositePeriodResult, str] | None:
    return _blocked_invalid_ready_period_result(
        _InvalidReadyCompositePeriodInputs(
            context=_InvalidReadyCompositePeriodContext(
                period_start=period_start,
                period_end=period_end,
                ready_facts=ready_facts,
                excluded_facts=excluded_facts,
            ),
            beginning_assets=beginning_assets,
            ending_assets=ending_assets,
            reason_codes=reason_codes,
            ready_return_views=ready_return_views,
            ready_reporting_currencies=ready_reporting_currencies,
            ready_source_fingerprints=ready_source_fingerprints,
            ready_restatement_versions=ready_restatement_versions,
        )
    )


def _build_composite_period_fact_set(
    *,
    period_start: dt_date,
    period_end: dt_date,
    facts: Sequence[CompositeMemberReturnFactLike],
) -> _CompositePeriodFactSet:
    ready_facts, excluded_facts = _classify_composite_period_facts(facts)
    metadata = _composite_period_fact_metadata(
        ready_facts=ready_facts,
        excluded_facts=excluded_facts,
    )
    return _CompositePeriodFactSet(
        period_start=period_start,
        period_end=period_end,
        ready_facts=ready_facts,
        excluded_facts=excluded_facts,
        reason_codes=metadata.reason_codes,
        beginning_assets=metadata.beginning_assets,
        ending_assets=metadata.ending_assets,
        ready_return_views=metadata.ready_return_views,
        ready_reporting_currencies=metadata.ready_reporting_currencies,
        ready_source_fingerprints=metadata.ready_source_fingerprints,
        ready_restatement_versions=metadata.ready_restatement_versions,
    )


def _classify_composite_period_facts(
    facts: Sequence[CompositeMemberReturnFactLike],
) -> tuple[list[CompositeMemberReturnFactLike], list[CompositeMemberReturnFactLike]]:
    ready_facts: list[CompositeMemberReturnFactLike] = []
    excluded_facts: list[CompositeMemberReturnFactLike] = []
    for fact in facts:
        if str(fact.status) == COMPOSITE_MEMBER_READY_STATUS:
            ready_facts.append(fact)
        else:
            excluded_facts.append(fact)
    return ready_facts, excluded_facts


def _sum_composite_member_assets(
    ready_facts: Sequence[CompositeMemberReturnFactLike],
    asset_value: Callable[[CompositeMemberReturnFactLike], Decimal],
) -> Decimal:
    return sum((asset_value(fact) for fact in ready_facts), Decimal("0"))


def _sorted_unique_composite_values(
    facts: Sequence[CompositeMemberReturnFactLike],
    value: Callable[[CompositeMemberReturnFactLike], str],
) -> list[str]:
    return sorted({value(fact) for fact in facts})


def _sorted_excluded_composite_reason_codes(excluded_facts: Sequence[CompositeMemberReturnFactLike]) -> list[str]:
    return sorted({code for fact in excluded_facts for code in fact.reason_codes})


def _composite_period_fact_metadata(
    *,
    ready_facts: Sequence[CompositeMemberReturnFactLike],
    excluded_facts: Sequence[CompositeMemberReturnFactLike],
) -> _CompositePeriodFactMetadata:
    return _CompositePeriodFactMetadata(
        reason_codes=_sorted_excluded_composite_reason_codes(excluded_facts),
        beginning_assets=_sum_composite_member_assets(ready_facts, lambda fact: fact.beginning_market_value),
        ending_assets=_sum_composite_member_assets(ready_facts, lambda fact: fact.ending_market_value),
        ready_return_views=_sorted_unique_composite_values(ready_facts, lambda fact: str(fact.return_view)),
        ready_reporting_currencies=_sorted_unique_composite_values(ready_facts, lambda fact: fact.reporting_currency),
        ready_source_fingerprints=_sorted_unique_composite_values(ready_facts, lambda fact: fact.source_fingerprint),
        ready_restatement_versions=_sorted_unique_composite_values(ready_facts, lambda fact: fact.restatement_version),
    )


def _build_ready_composite_period_result(
    *,
    period_fact_set: _CompositePeriodFactSet,
    cumulative_growth: Decimal,
) -> tuple[CompositePeriodResult, Decimal]:
    weighted_return, member_contributions = _build_ready_member_contributions(
        ready_facts=period_fact_set.ready_facts,
        beginning_assets=period_fact_set.beginning_assets,
    )
    next_cumulative_growth = cumulative_growth * (Decimal("1") + weighted_return)
    cumulative_return = next_cumulative_growth - Decimal("1")
    status = "READY" if not period_fact_set.excluded_facts else "DEGRADED"
    return (
        CompositePeriodResult(
            period_start=period_fact_set.period_start,
            period_end=period_fact_set.period_end,
            status=status,
            return_value=_quantize_decimal(weighted_return, COMPOSITE_RETURN_QUANTUM),
            cumulative_return=_quantize_decimal(cumulative_return, COMPOSITE_RETURN_QUANTUM),
            beginning_market_value=_quantize_decimal(period_fact_set.beginning_assets, COMPOSITE_ASSET_QUANTUM),
            ending_market_value=_quantize_decimal(period_fact_set.ending_assets, COMPOSITE_ASSET_QUANTUM),
            member_count=len(period_fact_set.ready_facts),
            excluded_member_count=len(period_fact_set.excluded_facts),
            dispersion_equal_weight=_sample_standard_deviation(
                [fact.return_value for fact in period_fact_set.ready_facts]
            ),
            return_view=period_fact_set.ready_return_views[0],
            reporting_currency=period_fact_set.ready_reporting_currencies[0],
            source_fingerprints=period_fact_set.ready_source_fingerprints,
            restatement_versions=period_fact_set.ready_restatement_versions,
            reason_codes=period_fact_set.reason_codes,
            member_contributions=member_contributions,
        ),
        next_cumulative_growth,
    )


def _group_composite_member_return_facts(
    *,
    composite_id: str,
    member_return_facts: Sequence[CompositeMemberReturnFactLike],
) -> dict[tuple[dt_date, dt_date], list[CompositeMemberReturnFactLike]]:
    grouped_facts: dict[tuple[dt_date, dt_date], list[CompositeMemberReturnFactLike]] = defaultdict(list)
    for fact in member_return_facts:
        if fact.composite_id != composite_id:
            continue
        grouped_facts[(fact.period_start, fact.period_end)].append(fact)
    return grouped_facts


def _composite_calculation_status(period_results: Sequence[CompositePeriodResult]) -> str:
    if all(period.status == "READY" for period in period_results):
        return "READY"
    if any(period.status == "READY" or period.status == "DEGRADED" for period in period_results):
        return "DEGRADED"
    return "BLOCKED"


def calculate_asset_weighted_composite_twr(
    *,
    composite_id: str,
    member_return_facts: Sequence[CompositeMemberReturnFactLike],
) -> CompositeCalculationResult:
    grouped_facts = _group_composite_member_return_facts(
        composite_id=composite_id,
        member_return_facts=member_return_facts,
    )

    period_results: list[CompositePeriodResult] = []
    cumulative_growth = Decimal("1")
    aggregate_reason_codes: set[str] = set()

    for period_start, period_end in sorted(grouped_facts):
        facts = grouped_facts[(period_start, period_end)]
        period_fact_set = _build_composite_period_fact_set(
            period_start=period_start,
            period_end=period_end,
            facts=facts,
        )
        aggregate_reason_codes.update(period_fact_set.reason_codes)
        blocked_period = _blocked_composite_period_result_for_invalid_ready_facts(
            period_start=period_start,
            period_end=period_end,
            beginning_assets=period_fact_set.beginning_assets,
            ending_assets=period_fact_set.ending_assets,
            ready_facts=period_fact_set.ready_facts,
            excluded_facts=period_fact_set.excluded_facts,
            reason_codes=period_fact_set.reason_codes,
            ready_return_views=period_fact_set.ready_return_views,
            ready_reporting_currencies=period_fact_set.ready_reporting_currencies,
            ready_source_fingerprints=period_fact_set.ready_source_fingerprints,
            ready_restatement_versions=period_fact_set.ready_restatement_versions,
        )
        if blocked_period is not None:
            period_result, aggregate_reason_code = blocked_period
            period_results.append(period_result)
            aggregate_reason_codes.add(aggregate_reason_code)
            continue

        period_result, cumulative_growth = _build_ready_composite_period_result(
            period_fact_set=period_fact_set,
            cumulative_growth=cumulative_growth,
        )
        period_results.append(period_result)

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
    return CompositeCalculationResult(
        composite_id=composite_id,
        status=_composite_calculation_status(period_results),
        period_results=period_results,
        cumulative_return=terminal_cumulative,
        reason_codes=sorted(aggregate_reason_codes),
    )
