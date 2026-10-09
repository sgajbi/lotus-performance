"""Independent rational component oracles and exact inclusion-evidence refusals."""

import re
from copy import deepcopy
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from app.models.composite_component_model_fees import CompositeComponentModelFeeProfile, CompositeGrossComponentEvidence
from app.services.composite_materialization.component_model_fee_returns import component_model_net_return
from tests.unit.models.test_composite_component_model_fees import component_case, member


def calculate(wire, evidence, gross="0.02"):
    return component_model_net_return(
        Decimal(gross),
        profile=CompositeComponentModelFeeProfile.model_validate(wire),
        gross_evidence=CompositeGrossComponentEvidence.model_validate(evidence),
    )


def test_same_economic_charge_offsets_once_and_container_is_not_charged():
    wire, evidence = component_case()
    original = deepcopy((wire, evidence))
    result = calculate(wire, evidence)
    assert Fraction(result.model_net_return) == Fraction(148, 12500)
    assert Fraction(result.total_component_fee_fraction) == Fraction(1, 100)
    assert Fraction(result.already_included_fee_fraction) == Fraction(1, 500)
    assert Fraction(result.deducted_fee_fraction) == Fraction(1, 125)
    assert (wire, evidence) == original


def test_same_category_different_economic_charge_is_not_an_offset():
    wire, evidence = component_case()
    transaction = member(wire)["components"][-1]
    transaction.update(treatment="DEDUCT", gross_inclusion_evidence=None)
    evidence["included_components"][0].update(
        component_id="historical.transaction", economic_charge_id="historical.charge"
    )
    assert Fraction(calculate(wire, evidence).model_net_return) == Fraction(49, 5000)
    transaction.update(
        treatment="ALREADY_INCLUDED_IN_GROSS",
        gross_inclusion_evidence=evidence["included_components"][0]["source_evidence"],
    )
    with pytest.raises(ValueError, match="exact economic-charge evidence"):
        calculate(wire, evidence)


def test_already_included_economic_charge_cannot_be_deducted_again():
    wire, evidence = component_case()
    member(wire)["components"][-1].update(treatment="DEDUCT", gross_inclusion_evidence=None)
    with pytest.raises(ValueError, match="deducted again"):
        calculate(wire, evidence)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "foreign-tenant"),
        ("composite_id", "foreign-composite"),
        ("member_id", "foreign-member"),
        ("period_start", "2026-01-02"),
        ("period_end", "2026-01-30"),
        ("reporting_currency", "EUR"),
        ("gross_receipt_digest", "sha256:" + "9" * 64),
    ],
)
def test_foreign_gross_component_scope_refuses(field, value):
    wire, evidence = component_case()
    evidence["scope"][field] = value
    with pytest.raises(ValueError):
        calculate(wire, evidence)


@pytest.mark.parametrize("field", ["method_binding", "calendar_binding", "reference_base"])
def test_changed_full_scope_binding_refuses(field):
    wire, evidence = component_case()
    evidence["scope"][field]["revision"] = "foreign.2"
    with pytest.raises(ValueError, match="foreign scope"):
        calculate(wire, evidence)


@pytest.mark.parametrize("fault", ["component", "category", "fraction", "base", "source", "aggregate"])
def test_mismatched_original_component_evidence_refuses(fault):
    wire, evidence = component_case()
    included = evidence["included_components"][0]
    if fault == "component":
        included["component_id"] = "other.component"
    elif fault == "category":
        included["category"] = "CUSTODY_FEE"
    elif fault == "fraction":
        included["period_fee_fraction"] = "0.001"
    elif fault == "base":
        included["reference_base"]["revision"] = "foreign.2"
    elif fault == "source":
        included["source_evidence"]["revision"] = "foreign.2"
    else:
        evidence["evidence_binding"]["revision"] = "foreign.2"
    with pytest.raises(ValueError):
        calculate(wire, evidence)


