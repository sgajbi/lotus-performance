"""Retained producer history and explicitly synthetic new-contract test projections.

The marked receipt below is a consumer control fixture, not a producer HTTP/PG
publication claim. Original producer approvals are never rewritten on disk.
"""

import json
from copy import deepcopy
from pathlib import Path

from app.models.composite_authority import authority_digest, legacy_composite_product_digest
from app.models.composite_eligibility_evidence import _month_window

FIXTURES = Path(__file__).parent / "fixtures"


def monthly_approvals():
    return json.loads((FIXTURES / "composite_monthly_66aec9d2_approvals.json").read_text(encoding="utf-8"))


def rehash(payload):
    payload["content_hash"] = authority_digest({key: value for key, value in payload.items() if key != "content_hash"})


def rehash_approval(approval):
    rehash(approval["proposal"])
    approval["claims_digest"] = authority_digest(
        {
            "purpose": "COMPOSITE_MONTHLY_MEMBERSHIP_APPROVAL",
            "proposal_content_hash": approval["proposal"]["content_hash"],
            "approved_by": approval["approved_by"],
            "approved_at": approval["approved_at"],
        }
    )
    rehash(approval)


def synthetic_monthly_packet():
    approval = deepcopy(monthly_approvals()[2])
    proposal = approval["proposal"]
    proposal["publication_evidence_version"] = "v1"
    rehash_approval(approval)
    definition = json.loads((FIXTURES / "composite_eligibility_66aec9d2_retained.json").read_text(encoding="utf-8"))[
        "finalization"
    ]["definition"]
    first, last = _month_window(proposal["observations"]["month"])
    observations = {item["portfolio_id"]: item for item in proposal["observations"]["portfolios"]}
    decisions = []
    for result in proposal["evaluation"]["portfolios"]:
        reasons = [
            reason
            for item in result["assessments"]
            for reason in (item["failure_reasons"] if result["status"] == "EXCLUDED" else item["unknown_reasons"])
        ]
        decisions.append(
            {
                "portfolio_id": result["portfolio_id"],
                "effective_from": first,
                "effective_to": last,
                "status": result["status"],
                "reason_code": None if result["status"] == "INCLUDED" else reasons[0],
                "discretionary": observations[result["portfolio_id"]]["discretionary"],
                "source_snapshot_id": proposal["evaluation"]["content_hash"],
                "approval_ref": approval["claims_digest"],
            }
        )
    membership = {
        "product_name": "CompositeMembership",
        "product_version": "v1",
        **{key: definition[key] for key in ("tenant_id", "composite_id", "definition_version")},
        "membership_revision": proposal["target_membership_revision"],
        "policy_version": proposal["policy_approval"]["proposal"]["eligibility_policy_version"],
        "source_cut_id": proposal["universe"]["source_cut_id"],
        "decisions": decisions,
        "decided_by": approval["approved_by"],
        "decided_at": approval["approved_at"],
        "correlation_id": proposal["correlation_id"],
        "supersedes_membership_revision": proposal["parent_membership_revision"],
        "affected_from": first,
        "affected_to": last,
    }
    membership["content_hash"] = legacy_composite_product_digest(membership)
    universe = deepcopy(proposal["universe"])
    universe.update(
        membership_revision=membership["membership_revision"],
        membership_content_hash=membership["content_hash"],
        attestation_version=proposal["evaluation_revision"],
        coverage_from=first,
        coverage_to=last,
        attested_by=approval["approved_by"],
        attested_at=approval["approved_at"],
        correlation_id=proposal["correlation_id"],
    )
    locator = {
        "owner_service": "lotus-manage",
        "product_name": approval["product_name"],
        "contract_version": "v1",
        "authority_scope": "POLICY_INPUT",
        "source_cut_id": universe["source_cut_id"],
        "source_watermark": proposal["evaluation_revision"],
        "content_hash": "sha256:" + "0" * 64,
    }
    universe["source_products"].append(locator)
    universe["source_products"].sort(
        key=lambda item: (item["owner_service"], item["product_name"], item["contract_version"], item["source_cut_id"])
    )
    universe["content_hash"] = legacy_composite_product_digest(universe)
    approval.update(
        membership_content_hash=membership["content_hash"], published_universe_content_hash=universe["content_hash"]
    )
    rehash(approval)
    locator["content_hash"] = approval["content_hash"]
    receipt = {
        "product_name": "CompositeMonthlyEligibilityPublicationReceipt",
        "product_version": "v1",
        "definition": definition,
        "approval": approval,
        "membership_binding": {
            "product_name": "CompositeMembership",
            "product_version": "v1",
            "revision": membership["membership_revision"],
            "digest": membership["content_hash"],
        },
        "universe_binding": {
            "product_name": "CompositeUniverseAttestation",
            "product_version": "v1",
            "revision": universe["attestation_version"],
            "digest": universe["content_hash"],
        },
        "source_cut_id": universe["source_cut_id"],
        "publication_sequence": 4,
        "completeness": "UNVERIFIED",
    }
    rehash(receipt)
    return {"definition": definition, "membership": membership, "attestation": universe}, receipt


