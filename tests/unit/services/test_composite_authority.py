from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from app.models.composite_authority import ManageCompositeDefinitionV2, decode_authority_json
from app.models.composite_external_facts import CompositeExternalMemberFacts
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization.authority_policy import selection_for_window
from app.services.composite_materialization.source_contract import admit_pinned_source
from core.errors import APIUnprocessableEntityError
from tests.composite_authority_helpers import (
    command_for_packet,
    independent_ending_packet,
    install_test_authorities,
    observation_packet,
    rehash_definition,
    shared_packet,
)


def admit(packet):
    return admit_pinned_source(
        command=command_for_packet(packet),
        tenant_id="synthetic-tenant-a",
        **{key: packet[key] for key in ("definition", "membership", "attestation")},
    )


@pytest.mark.parametrize("version", ["original", "corrected"])
def test_frozen_external_definition_admission_requires_independent_ports(monkeypatch, version):
    packet = shared_packet(version)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(packet)
    assert refused.value.error_code == "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE"
    install_test_authorities(monkeypatch, packet)
    source = admit(packet)
    assert source.definition.model_dump(mode="json") == packet["definition"]
    assert source.definition.authority_approval.official_activation == "UNAVAILABLE"


@pytest.mark.parametrize(
    "factory,code",
    [
        ("authority_approval_verifier", "COMPOSITE_AUTHORITY_APPROVAL_UNAVAILABLE"),
        ("eligibility_approval_verifier", "COMPOSITE_ELIGIBILITY_APPROVAL_UNAVAILABLE"),
        ("method_approval_verifier", "COMPOSITE_METHOD_APPROVAL_UNAVAILABLE"),
    ],
)
def test_approvals_are_independent_not_inferred_from_registration(monkeypatch, factory, code):
    packet = shared_packet()
    install_test_authorities(monkeypatch, packet)
    monkeypatch.setattr(ports, factory, lambda: ports.UnavailableApprovalVerification())
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(packet)
    assert refused.value.error_code == code


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("registry", "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE"),
        ("gap", "COMPOSITE_ECONOMIC_AUTHORITY_GAP"),
        ("overlap", "COMPOSITE_ECONOMIC_AUTHORITY_OVERLAP"),
        ("kind", "COMPOSITE_AUTHORITY_FACT_KIND_MISMATCH"),
        ("mode", "COMPOSITE_AUTHORITY_MODE_MISMATCH"),
        ("claim", "COMPOSITE_APPROVAL_BINDING_MISMATCH"),
    ],
)
def test_rehashing_does_not_repair_economic_or_approval_contradictions(monkeypatch, mutation, code):
    packet = shared_packet()
    install_test_authorities(monkeypatch, packet)
    profile = packet["definition"]["source_authority"]["payload"]
    if mutation == "registry":
        profile["providers"][0]["registry_digest"] = "sha256:" + "f" * 64
    elif mutation == "gap":
        profile["selections"][0]["effective_from"] = "2026-09-02"
    elif mutation == "overlap":
        duplicate = deepcopy(profile["selections"][0])
        duplicate["selection_id"] = "duplicate_assets"
        profile["selections"].insert(1, duplicate)
    elif mutation == "kind":
        profile["providers"][0]["source_kind"] = "LOTUS_CORE"
        profile["providers"][0]["provider_id"] = "lotus-core"
        for identity in profile["member_identities"]:
            identity["identity_kind"] = "CORE_PORTFOLIO"
            identity["provider_id"] = "lotus-core"
        for selection in profile["selections"]:
            selection["provider_id"] = selection["economic_authority"] = "lotus-core"
    elif mutation == "mode":
        profile["mode"] = "INTERNAL"
    elif mutation == "claim":
        packet["definition"]["authority_approval"]["claims"]["method_evidence_digest"] = "sha256:" + "f" * 64
    rehash_definition(packet["definition"])
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(packet)
    assert refused.value.error_code == code


