"""Controlled monthly HTTP joins; independent trust remains unavailable by default."""

import json
from copy import deepcopy

import httpx
import pytest

from app.adapters.manage_composite_eligibility_evidence import ManageCompositeEligibilityEvidence
from app.core.config import get_settings
from app.models.composite_authority import legacy_composite_product_digest
from app.models.composite_monthly_eligibility_evidence import CompositeMonthlyEligibilityPublicationReceipt
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization import authority_policy
from app.services.composite_materialization.source_contract import published_eligibility_from_wire
from core.errors import APIError
from tests.composite_authority_helpers import command_for_packet
from tests.composite_eligibility_helpers import verification_expectation
from tests.composite_monthly_eligibility_helpers import rehash, synthetic_monthly_packet


def join(packet, wire):
    return published_eligibility_from_wire(
        command=command_for_packet(packet),
        tenant_id="synthetic-tenant",
        **packet,
        receipt=CompositeMonthlyEligibilityPublicationReceipt.model_validate(wire),
    )


def test_current_marked_month_joins_actual_separate_product_wires():
    packet, wire = synthetic_monthly_packet()
    result = join(packet, wire)
    assert result.receipt.model_dump() == wire
    assert result.membership_binding == result.receipt.membership_binding
    assert result.universe_binding == result.receipt.universe_binding
    assert (
        result.receipt.definition.source_authority.payload.eligibility_evaluation_binding.product_name
        == "CompositeSubjectEvaluationApproval"
    )


def test_prior_membership_history_is_retained_outside_current_month():
    packet, wire = synthetic_monthly_packet()
    history = deepcopy(packet["membership"]["decisions"][0])
    history.update(
        effective_from="2026-08-01",
        effective_to="2026-08-31",
        source_snapshot_id="old-evaluation",
        approval_ref="old-claims",
    )
    packet["membership"]["decisions"].insert(0, history)
    bind_membership(packet, wire)
    result = join(packet, wire)
    assert result.receipt.membership_binding.digest == packet["membership"]["content_hash"]
    assert history["approval_ref"] == "old-claims"


def bind_membership(packet, wire):
    packet["membership"]["content_hash"] = legacy_composite_product_digest(packet["membership"])
    packet["attestation"]["membership_content_hash"] = packet["membership"]["content_hash"]
    packet["attestation"]["content_hash"] = legacy_composite_product_digest(packet["attestation"])
    wire["approval"].update(
        membership_content_hash=packet["membership"]["content_hash"],
        published_universe_content_hash=packet["attestation"]["content_hash"],
    )
    rehash(wire["approval"])
    locator = next(
        item
        for item in packet["attestation"]["source_products"]
        if item["product_name"] == "CompositeMonthlyEvaluationApproval"
    )
    locator["content_hash"] = wire["approval"]["content_hash"]
    wire["membership_binding"]["digest"] = packet["membership"]["content_hash"]
    wire["universe_binding"]["digest"] = packet["attestation"]["content_hash"]
    rehash(wire)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "EXCLUDED"),
        ("source_snapshot_id", "other-evaluation"),
        ("approval_ref", "other-checker"),
        ("reason_code", "OTHER"),
        ("discretionary", False),
        ("effective_from", "2026-08-31"),
    ],
)
def test_fully_rehashed_current_membership_semantic_tamper_refuses(field, value):
    packet, wire = synthetic_monthly_packet()
    packet["membership"]["decisions"][0][field] = value
    if field == "status":
        packet["membership"]["decisions"][0]["reason_code"] = "OTHER"
    bind_membership(packet, wire)
    with pytest.raises(APIError) as refused:
        join(packet, wire)
    assert refused.value.error_code == "COMPOSITE_ELIGIBILITY_PUBLISHED_DECISION_MISMATCH"


def test_nested_current_locator_digest_tamper_is_detected_despite_unchanged_universe_hash():
    packet, wire = synthetic_monthly_packet()
    locator = next(
        item
        for item in packet["attestation"]["source_products"]
        if item["product_name"] == "CompositeMonthlyEvaluationApproval"
    )
    locator["content_hash"] = "sha256:" + "e" * 64
    assert legacy_composite_product_digest(packet["attestation"]) == packet["attestation"]["content_hash"]
    with pytest.raises(APIError) as refused:
        join(packet, wire)
    assert refused.value.error_code == "COMPOSITE_ELIGIBILITY_RESOLUTION_BINDING_MISMATCH"


def test_unmarked_missing_current_locator_cannot_fall_back_to_first_month_approval():
    packet, wire = synthetic_monthly_packet()
    packet["attestation"]["source_products"] = [
        item
        for item in packet["attestation"]["source_products"]
        if item["product_name"] != "CompositeMonthlyEvaluationApproval"
    ]
    packet["attestation"]["content_hash"] = legacy_composite_product_digest(packet["attestation"])
    wire["approval"]["published_universe_content_hash"] = packet["attestation"]["content_hash"]
    wire["universe_binding"]["digest"] = packet["attestation"]["content_hash"]
    rehash(wire["approval"])
    rehash(wire)
    with pytest.raises(APIError) as refused:
        join(packet, wire)
    assert refused.value.error_code == "COMPOSITE_ELIGIBILITY_RESOLUTION_BINDING_MISMATCH"


