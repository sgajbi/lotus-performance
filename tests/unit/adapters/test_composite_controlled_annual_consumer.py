"""Configured source reads join original producer products and independent trust."""

import json
from dataclasses import replace

import pytest

from app.adapters.composite_membership_source import ManageCompositeMembershipSource
from app.core.config import get_settings
from app.models.composite_controlled_annual_authority import ControlledAnnualDefinitionV4
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.ports import composite_controlled_annual_evidence as year_ports
from app.services.composite_materialization.source_contract import (
    PinnedCompositeSource,
    require_pinned_source_scope,
    source_digest,
)
from core.errors import APIError
from tests.composite_controlled_annual_helpers import (
    command,
    competing_receipt,
    graph,
    hash_envelope,
    install_independent_test_trust,
    source_packet,
)
from tests.composite_controlled_scenario_helpers import install_http_transport


async def read_source(packet=None):
    packet = packet or source_packet()
    return await ManageCompositeMembershipSource().read_pinned(
        command(packet), tenant_id=packet["definition"]["tenant_id"], actor_id="reader", role="DPM_COMPOSITE_CONSUMER"
    )


@pytest.mark.asyncio
async def test_actual_adapter_joins_all_four_producer_products_and_retains_exact_source_off_custody(monkeypatch):
    packet = source_packet()
    trust_calls = install_independent_test_trust(monkeypatch)
    calls = install_http_transport(monkeypatch, packet=packet, receipt=graph())
    source = await read_source(packet)
    assert isinstance(source.definition, ControlledAnnualDefinitionV4)
    assert source.wire_evidence.model_dump() == packet
    assert source.published_eligibility.receipt.model_dump(mode="json") == graph()
    assert [request.method for request in calls] == ["GET", "GET", "GET", "POST"]
    assert (
        json.loads(calls[-1].content)
        == packet["definition"]["source_authority"]["payload"]["eligibility_evaluation_binding"]
    )
    assert any(request.purpose == "COMPOSITE_CONTROLLED_YEAR_AUTHORITY" for request in trust_calls)
    retained = PinnedCompositeSource.model_validate_json(source.model_dump_json())
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    require_pinned_source_scope(retained, command=command(), tenant_id=packet["definition"]["tenant_id"])
    assert retained == source and len(calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denied",
    [
        "year",
        "ELIGIBILITY_POLICY",
        "ELIGIBILITY_POLICY_EVALUATION",
        "RETURN_METHOD_CALENDAR",
        "PROVIDER_REGISTRATION",
        "PROVIDER_TRUST",
    ],
)
async def test_missing_independent_year_policy_method_or_provider_trust_refuses(monkeypatch, denied):
    install_independent_test_trust(monkeypatch, denied_year=denied == "year", denied_purpose=denied)
    install_http_transport(monkeypatch, packet=source_packet(), receipt=graph())
    with pytest.raises(APIError) as error:
        await read_source()
    expected = (
        "COMPOSITE_YEAR_VERIFICATION_UNAVAILABLE"
        if denied == "year"
        else "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE"
        if denied == "PROVIDER_TRUST"
        else "COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE"
    )
    assert error.value.error_code == expected


@pytest.mark.asyncio
async def test_valid_same_scope_competing_basis_cannot_replace_the_separately_pinned_definition(monkeypatch):
    other = competing_receipt()
    decode_eligibility_receipt(json.dumps(other))
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=source_packet(), receipt=other)
    with pytest.raises(APIError) as error:
        await read_source()
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_FINAL_DEFINITION_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["definition", "membership", "attestation"])
async def test_changed_raw_product_never_reuses_original_hash(monkeypatch, product):
    packet = source_packet()
    packet[product]["content_hash"] = "sha256:" + "0" * 64
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=packet, receipt=graph())
    with pytest.raises(APIError) as error:
        await read_source(packet)
    assert error.value.error_code == (
        "COMPOSITE_SOURCE_SCHEMA_INVALID" if product == "definition" else "COMPOSITE_SOURCE_HASH_MISMATCH"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,value", [("tenant_id", "foreign"), ("status", "PENDING_REVIEW"), ("approval_ref", "foreign-claims")]
)
async def test_rehashed_membership_cannot_change_scope_or_evaluated_publication(monkeypatch, mutation, value):
    packet = source_packet()
    if mutation == "tenant_id":
        packet["membership"][mutation] = value
    else:
        packet["membership"]["decisions"][0][mutation] = value
        if mutation == "status":
            packet["membership"]["decisions"][0]["reason_code"] = "COMPOSITE_CONTROLLED_INPUT_PENDING_EVALUATION"
    packet["membership"]["content_hash"] = source_digest(packet["membership"])
    packet["attestation"]["membership_content_hash"] = packet["membership"]["content_hash"]
    packet["attestation"]["content_hash"] = source_digest(packet["attestation"])
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=packet, receipt=graph())
    with pytest.raises(APIError) as error:
        await read_source(packet)
    assert error.value.error_code in {
        "COMPOSITE_SOURCE_SCOPE_MISMATCH",
        "COMPOSITE_ELIGIBILITY_PUBLICATION_BINDING_MISMATCH",
    }