def test_adjacent_selection_is_valid_transition_not_overlap():
    packet = shared_packet()
    profile = packet["definition"]["source_authority"]["payload"]
    profile["selections"][0]["effective_to"] = "2026-09-15"
    adjacent = deepcopy(profile["selections"][0])
    adjacent.update(selection_id="beginning_assets_next", effective_from="2026-09-16", effective_to="2026-09-30")
    profile["selections"].insert(1, adjacent)
    rehash_definition(packet["definition"])
    definition = ManageCompositeDefinitionV2.model_validate(packet["definition"])
    with pytest.raises(APIUnprocessableEntityError) as refused:
        selection_for_window(
            definition,
            member_id="external-member-a",
            fact="BEGINNING_ASSETS",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
        )
    assert refused.value.error_code == "COMPOSITE_AUTHORITY_TRANSITION_REQUIRES_SPLIT_PERIOD"


@pytest.mark.parametrize("wire", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1.25}', '{"x":Infinity}'])
def test_strict_raw_authority_decode_refuses_ambiguous_numbers_and_duplicate_keys(wire):
    with pytest.raises(ValueError):
        decode_authority_json(wire)


def test_observations_retain_actual_cashflows_and_unavailable_ending_assets():
    _, raw = observation_packet(ending_assets=False)
    raw["rows"][0]["cash_flows"][0].update(business_date="2026-09-15", placement="END_OF_DAY")
    wire = CompositeExternalMemberFacts.model_validate(raw)
    assert wire.rows[0].ending_assets is None
    assert wire.rows[0].cash_flows[0].business_date == "2026-09-15"
    raw["rows"][0]["member_return"] = 0.1
    with pytest.raises(ValidationError):
        CompositeExternalMemberFacts.model_validate(raw)


def test_institutional_reference_is_decodable_but_not_qualified_by_synthetic_ports(monkeypatch):
    packet = shared_packet()
    envelope = packet["definition"]["authority_approval"]
    envelope["evidence_kind"] = "INSTITUTIONAL_ATTESTATION_REFERENCE"
    envelope["claims"]["schema_version"] = "composite-authority-approval-claims.v1"
    envelope["attestation"] = {
        "contract_version": "composite-authority-attestation.v1",
        "issuer_id": "unqualified-issuer",
        "attestation_id": "unqualified-artifact",
        "revision": "r1",
        "digest": "sha256:" + "e" * 64,
    }
    rehash_definition(packet["definition"])
    install_test_authorities(monkeypatch, packet)
    definition = ManageCompositeDefinitionV2.model_validate(packet["definition"])
    assert definition.authority_approval.evidence_kind == "INSTITUTIONAL_ATTESTATION_REFERENCE"
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(packet)
    assert refused.value.error_code == "COMPOSITE_INSTITUTIONAL_AUTHORITY_UNAVAILABLE"


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing_member", "COMPOSITE_ECONOMIC_AUTHORITY_GAP"),
        ("gap", "COMPOSITE_ECONOMIC_AUTHORITY_GAP"),
        ("overlap", "COMPOSITE_ECONOMIC_AUTHORITY_OVERLAP"),
        ("method", "COMPOSITE_AUTHORITY_METHOD_BINDING_UNEXPECTED"),
    ],
)
def test_explicit_ending_selection_requires_complete_unambiguous_nonreturn_authority(monkeypatch, mutation, code):
    packet, _, _ = independent_ending_packet()
    profile = packet["definition"]["source_authority"]["payload"]
    ending = next(s for s in profile["selections"] if s["fact"] == "ENDING_ASSETS")
    if mutation == "missing_member":
        ending["member_ids"].pop()
    elif mutation == "gap":
        ending["effective_from"] = "2026-09-02"
    elif mutation == "overlap":
        duplicate = deepcopy(ending)
        duplicate["selection_id"] = "ending_assets_overlap"
        profile["selections"].insert(2, duplicate)
    else:
        ending["method_profile_binding"] = deepcopy(profile["return_method_binding"])
    rehash_definition(packet["definition"])
    install_test_authorities(monkeypatch, packet)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(packet)
    assert refused.value.error_code == code