@pytest.mark.asyncio
async def test_registered_adapter_posts_exact_current_month_locator_and_decodes_monthly_receipt(monkeypatch):
    packet, wire = synthetic_monthly_packet()
    calls = []

    async def post(**kwargs):
        calls.append(kwargs)
        response = httpx.Response(200, text=json.dumps(wire))
        return 200, kwargs["response_decoder"](response)

    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "http://manage/api/v1/")
    monkeypatch.setattr("app.adapters.manage_composite_eligibility_evidence.post_with_retry", post)
    result = await ManageCompositeEligibilityEvidence().read_published(
        command_for_packet(packet),
        tenant_id="synthetic-tenant",
        actor_id="reader",
        role="DPM_COMPOSITE_CONSUMER",
        **packet,
    )
    assert result.receipt.model_dump() == wire
    assert calls[0]["json_body"] == {
        "product_name": "CompositeMonthlyEvaluationApproval",
        "product_version": "v1",
        "revision": wire["approval"]["proposal"]["evaluation_revision"],
        "digest": wire["approval"]["content_hash"],
    }
    assert calls[0]["url"].endswith("/eligibility-evidence/resolve")


def test_monthly_schema_and_unsigned_claims_do_not_supply_independent_source_verification():
    packet, wire = synthetic_monthly_packet()
    result = join(packet, wire)
    with pytest.raises(APIError) as refused:
        authority_policy._verify_monthly_approvals(
            result.receipt.definition,
            command_for_packet(packet),
            "registry-digest",
            ["synthetic-member"],
            result.receipt,
        )
    assert refused.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE"


def install_fixed_source_verifier(monkeypatch, wire):
    receipt = CompositeMonthlyEligibilityPublicationReceipt.model_validate(wire)
    source_receipt = receipt.approval.proposal.source_assembly_evidence.verification

    class FixedSourceVerifier:
        def verify(self, request):
            if request != source_receipt.request:
                return ports.UnavailableCompositeEvidence()
            return ports.VerifiedCompositeEvidence(source_receipt, verification_expectation(source_receipt))

    monkeypatch.setattr(ports, "composite_receipt_verifier", FixedSourceVerifier)


def test_independent_whole_source_cut_does_not_grant_financial_authority(monkeypatch):
    packet, wire = synthetic_monthly_packet()
    result = join(packet, wire)
    install_fixed_source_verifier(monkeypatch, wire)
    with pytest.raises(APIError) as refused:
        authority_policy._verify_monthly_approvals(
            result.receipt.definition,
            command_for_packet(packet),
            "registry-digest",
            ["synthetic-member"],
            result.receipt,
        )
    assert refused.value.error_code == "COMPOSITE_AUTHORITY_APPROVAL_UNAVAILABLE"


def test_every_months_policy_checker_and_original_authority_method_receive_distinct_full_requests(monkeypatch):
    packet, wire = synthetic_monthly_packet()
    result = join(packet, wire)
    install_fixed_source_verifier(monkeypatch, wire)
    calls = []
    command = command_for_packet(packet)
    expected = {
        "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE": None,
        "RETURN_METHOD_CALENDAR": "SyntheticReturnMethodCalendar",
        "ELIGIBILITY_POLICY": "CompositeMonthlyPolicyApproval",
        "COMPOSITE_MONTHLY_MEMBERSHIP_APPROVAL": "CompositeMonthlyEvaluationApproval",
    }

    class ControlledApprovalVerifier:
        def verify(self, request):
            assert (request.binding.product_name if request.binding is not None else None) == expected[request.purpose]
            assert request.eligibility_evidence_wire == wire
            assert request.definition.model_dump() == packet["definition"]
            assert request.command == command
            assert request.expected_members == ("synthetic-member",)
            assert request.universe_digest == "registry-digest"
            calls.append(request)
            return True

    for factory in ("authority_approval_verifier", "method_approval_verifier", "eligibility_approval_verifier"):
        monkeypatch.setattr(ports, factory, ControlledApprovalVerifier)
    authority_policy._verify_monthly_approvals(
        result.receipt.definition,
        command,
        "registry-digest",
        ["synthetic-member"],
        result.receipt,
    )
    assert [request.purpose for request in calls] == list(expected)
    assert all((request.effective_from, request.effective_to) == ("2026-09-01", "2026-09-30") for request in calls)
    assert calls[2].binding.digest == wire["approval"]["proposal"]["policy_approval"]["content_hash"]
    assert calls[3].binding.digest == wire["approval"]["content_hash"]