@pytest.mark.asyncio
async def test_fully_rebound_pending_membership_is_not_an_evaluated_included_publication(monkeypatch):
    packet, receipt = source_packet(), graph()
    packet["membership"]["decisions"][0].update(
        status="PENDING_REVIEW", reason_code="COMPOSITE_CONTROLLED_INPUT_PENDING_EVALUATION"
    )
    packet["membership"]["content_hash"] = source_digest(packet["membership"])
    packet["attestation"]["membership_content_hash"] = packet["membership"]["content_hash"]
    packet["attestation"]["content_hash"] = source_digest(packet["attestation"])
    for key, value in (
        ("membership_content_hash", packet["membership"]["content_hash"]),
        ("universe_content_hash", packet["attestation"]["content_hash"]),
    ):
        receipt[key] = value
        receipt["finalization"]["evaluation_approval"][key] = value
    hash_envelope(receipt["finalization"]["evaluation_approval"])
    receipt = competing_receipt(receipt)
    decode_eligibility_receipt(json.dumps(receipt))
    packet["definition"] = receipt["finalization"]["definition"]
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=packet, receipt=receipt)
    with pytest.raises(APIError) as error:
        await read_source(packet)
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_PUBLISHED_DECISION_MISMATCH"


@pytest.mark.asyncio
async def test_default_year_verifier_does_not_admit_a_signed_source_graph(monkeypatch):
    install_independent_test_trust(monkeypatch)
    monkeypatch.setattr(year_ports, "controlled_year_verifier", year_ports.UnavailableControlledYearVerification)
    install_http_transport(monkeypatch, packet=source_packet(), receipt=graph())
    with pytest.raises(APIError) as error:
        await read_source()
    assert error.value.error_code == "COMPOSITE_YEAR_VERIFICATION_UNAVAILABLE"


def test_independent_trust_record_cannot_substitute_verifier_or_source_key(monkeypatch):
    install_independent_test_trust(monkeypatch)
    proof = decode_eligibility_receipt(json.dumps(graph())).finalization.year_authority_verification
    good = year_ports.controlled_year_verifier().verify(proof.request)
    assert year_ports.admit_controlled_year_verification(proof, good) == proof
    for field in ("signer_key_digest", "verifier_key_digest", "configuration_digest"):
        invalid = replace(good, expectation=replace(good.expectation, **{field: "sha256:" + "0" * 64}))
        with pytest.raises(ValueError, match="TRUST_MISMATCH"):
            year_ports.admit_controlled_year_verification(proof, invalid)
    invalid = replace(good, expectation=replace(good.expectation, source_public_key_base64="AAAA"))
    with pytest.raises(ValueError, match="SOURCE_SIGNATURE_INVALID"):
        year_ports.admit_controlled_year_verification(proof, invalid)
    for field, instant in (
        ("source_key_valid_to", proof.basis_mapping.basis.actual_issued_at),
        ("verifier_key_valid_to", proof.admitted_at),
    ):
        expired = replace(good, expectation=replace(good.expectation, **{field: instant}))
        with pytest.raises(ValueError, match="KEY_WINDOW_MISMATCH"):
            year_ports.admit_controlled_year_verification(proof, expired)


@pytest.mark.asyncio
async def test_unknown_definition_version_cannot_enter_the_legacy_recursive_hash_path(monkeypatch):
    packet = source_packet()
    packet["definition"]["product_version"] = "v42"
    packet["definition"]["content_hash"] = source_digest(packet["definition"])
    calls = install_http_transport(monkeypatch, packet=packet, receipt=graph())
    with pytest.raises(APIError) as error:
        await read_source(packet)
    assert error.value.error_code == "COMPOSITE_SOURCE_SCHEMA_INVALID"
    assert [request.method for request in calls] == ["GET", "GET", "GET"]
