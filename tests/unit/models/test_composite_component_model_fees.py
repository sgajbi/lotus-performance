"""Separate component contract; synthetic evidence does not grant approval."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.composite_component_model_fees import CompositeComponentModelFeeProfile, CompositeGrossComponentEvidence


def binding(name, digit):
    return {"product_name": name, "product_version": "v1", "revision": "synthetic.1", "digest": "sha256:" + digit * 64}


@pytest.mark.parametrize("fault", ["unsorted", "duplicate"])
def test_bundle_requires_canonical_component_identity_order(fault):
    wire, _ = component_case()
    CompositeComponentModelFeeProfile.model_validate(wire)
    identities = wire["periods"][0]["member_rates"][0]["bundles"][0]["component_ids"]
    if fault == "unsorted":
        identities.reverse()
    else:
        identities.append(identities[-1])
    with pytest.raises(ValueError, match="sorted and unique"):
        CompositeComponentModelFeeProfile.model_validate(wire)


def component_case():
    base = binding("SyntheticPostGrossWealthReference", "a")
    inclusion = binding("SyntheticGrossTransactionCostEvidence", "b")
    aggregate = binding("SyntheticGrossComponentEvidence", "c")
    components = [
        {
            "component_id": name,
            "economic_charge_id": "charge." + name,
            "category": category,
            "period_fee_fraction": fraction,
            "reference_base": deepcopy(base),
            "allocation_evidence": binding("SyntheticComponentAllocation", "d"),
            "treatment": "ALREADY_INCLUDED_IN_GROSS" if name == "transaction" else "DEDUCT",
            "gross_inclusion_evidence": deepcopy(inclusion) if name == "transaction" else None,
        }
        for name, category, fraction in (
            ("administration", "ADMINISTRATION_FEE", "0.001"),
            ("custody", "CUSTODY_FEE", "0.001"),
            ("management", "MANAGEMENT_ADVISORY_FEE", "0.006"),
            ("transaction", "TRANSACTION_COST", "0.002"),
        )
    ]
    wire = {
        "product_name": "CompositeComponentPeriodicModelFeeProfile",
        "product_version": "v1",
        "profile_id": "synthetic.components",
        "revision": "profile.1",
        "tenant_id": "tenant-a",
        "composite_id": "synthetic.composite",
        "method_binding": binding("SyntheticComponentPeriodicMethod", "e"),
        "calendar_binding": binding("SyntheticCompleteCalendar", "f"),
        "effective_from": "2026-01-01",
        "effective_to": "2026-01-31",
        "reporting_currency": "USD",
        "gross_source_basis": "GROSS",
        "reference_base_basis": "COMMON_POST_GROSS_WEALTH",
        "rate_basis": "EXPLICIT_ALLOCATED_PERIOD_WEALTH_FRACTIONS",
        "bundled_fee_context": "WRAP",
        "timing": "END_OF_COMPLETE_PERIOD_AFTER_GROSS_RETURN",
        "transformation": "MULTIPLICATIVE_WEALTH_HAIRCUT",
        "asset_treatment": "UNCHANGED_SOURCE_ASSETS_BEGINNING_ASSET_WEIGHTING",
        "monetary_precision": "DECIMAL_STRICT_NO_INTERMEDIATE_ROUNDING",
        "standards_applicability": "NOT_ASSESSED_ENGINEERING_METHOD_ONLY",
        "periods": [
            {
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "member_rates": [
                    {
                        "entry_id": "entry.member-a.january",
                        "member_id": "member-a",
                        "gross_receipt_digest": "sha256:" + "1" * 64,
                        "gross_component_evidence_binding": deepcopy(aggregate),
                        "reference_base": deepcopy(base),
                        "components": components,
                        "bundles": [
                            {
                                "bundle_id": "bundle.wrap",
                                "component_ids": [row["component_id"] for row in components],
                                "declared_period_fee_fraction": "0.010",
                                "allocation_evidence": binding("SyntheticBundleAllocation", "2"),
                            }
                        ],
                    }
                ],
            }
        ],
    }
    evidence = {
        "scope": {
            **{
                field: deepcopy(wire[field])
                for field in ("tenant_id", "composite_id", "reporting_currency", "method_binding", "calendar_binding")
            },
            "member_id": "member-a",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gross_receipt_digest": "sha256:" + "1" * 64,
            "reference_base": deepcopy(base),
        },
        "evidence_binding": aggregate,
        "included_components": [
            {
                "component_id": "transaction",
                "economic_charge_id": "charge.transaction",
                "category": "TRANSACTION_COST",
                "period_fee_fraction": "0.002",
                "reference_base": deepcopy(base),
                "source_evidence": inclusion,
            }
        ],
    }
    return wire, evidence


def member(wire):
    return wire["periods"][0]["member_rates"][0]


def test_explicit_component_profile_and_evidence_roundtrip():
    wire, evidence = component_case()
    assert CompositeComponentModelFeeProfile.model_validate(wire).model_dump(mode="json") == wire
    assert CompositeGrossComponentEvidence.model_validate(evidence).model_dump(mode="json") == evidence


@pytest.mark.parametrize(
    "fault", ["component", "economic-charge", "container-charge", "unknown", "overlap", "incomplete"]
)
def test_duplicate_or_unknown_bundle_economics_refuse(fault):
    wire, _ = component_case()
    entry = member(wire)
    if fault == "component":
        entry["components"].append(deepcopy(entry["components"][0]))
    elif fault == "economic-charge":
        entry["components"][1]["economic_charge_id"] = entry["components"][0]["economic_charge_id"]
    elif fault == "container-charge":
        entry["bundles"][0]["bundle_id"] = entry["components"][0]["component_id"]
    elif fault == "unknown":
        entry["bundles"][0]["component_ids"] = ["unknown"]
    elif fault == "overlap":
        extra = deepcopy(entry["bundles"][0])
        extra["bundle_id"] = "bundle.second"
        entry["bundles"].append(extra)
    else:
        entry["bundles"][0]["component_ids"].pop()
    with pytest.raises(ValidationError):
        CompositeComponentModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("value", ["-0.001", "1", "NaN", "Infinity", None])
def test_unsupported_or_unknown_allocated_fraction_refuses(value):
    wire, _ = component_case()
    member(wire)["components"][0]["period_fee_fraction"] = value
    with pytest.raises(ValidationError):
        CompositeComponentModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("category", ["PERFORMANCE_FEE", "REBATE", "WITHHOLDING_TAX", "INDIRECT_FUND_COST"])
def test_recognizing_taxonomy_does_not_enable_unspecified_fee_methods(category):
    wire, _ = component_case()
    member(wire)["components"][0]["category"] = category
    with pytest.raises(ValidationError):
        CompositeComponentModelFeeProfile.model_validate(wire)


def test_offset_requires_explicit_evidence_and_bundle_is_not_a_second_deduction():
    wire, _ = component_case()
    member(wire)["components"][-1]["gross_inclusion_evidence"] = None
    with pytest.raises(ValidationError):
        CompositeComponentModelFeeProfile.model_validate(wire)
    wire, _ = component_case()
    member(wire)["bundles"][0]["treatment"] = "DEDUCT"
    with pytest.raises(ValidationError):
        CompositeComponentModelFeeProfile.model_validate(wire)


def test_inverted_middle_period_cannot_hide_in_adjacent_profile_boundaries():
    wire, _ = component_case()
    first = wire["periods"][0]
    first["period_end"] = "2026-01-02"
    middle, last = deepcopy(first), deepcopy(first)
    middle.update(period_start="2026-01-03", period_end="2026-01-02")
    last.update(period_start="2026-01-03", period_end="2026-01-31")
    middle["member_rates"][0]["entry_id"] = "entry.middle"
    last["member_rates"][0]["entry_id"] = "entry.last"
    wire["periods"] = [first, middle, last]
    with pytest.raises(ValidationError):
        CompositeComponentModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("fault", ["duplicate-container", "unbundled-container", "empty-wrap", "duplicate-member"])
def test_container_and_population_identity_refusals(fault):
    wire, _ = component_case()
    entry = member(wire)
    if fault == "duplicate-container":
        entry["bundles"].append(deepcopy(entry["bundles"][0]))
    elif fault == "unbundled-container":
        wire["bundled_fee_context"] = "UNBUNDLED"
    elif fault == "empty-wrap":
        entry["bundles"] = []
    else:
        extra = deepcopy(entry)
        extra["entry_id"] = "another.entry"
        wire["periods"][0]["member_rates"].append(extra)
    with pytest.raises(ValidationError):
        CompositeComponentModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("same_component_id", [True, False])
def test_duplicate_original_economic_charge_evidence_refuses(same_component_id):
    _, evidence = component_case()
    extra = deepcopy(evidence["included_components"][0])
    if not same_component_id:
        extra["component_id"] = "another.component"
    evidence["included_components"].append(extra)
    with pytest.raises(ValidationError):
        CompositeGrossComponentEvidence.model_validate(evidence)
