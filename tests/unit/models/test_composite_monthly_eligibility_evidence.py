"""Exact historical month wires and rehashed semantic attacks on new receipts."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.composite_authority import legacy_composite_product_digest
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.models.composite_monthly_eligibility_evidence import (
    CompositeMonthlyEligibilityPublicationReceipt,
    MonthlyEvaluationApproval,
    MonthlyEvaluationProposal,
    monthly_publication_binding,
)
from tests.composite_monthly_eligibility_helpers import (
    monthly_approvals,
    rehash,
    rehash_approval,
    synthetic_monthly_packet,
)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_genuine_producer_history_preserves_every_value_and_nested_hash(index):
    wire = monthly_approvals()[index]
    decoded = MonthlyEvaluationApproval.model_validate(wire)
    assert decoded.model_dump() == wire
    assert "publication_evidence_version" not in decoded.proposal.model_dump()
    assert decoded.proposal.source_assembly_evidence.verification.request.purpose == "COMPOSITE_MONTHLY_SOURCE_CUT"


def test_marked_new_receipt_dispatch_and_complete_wire_roundtrip():
    _, wire = synthetic_monthly_packet()
    decoded = decode_eligibility_receipt(json.dumps(wire))
    assert isinstance(decoded, CompositeMonthlyEligibilityPublicationReceipt)
    assert decoded.model_dump() == wire
    assert decoded.completeness == "UNVERIFIED"


@pytest.mark.parametrize("field", ["source_assembly_evidence", "publication_evidence_version"])
def test_explicit_null_is_not_omitted_from_legacy_hashed_payload(field):
    proposal = monthly_approvals()[0]["proposal"]
    proposal[field] = None
    rehash(proposal)
    with pytest.raises(ValidationError, match="COMPOSITE_MONTHLY_NONCANONICAL_NULL"):
        MonthlyEvaluationProposal.model_validate(proposal)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("future_policy", "POLICY_NOT_PROSPECTIVE"),
        ("self_policy", "SELF_APPROVAL_FORBIDDEN"),
        ("self_checker", "SELF_APPROVAL_FORBIDDEN"),
        ("early_checker", "CLOCK_MISMATCH"),
        ("parent", "PARENT_BINDING_MISMATCH"),
        ("observations_digest", "SOURCE_BINDING_MISMATCH"),
        ("status", "STATUS_MISMATCH"),
        ("scope", "SCOPE_MISMATCH"),
    ],
)
def test_rehashed_semantic_cross_links_refuse(fault, code):
    approval = deepcopy(monthly_approvals()[2])
    proposal = approval["proposal"]
    policy = proposal["policy_approval"]
    if fault == "future_policy":
        policy["approved_at"] = "2026-09-01T00:00:00.000000Z"
        rehash(policy)
    elif fault == "self_policy":
        policy["approved_by"] = policy["proposal"]["proposed_by"]
        rehash(policy)
    elif fault == "self_checker":
        approval["approved_by"] = proposal["proposed_by"]
    elif fault == "early_checker":
        approval["approved_at"] = "2026-01-01T00:00:00.000000Z"
    elif fault == "parent":
        proposal["parent_membership_content_hash"] = "sha256:" + "c" * 64
    elif fault == "observations_digest":
        product = next(
            item for item in proposal["universe"]["source_products"] if item["authority_scope"] == "POLICY_INPUT"
        )
        product["content_hash"] = "sha256:" + "d" * 64
        assert legacy_composite_product_digest(proposal["universe"]) == proposal["universe"]["content_hash"]
    elif fault == "status":
        result = proposal["evaluation"]["portfolios"][0]
        result["status"] = "EXCLUDED"
        proposal["evaluation"].update(included_count=0, excluded_count=1)
        rehash(proposal["evaluation"])
    else:
        proposal["universe"]["tenant_id"] = "another-tenant"
        proposal["universe"]["content_hash"] = legacy_composite_product_digest(proposal["universe"])
    rehash_approval(approval)
    with pytest.raises(ValidationError, match=code):
        MonthlyEvaluationApproval.model_validate(approval)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("unmarked", "PUBLICATION_VERSION_UNAVAILABLE"),
        ("wrong_marker", "literal_error"),
        ("binding", "MEMBERSHIP_BINDING_MISMATCH"),
        ("sequence_bool", "int_type"),
        ("sequence_zero", "greater_than_equal"),
        ("cut", "SOURCE_CUT_MISMATCH"),
    ],
)
def test_rehashed_publication_receipt_is_strict(fault, code):
    _, wire = synthetic_monthly_packet()
    if fault == "unmarked":
        wire["approval"]["proposal"].pop("publication_evidence_version")
        rehash_approval(wire["approval"])
    elif fault == "wrong_marker":
        wire["approval"]["proposal"]["publication_evidence_version"] = "v2"
        rehash_approval(wire["approval"])
    elif fault == "binding":
        wire["membership_binding"]["revision"] = "wrong-month"
    elif fault == "cut":
        wire["source_cut_id"] = "wrong-cut"
    else:
        wire["publication_sequence"] = fault == "sequence_bool"
        if fault == "sequence_zero":
            wire["publication_sequence"] = 0
    rehash(wire)
    with pytest.raises(ValidationError, match=code):
        CompositeMonthlyEligibilityPublicationReceipt.model_validate(wire)


@pytest.mark.parametrize("fault", ["duplicate", "owner", "scope", "cut", "version"])
def test_current_locator_cannot_be_malformed_or_duplicated(fault):
    packet, _ = synthetic_monthly_packet()
    products = packet["attestation"]["source_products"]
    locator = next(item for item in products if item["product_name"] == "CompositeMonthlyEvaluationApproval")
    if fault == "duplicate":
        products.append(deepcopy(locator))
    else:
        key = {
            "owner": "owner_service",
            "scope": "authority_scope",
            "cut": "source_cut_id",
            "version": "contract_version",
        }[fault]
        locator[key] = {"scope": "REFERENCE_INPUT", "version": "v2"}.get(fault, "wrong")
    with pytest.raises(ValueError):
        monthly_publication_binding(products, packet["attestation"]["source_cut_id"])


def test_original_definition_authority_date_is_not_reused_as_future_month_checker_date():
    _, wire = synthetic_monthly_packet()
    wire["approval"]["approved_at"] = "2026-10-20T00:00:00.000000Z"
    rehash_approval(wire["approval"])
    rehash(wire)
    result = CompositeMonthlyEligibilityPublicationReceipt.model_validate(wire)
    assert result.definition.authority_approval.claims.approved_at < result.approval.approved_at