def test_unknown_allocation_total_and_mixed_component_base_refuse():
    wire, evidence = component_case()
    member(wire)["bundles"][0]["declared_period_fee_fraction"] = "0.011"
    with pytest.raises(ValueError, match="reconcile"):
        calculate(wire, evidence)
    wire, evidence = component_case()
    member(wire)["components"][0]["reference_base"]["revision"] = "foreign.2"
    with pytest.raises(ValueError, match="same post-gross"):
        calculate(wire, evidence)


def test_exact_zero_and_total_component_fee_domain():
    wire, evidence = component_case()
    for component in member(wire)["components"]:
        component["period_fee_fraction"] = "0"
    member(wire)["bundles"][0]["declared_period_fee_fraction"] = "0"
    evidence["included_components"][0]["period_fee_fraction"] = "0"
    result = calculate(wire, evidence)
    assert result.model_net_return == Decimal("0.02") and result.deducted_fee_fraction == 0
    member(wire)["bundles"] = []
    wire["bundled_fee_context"] = "UNBUNDLED"
    for component in member(wire)["components"]:
        component.update(period_fee_fraction="0.3", treatment="DEDUCT", gross_inclusion_evidence=None)
    evidence["included_components"] = []
    with pytest.raises(ValueError, match="Total component fee"):
        calculate(wire, evidence)


def test_precision_and_flags_survive_hostile_caller_context():
    wire, evidence = component_case()
    member(wire)["components"][2]["period_fee_fraction"] = "0.006" + "0" * 40 + "1"
    member(wire)["bundles"][0]["declared_period_fee_fraction"] = "0.010" + "0" * 40 + "1"
    gross = "0.020" + "0" * 40 + "1"
    fee = Fraction(member(wire)["bundles"][0]["declared_period_fee_fraction"]) - Fraction(1, 500)
    expected = (1 + Fraction(gross)) * (1 - fee) - 1
    with localcontext() as caller:
        caller.prec, caller.rounding, caller.Emin, caller.Emax = 6, ROUND_DOWN, -9, 9
        caller.traps[Inexact] = caller.traps[Rounded] = True
        before = (dict(caller.flags), dict(caller.traps))
        result = calculate(wire, evidence, gross)
        assert Fraction(result.model_net_return) == expected
        assert before == (dict(caller.flags), dict(caller.traps))


@pytest.mark.parametrize("gross", ["NaN", "Infinity", "-1.001"])
def test_component_method_retains_existing_gross_wealth_domain(gross):
    wire, evidence = component_case()
    with pytest.raises(ValueError):
        calculate(wire, evidence, gross)


def test_total_fee_exactly_one_refuses_even_when_offset_would_reduce_deduction():
    wire, evidence = component_case()
    wire["bundled_fee_context"] = "UNBUNDLED"
    member(wire)["bundles"] = []
    for component in member(wire)["components"]:
        component["period_fee_fraction"] = "0.25"
    evidence["included_components"][0]["period_fee_fraction"] = "0.25"
    with pytest.raises(ValueError, match="Total component fee"):
        calculate(wire, evidence)


def test_methodology_worked_allocation_and_output_match_executed_convention():
    path = Path(__file__).resolve().parents[3] / "docs/methodologies/metrics/metric-composite-component-model-fee.md"
    worked = path.read_text(encoding="utf-8").split("## Worked Example\n", 1)[1]
    rows = re.findall(
        r"^\| (Transaction|Management/advisory|Custody|Administration) \| ([0-9.]+) \| [^|]+ \| ([0-9.]+) \|$",
        worked,
        flags=re.MULTILINE,
    )
    assert len(rows) == 4
    wire, evidence = component_case()
    fractions = {row["component_id"]: Fraction(row["period_fee_fraction"]) for row in member(wire)["components"]}
    labels = {
        "Transaction": "transaction",
        "Management/advisory": "management",
        "Custody": "custody",
        "Administration": "administration",
    }
    for label, fraction, _ in rows:
        assert Fraction(fraction) == fractions[labels[label]]
    expected = (1 + Fraction(1, 50)) * (1 - sum(Fraction(deducted) for _, _, deducted in rows)) - 1
    assert Fraction(calculate(wire, evidence).model_net_return) == expected
    documented = re.search(r"model_net_return = ([0-9.]+)", worked)
    assert documented is not None and Fraction(documented.group(1)) == expected
