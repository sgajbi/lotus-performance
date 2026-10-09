"""One elected common-base periodic convention; no source or approval authority."""

from dataclasses import dataclass
from decimal import Decimal

from app.models.composite_component_model_fees import (
    CompositeComponentModelFeeProfile,
    CompositeGrossComponentEvidence,
    CompositeGrossComponentScope,
)
from app.services.composite_materialization.model_fee_returns import periodic_model_net_return
from engine.numerical_boundary import monetary_arithmetic_context


@dataclass(frozen=True)
class ComponentModelFeeResult:
    total_component_fee_fraction: Decimal
    already_included_fee_fraction: Decimal
    deducted_fee_fraction: Decimal
    model_net_return: Decimal


def _selected_entry(profile, scope):
    periods = [
        row for row in profile.periods if (row.period_start, row.period_end) == (scope.period_start, scope.period_end)
    ]
    if len(periods) != 1:
        raise ValueError("Component fee requires an exact complete period")
    members = [row for row in periods[0].member_rates if row.member_id == scope.member_id]
    if len(members) != 1:
        raise ValueError("Component fee requires the exact admitted member")
    entry = members[0]
    expected = CompositeGrossComponentScope(
        tenant_id=profile.tenant_id,
        composite_id=profile.composite_id,
        member_id=entry.member_id,
        period_start=periods[0].period_start,
        period_end=periods[0].period_end,
        reporting_currency=profile.reporting_currency,
        method_binding=profile.method_binding,
        calendar_binding=profile.calendar_binding,
        gross_receipt_digest=entry.gross_receipt_digest,
        reference_base=entry.reference_base,
    )
    if scope != expected:
        raise ValueError("Gross inclusion evidence has a foreign scope, receipt, method or reference base")
    return entry


def _require_bundle_reconciliation(entry):
    by_id = {row.component_id: Decimal(row.period_fee_fraction) for row in entry.components}
    for bundle in entry.bundles:
        if sum((by_id[component_id] for component_id in bundle.component_ids), Decimal(0)) != Decimal(
            bundle.declared_period_fee_fraction
        ):
            raise ValueError("Explicit component allocations do not reconcile to the declared bundle fraction")


def _included_component_fraction(component, evidence):
    matches = [row for row in evidence.included_components if row.economic_charge_id == component.economic_charge_id]
    if component.treatment == "DEDUCT":
        if matches:
            raise ValueError("An already included economic charge cannot be deducted again")
        return Decimal(0)
    if len(matches) != 1:
        raise ValueError("An included offset requires exact economic-charge evidence, never category matching")
    original = matches[0]
    if (
        original.component_id,
        original.category,
        original.reference_base,
        Decimal(original.period_fee_fraction),
        original.source_evidence,
    ) != (
        component.component_id,
        component.category,
        component.reference_base,
        Decimal(component.period_fee_fraction),
        component.gross_inclusion_evidence,
    ):
        raise ValueError("Gross inclusion evidence differs from the exact component, amount or base")
    return Decimal(component.period_fee_fraction)


def _require_original_evidence_base(entry, gross_evidence):
    if gross_evidence.evidence_binding != entry.gross_component_evidence_binding:
        raise ValueError("Gross component evidence differs from the pinned source binding")
    if any(row.reference_base != entry.reference_base for row in entry.components):
        raise ValueError("Every allocated component requires the same post-gross wealth reference base")


def _arithmetic_values(entry, gross_evidence):
    values = [Decimal(row.period_fee_fraction) for row in entry.components]
    values.extend(Decimal(row.declared_period_fee_fraction) for row in entry.bundles)
    values.extend(Decimal(row.period_fee_fraction) for row in gross_evidence.included_components)
    return values


def component_model_net_return(
    gross_return: Decimal,
    *,
    profile: CompositeComponentModelFeeProfile,
    gross_evidence: CompositeGrossComponentEvidence,
) -> ComponentModelFeeResult:
    entry = _selected_entry(profile, gross_evidence.scope)
    _require_original_evidence_base(entry, gross_evidence)
    values = _arithmetic_values(entry, gross_evidence)
    with monetary_arithmetic_context([gross_return, Decimal(1), *values], products=True):
        _require_bundle_reconciliation(entry)
        total = sum((Decimal(row.period_fee_fraction) for row in entry.components), Decimal(0))
        if not Decimal(0) <= total < Decimal(1):
            raise ValueError("Total component fee is outside the periodic wealth-fraction domain")
        included = sum((_included_component_fraction(row, gross_evidence) for row in entry.components), Decimal(0))
        deducted = total - included
        result = periodic_model_net_return(gross_return, deducted)
    return ComponentModelFeeResult(total, included, deducted, result)
