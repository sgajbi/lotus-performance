"""Shared retained FX compatibility before linking any financial window vector."""

from dataclasses import dataclass
from typing import Any

from app.models.composite_currency_normalization import CompositeFXNormalizationSource
from app.models.composite_materialization import CompositeMemberOutcomeState
from app.services.composite_materialization.records import MaterializationRecord
from core.errors import APIConflictError, APIUnprocessableEntityError


@dataclass(frozen=True)
class CurrencyWindowAuthority:
    normalization_method: dict[str, Any] | None
    native_currency: str
    member_money_currencies: dict[str, str]


def retained_currency_authority(record: MaterializationRecord) -> CurrencyWindowAuthority:
    if record.source is None:
        raise APIConflictError("A required retained window is unavailable.", error_code="REQUIRED_PERIOD_UNAVAILABLE")
    native = record.source.definition.reporting_currency
    wire = record.source.currency_normalization_wire
    if wire is None:
        return CurrencyWindowAuthority(None, native, {})
    # Callers first admit each record's raw source and normalized member custody.
    source = CompositeFXNormalizationSource.model_validate(wire)
    participating = {row.portfolio_id for row in record.outcomes if row.state == CompositeMemberOutcomeState.READY}
    return CurrencyWindowAuthority(
        source.method_binding.model_dump(mode="json"),
        native,
        {
            member.member_id: member.source_money_currency
            for member in source.members
            if member.member_id in participating
        },
    )


def require_compatible_currency_authority(
    previous: CurrencyWindowAuthority | None, selected: CurrencyWindowAuthority
) -> None:
    if previous is None:
        return
    continuing = previous.member_money_currencies.keys() & selected.member_money_currencies.keys()
    if previous.native_currency != selected.native_currency or any(
        previous.member_money_currencies[member] != selected.member_money_currencies[member] for member in continuing
    ):
        raise APIUnprocessableEntityError(
            "Selected native-currency regimes require admitted membership and history treatment.",
            error_code="COMPOSITE_VECTOR_CURRENCY_REGIME_UNAVAILABLE",
        )
    if previous.normalization_method != selected.normalization_method:
        raise APIUnprocessableEntityError(
            "Selected window method or policy authority differs.", error_code="COMPOSITE_VECTOR_METHOD_MISMATCH"
        )


def require_compatible_currency_windows(records: list[MaterializationRecord]) -> None:
    previous = None
    for record in records:
        selected = retained_currency_authority(record)
        require_compatible_currency_authority(previous, selected)
        previous = selected
