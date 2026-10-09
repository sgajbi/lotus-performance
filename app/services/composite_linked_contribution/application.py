from collections import defaultdict
from decimal import Decimal, DecimalException, localcontext
from typing import NoReturn, cast

from app.models.composite_linked_contribution import (
    CompositeLinkedContributionRequest,
    CompositeLinkedContributionResponse,
    LinkedMemberPeriod,
    LinkedMemberTotal,
)
from app.models.composites import CompositeTWRSelectionManifest
from app.services.calculation_engine_version import calculation_engine_version
from app.services.composite_calculation_service import select_composite_materialization_facts
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIUnprocessableEntityError
from engine.composites import COMPOSITE_RETURN_QUANTUM, calculate_asset_weighted_composite_twr
from engine.contribution_smoothing import _calculate_carino_factor_for_return


def _refuse(code: str) -> NoReturn:
    raise APIUnprocessableEntityError("Retained Composite linked contribution is unavailable.", error_code=code)


def _ready_window_members(facts, window):
    return sorted(
        (
            fact
            for fact in facts
            if (fact.period_start, fact.period_end) == (window.period_start, window.period_end)
            and str(fact.status) == "READY"
        ),
        key=lambda fact: fact.portfolio_id,
    )


def _period_rows(facts, windows) -> tuple[list[LinkedMemberPeriod], Decimal]:
    rows, growth = [], Decimal(1)
    for window in windows:
        members = _ready_window_members(facts, window)
        assets = sum((fact.beginning_market_value for fact in members), Decimal(0))
        contributions = [fact.return_value * fact.beginning_market_value / assets for fact in members]
        period_return = sum(contributions, Decimal(0))
        try:
            factor = _calculate_carino_factor_for_return(period_return, strict_decimal=True)
        except ValueError:
            _refuse("COMPOSITE_CARINO_LOG_DOMAIN_REFUSED")
        growth *= 1 + period_return
        for fact, contribution in zip(members, contributions, strict=True):
            rows.append(
                LinkedMemberPeriod(
                    **fact.model_dump(
                        include={
                            "portfolio_id",
                            "period_start",
                            "period_end",
                            "return_value",
                            "beginning_market_value",
                            "source_snapshot_id",
                            "source_fingerprint",
                            "calculation_id",
                            "restatement_version",
                            "restatement_sequence",
                        }
                    ),
                    weight=fact.beginning_market_value / assets,
                    contribution=contribution,
                    linking_factor=factor,
                    linked_contribution=Decimal(0),
                    source_authority_identity=fact.source_authority_identity,
                )
            )
    return rows, growth - 1


def _link(rows: list[LinkedMemberPeriod], cumulative_return: Decimal) -> list[LinkedMemberTotal]:
    try:
        factor = cast(Decimal, _calculate_carino_factor_for_return(cumulative_return, strict_decimal=True))
    except ValueError:
        _refuse("COMPOSITE_CARINO_PRECISION_REFUSED")
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        row.linking_factor /= factor
        row.linked_contribution = row.contribution * row.linking_factor
        totals[row.portfolio_id] += row.linked_contribution
        counts[row.portfolio_id] += 1
    return [
        LinkedMemberTotal(
            portfolio_id=identity, linked_contribution=totals[identity], participating_period_count=counts[identity]
        )
        for identity in sorted(totals)
    ]


def _linked_economics(facts, windows):
    with localcontext() as context:
        context.prec = 80
        rows, cumulative = _period_rows(facts, windows)
        members = _link(rows, cumulative)
        total = sum((member.linked_contribution for member in members), Decimal(0))
        difference = total - cumulative
        if abs(difference) > Decimal("1e-60"):
            _refuse("COMPOSITE_CARINO_PRECISION_REFUSED")
        display_difference = sum(
            (member.linked_contribution.quantize(COMPOSITE_RETURN_QUANTUM) for member in members), Decimal(0)
        ) - cumulative.quantize(COMPOSITE_RETURN_QUANTUM)
    return cumulative, total, difference, display_difference, members, rows


def calculate_linked_member_contribution(
    request: CompositeLinkedContributionRequest, *, tenant_id: str
) -> CompositeLinkedContributionResponse:
    facts, windows = select_composite_materialization_facts(tenant_id=tenant_id, request=request)
    try:
        admitted = calculate_asset_weighted_composite_twr(composite_id=request.composite_id, member_return_facts=facts)
        if admitted.status != "READY":
            _refuse("COMPOSITE_CONSTITUENT_DECOMPOSITION_UNAVAILABLE")
        cumulative, total, difference, display_difference, members, rows = _linked_economics(facts, windows)
    except DecimalException:
        _refuse("COMPOSITE_CARINO_PRECISION_REFUSED")
    version = calculation_engine_version()
    response = CompositeLinkedContributionResponse(
        calculation_id=request.calculation_id,
        composite_id=request.composite_id,
        period_start=request.period_start,
        period_end=request.period_end,
        return_view=request.return_view,
        reporting_currency=admitted.period_results[0].reporting_currency,
        cumulative_return=cumulative,
        total_linked_contribution=total,
        reconciliation_difference=difference,
        display_rounding_difference=display_difference,
        members=members,
        periods=rows,
        selection_manifest=CompositeTWRSelectionManifest(
            windows=windows, engine_version=version, calculation_fingerprint="pending"
        ),
    )
    response.selection_manifest.calculation_fingerprint = generate_value_fingerprint(
        {
            "tenant_id": tenant_id,
            "request": request.model_dump(mode="json"),
            "result": response.model_dump(mode="json", exclude={"selection_manifest"}),
            "windows": [window.model_dump(mode="json") for window in windows],
        },
        version,
    )[0]
    return response