def install_monthly_test_authorities(monkeypatch, packet, wire, *, source_available=True):
    """Admit only fixed synthetic fixture records, never caller-selected configuration."""
    from app.models.composite_monthly_eligibility_evidence import CompositeMonthlyEligibilityPublicationReceipt
    from app.ports import composite_external_evidence as ports
    from app.services.composite_materialization import authority_policy
    from tests.composite_eligibility_helpers import verification_expectation

    receipt = CompositeMonthlyEligibilityPublicationReceipt.model_validate(wire)
    definition = receipt.definition
    profile = definition.source_authority.payload
    proposal = receipt.approval.proposal
    source_receipt = proposal.source_assembly_evidence.verification
    provider = profile.providers[0]
    expected_bindings = {
        "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE": None,
        "RETURN_METHOD_CALENDAR": profile.return_method_binding.digest,
        "ELIGIBILITY_POLICY": proposal.policy_approval.content_hash,
        "COMPOSITE_MONTHLY_MEMBERSHIP_APPROVAL": receipt.approval.content_hash,
    }
    monthly_purposes = {"ELIGIBILITY_POLICY", "COMPOSITE_MONTHLY_MEMBERSHIP_APPROVAL"}
    calls = []

    class FixedApproval:
        def verify(self, request):
            calls.append(request)
            window = (
                _month_window(proposal.observations.month)
                if request.purpose in monthly_purposes
                else (profile.effective_from, profile.effective_to)
            )
            return (
                request.purpose in expected_bindings
                and (request.binding.digest if request.binding is not None else None)
                == expected_bindings[request.purpose]
                and request.authority_claims_digest
                == (
                    authority_digest(definition.authority_approval.claims.model_dump())
                    if request.purpose == "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE"
                    else None
                )
                and request.definition.model_dump() == packet["definition"]
                and request.eligibility_evidence_wire == wire
                and (request.tenant_id, request.composite_id, request.definition_version)
                == (definition.tenant_id, definition.composite_id, definition.definition_version)
                and (request.effective_from, request.effective_to) == window
                and request.expected_members == tuple(proposal.observations.expected_portfolio_ids)
            )

    class FixedSource:
        def verify(self, request):
            if source_available and request == source_receipt.request:
                return ports.VerifiedCompositeEvidence(source_receipt, verification_expectation(source_receipt))
            return ports.UnavailableCompositeEvidence()

    class FixedRegistration:
        def resolve(self, request):
            if (
                request.tenant_id == definition.tenant_id
                and request.provider_id == provider.provider_id
                and request.registry_revision == provider.registry_revision
                and request.registry_digest == provider.registry_digest
                and request.source_product in {item.source_product for item in profile.selections}
                and (request.effective_from, request.effective_to) == (profile.effective_from, profile.effective_to)
            ):
                return authority_policy.ProviderTrustResolution(
                    "SYNTHETIC_TEST_ONLY", "NON_CERTIFYING_MONTHLY_CONTROL", provider.registry_digest
                )
            return authority_policy.ProviderTrustResolution("UNAVAILABLE", "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")

    for name in ("authority_approval_verifier", "method_approval_verifier", "eligibility_approval_verifier"):
        monkeypatch.setattr(ports, name, FixedApproval)
    monkeypatch.setattr(ports, "composite_receipt_verifier", FixedSource)
    monkeypatch.setattr(authority_policy, "provider_trust_resolver", FixedRegistration)
    return calls
