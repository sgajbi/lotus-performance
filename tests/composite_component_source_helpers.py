"""Frozen synthetic whole-cost supplier; no real producer or institutional qualification."""

from copy import deepcopy
from decimal import Decimal

from app.models.composite_authority import authority_digest
from app.models.composite_component_costs import CompositeGrossCostSource
from app.models.composite_eligibility_evidence import VerificationReceipt
from app.ports import composite_external_evidence as approvals
from app.services.composite_materialization.component_cost_admission import financial_verification_request
from engine.numerical_boundary import monetary_arithmetic_context
from tests.composite_eligibility_helpers import verification_expectation
from tests.unit.models.test_composite_component_model_fees import component_case


def component_source_inputs(packet, gross_outcomes, *, distinct=False, zero=False, false_base=False):
    profile, template = component_case()
    profile.update(
        tenant_id=packet["definition"]["tenant_id"],
        composite_id=packet["definition"]["composite_id"],
        effective_from="2026-01-05",
        effective_to="2026-01-05",
    )
    original = profile["periods"][0]["member_rates"][0]
    entries, members = [], []
    for outcome in gross_outcomes:
        fact = outcome.fact
        entry, evidence = deepcopy(original), deepcopy(template)
        scope = evidence["scope"]
        scope.update(
            tenant_id=profile["tenant_id"],
            composite_id=profile["composite_id"],
            member_id=outcome.portfolio_id,
            period_start="2026-01-05",
            period_end="2026-01-05",
            gross_receipt_digest=fact.source_snapshot_id,
        )
        entry.update(
            entry_id="day." + outcome.portfolio_id,
            member_id=outcome.portfolio_id,
            gross_receipt_digest=fact.source_snapshot_id,
        )
        if distinct or zero:
            entry["components"][-1].update(treatment="DEDUCT", gross_inclusion_evidence=None)
            evidence["included_components"] = []
        if zero:
            for component in entry["components"]:
                component["period_fee_fraction"] = "0"
            entry["bundles"][0]["declared_period_fee_fraction"] = "0"
        with monetary_arithmetic_context([fact.beginning_market_value, fact.return_value, Decimal(1)], products=True):
            amount = format(fact.beginning_market_value * (1 + fact.return_value), "f")
        if false_base and outcome.portfolio_id == "C":
            amount = "999"
        reference = {
            "gross_receipt_digest": fact.source_snapshot_id,
            "reporting_currency": "USD",
            "reference_wealth_amount": amount,
            "reference_wealth_convention": "BEGINNING_ASSETS_TIMES_GROSS_WEALTH_FACTOR",
        }
        base = {
            "product_name": "CompositePostGrossWealthReference",
            "product_version": "v1",
            "revision": "base.1",
            "digest": authority_digest(reference),
        }
        entry["reference_base"] = scope["reference_base"] = base
        for component in entry["components"]:
            component["reference_base"] = base
        for included in evidence["included_components"]:
            included["reference_base"] = base
        member = {
            "evidence": evidence,
            "completeness": "COMPLETE_ZERO" if not evidence["included_components"] else "COMPLETE_COMPONENTS",
            "reference_wealth_amount": amount,
            "reference_wealth_convention": reference["reference_wealth_convention"],
        }
        payload = deepcopy(member)
        del payload["evidence"]["evidence_binding"]
        binding = {
            "product_name": "CompositeGrossComponentEvidence",
            "product_version": "v1",
            "revision": "cost." + outcome.portfolio_id,
            "digest": authority_digest(payload),
        }
        evidence["evidence_binding"] = entry["gross_component_evidence_binding"] = binding
        entries.append(entry)
        members.append(member)
    profile["periods"] = [{"period_start": "2026-01-05", "period_end": "2026-01-05", "member_rates": entries}]
    return profile, members


def financial_source(packet, command, members):
    return {
        "product_name": "CompositeGrossCostSource",
        "product_version": "v1",
        "revision": "source.1",
        "producer_id": "synthetic.cost.issuer",
        "source_cut_id": command.source_cut_id,
        "source_watermark": "synthetic.original.watermark",
        "definition_content_hash": command.definition_content_hash,
        "membership_content_hash": command.membership_content_hash,
        "attestation_content_hash": command.attestation_content_hash,
        "model_fee_binding": command.model_fee_binding.model_dump(mode="json"),
        "members": members,
    }


class FrozenFinancialSupplier:
    def __init__(self, wire, request):
        self.wire, self.request = deepcopy(wire), request
        self.calls = 0

    def resolve(self, request):
        self.calls += 1
        return deepcopy(self.wire) if request == self.request else approvals.UnavailableCompositeEvidence()


class FrozenFinancialVerifier:
    def __init__(self, wire, request, definition_version):
        expected = financial_verification_request(
            CompositeGrossCostSource.model_validate(wire), request, definition_version
        )
        payload = dict(
            product_name="CompositeEvidenceVerificationReceipt",
            product_version="v1",
            artifact_digest=authority_digest(wire),
            artifact_revision="artifact.1",
            issuer_id=wire["producer_id"],
            posture="SYNTHETIC_NON_CERTIFYING",
            request=expected.model_dump(),
            verifier_id="synthetic.cost.verifier",
        )
        payload["content_hash"] = authority_digest(payload)
        self.receipt = VerificationReceipt.model_validate(payload)
        self.expectation = verification_expectation(self.receipt)

    def verify(self, request):
        if request != self.receipt.request:
            return approvals.UnavailableCompositeEvidence()
        return approvals.VerifiedCompositeEvidence(self.receipt, self.expectation)