def test_independent_ending_provider_cut_and_rehashed_wrong_selected_cut(monkeypatch):
    from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource
    from app.models.composite_authority import authority_digest

    packet, wire, ending_wire = independent_ending_packet()
    install_test_authorities(monkeypatch, packet)
    source = admit(packet)

    class Observations:
        def read(self, *, tenant_id, selection):
            return ending_wire if selection.fact == "ENDING_ASSETS" else wire

    command = command_for_packet(packet)

    def read(definition):
        return AuthorityCompositeMemberResultSource(definition, observations=Observations()).read_member(
            command,
            None,
            member_id="external-member-a",
            tenant_id="synthetic-tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
        )

    outcome = read(source.definition)
    assert outcome.state == "READY"
    assert outcome.fact.ending_market_value == 160
    assert len(outcome.source_evidence.observation_wires) == 2
    assert outcome.source_evidence.observation_wires[1]["source_cut_id"] != command.source_cut_id
    from app.services.composite_materialization.provider_evidence_policy import require_provider_member_evidence
    from core.errors import APIConflictError

    require_provider_member_evidence(source, command, outcome)
    tampered = outcome.model_copy(deep=True)
    tampered.fact.ending_market_value = 161
    with pytest.raises(APIConflictError):
        require_provider_member_evidence(source, command, tampered)
    tampered = outcome.model_copy(deep=True)
    tampered.source_evidence.observation_wires[1]["rows"][0]["ending_assets"] = "161"
    with pytest.raises(APIConflictError):
        require_provider_member_evidence(source, command, tampered)
    ending_wire["source_cut_id"] = "wrong-provider-cut"
    ending = next(
        s for s in packet["definition"]["source_authority"]["payload"]["selections"] if s["fact"] == "ENDING_ASSETS"
    )
    ending["source_digest"] = authority_digest(ending_wire)
    rehash_definition(packet["definition"])
    assert read(ManageCompositeDefinitionV2.model_validate(packet["definition"])).state == "BLOCKED"


def test_raw_definition_decoder_cannot_downgrade_duplicate_version():
    import httpx

    from app.adapters.composite_membership_source import composite_response_payload

    response = httpx.Response(
        200, text='{"product_name":"CompositeDefinition","product_version":"v2","product_version":"v1"}'
    )
    with pytest.raises(APIUnprocessableEntityError) as refused:
        composite_response_payload(response)
    assert refused.value.error_code == "COMPOSITE_SOURCE_SCHEMA_INVALID"


def test_pure_asset_reporting_engine_refuses_unselected_ending_assets(monkeypatch):
    from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource
    from engine.composites import calculate_asset_weighted_composite_twr

    packet, wire = observation_packet(ending_assets=False)
    install_test_authorities(monkeypatch, packet)
    source = admit(packet)
    command = command_for_packet(packet)

    class Observations:
        def read(self, *, tenant_id, selection):
            return wire

    outcome = AuthorityCompositeMemberResultSource(source.definition, observations=Observations()).read_member(
        command,
        None,
        member_id="external-member-a",
        tenant_id="synthetic-tenant-a",
        membership_snapshot_id=command.membership_content_hash,
        request_headers={},
    )
    assert outcome.state == "READY"
    from app.models.composites import CompositeMemberReturnFact

    payload = outcome.fact.model_dump(mode="json")
    contradictory = deepcopy(payload)
    contradictory["source_authority_identity"]["return_source_kind"] = "LOTUS_PERFORMANCE"
    with pytest.raises(ValidationError, match="Selected authority mode conflicts"):
        CompositeMemberReturnFact.model_validate(contradictory)
    contradictory = deepcopy(payload)
    contradictory["calculation_id"] = "invented-calculation"
    with pytest.raises(ValidationError, match="cannot manufacture"):
        CompositeMemberReturnFact.model_validate(contradictory)
    with pytest.raises(ValueError, match="^COMPOSITE_ENDING_ASSETS_UNAVAILABLE$"):
        calculate_asset_weighted_composite_twr(composite_id=command.composite_id, member_return_facts=[outcome.fact])
