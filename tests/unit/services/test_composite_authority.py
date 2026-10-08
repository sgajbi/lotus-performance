from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from app.models.composite_authority import ManageCompositeDefinitionV2, decode_authority_json
from app.models.composite_external_facts import CompositeExternalMemberFacts
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization.authority_policy import admit_authority_profile, selection_for_window
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


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"eligibility_policy_version": "other-policy"}, "COMPOSITE_SOURCE_POLICY_MISMATCH"),
        ({"inception_date": "2026-09-02"}, "COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH"),
        ({"termination_date": "2026-09-29"}, "COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH"),
    ],
)
def test_pinned_v2_source_refuses_rehashed_definition_outside_command_scope(monkeypatch, changes, code):
    packet = shared_packet()
    install_test_authorities(monkeypatch, packet)
    assert admit(packet).definition.composite_id == packet["definition"]["composite_id"]
    packet["definition"].update(changes)
    rehash_definition(packet["definition"])
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(packet)
    assert refused.value.error_code == code


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("profile_digest", "COMPOSITE_PROFILE_DIGEST_MISMATCH"),
        ("definition_digest", "COMPOSITE_DEFINITION_PAYLOAD_DIGEST_MISMATCH"),
        ("final_digest", "COMPOSITE_SOURCE_HASH_MISMATCH"),
        ("self_approval", "COMPOSITE_AUTHORITY_SELF_APPROVAL_FORBIDDEN"),
        ("definition_window", "COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH"),
        ("tenant", "COMPOSITE_SOURCE_SCOPE_MISMATCH"),
        ("command_window", "COMPOSITE_PROFILE_WINDOW_MISMATCH"),
        ("universe", "COMPOSITE_AUTHORITY_UNIVERSE_MISMATCH"),
        ("internal_owner", "COMPOSITE_AUTHORITY_INTERNAL_OWNER_MISMATCH"),
        ("member_provider", "COMPOSITE_AUTHORITY_PROVIDER_MISMATCH"),
        ("member_kind", "COMPOSITE_AUTHORITY_MEMBER_KIND_MISMATCH"),
        ("selection_provider", "COMPOSITE_AUTHORITY_PROVIDER_MISMATCH"),
        ("economic_owner", "COMPOSITE_ECONOMIC_AUTHORITY_MISMATCH"),
        ("selection_window", "COMPOSITE_PROFILE_WINDOW_MISMATCH"),
        ("method", "COMPOSITE_METHOD_BINDING_MISMATCH"),
    ],
)
def test_projected_authority_admission_refuses_corruption_before_trust(monkeypatch, mutation, code):
    """Typed projection alone cannot authorize a retained or rehashed contradictory definition."""
    packet = shared_packet()
    install_test_authorities(monkeypatch, packet)
    source = admit(packet)
    command = command_for_packet(packet)
    wire = deepcopy(packet["definition"])
    profile = wire["source_authority"]["payload"]
    members = list(source.attestation.expected_portfolio_ids)
    tenant = source.definition.tenant_id
    if mutation == "self_approval":
        wire["authority_approval"]["claims"]["approving_identity"] = wire["created_by"]
    elif mutation == "definition_window":
        wire["inception_date"] = "2026-09-02"
    elif mutation == "tenant":
        tenant = "foreign-tenant"
    elif mutation == "command_window":
        command = command_for_packet(packet, period_end="2026-10-01")
    elif mutation == "universe":
        members.pop()
    elif mutation == "internal_owner":
        profile["providers"][0]["source_kind"] = "LOTUS_CORE"
    elif mutation == "member_provider":
        profile["member_identities"][0]["provider_id"] = "missing-provider"
    elif mutation == "member_kind":
        profile["member_identities"][0]["identity_kind"] = "CORE_PORTFOLIO"
    elif mutation == "selection_provider":
        profile["selections"][0]["provider_id"] = "missing-provider"
    elif mutation == "economic_owner":
        profile["selections"][0]["economic_authority"] = "other-owner"
    elif mutation == "selection_window":
        profile["selections"][0]["effective_to"] = "2026-10-01"
    elif mutation == "method":
        selected = next(item for item in profile["selections"] if item["fact"] == "MEMBER_RETURN")
        selected["method_profile_binding"]["revision"] = "other-method"
    rehash_definition(wire)
    if mutation == "profile_digest":
        wire["source_authority"]["profile_digest"] = "sha256:" + "f" * 64
    elif mutation == "definition_digest":
        wire["definition_payload_digest"] = "sha256:" + "f" * 64
    elif mutation == "final_digest":
        wire["content_hash"] = "sha256:" + "f" * 64
    definition = ManageCompositeDefinitionV2.model_validate(wire)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit_authority_profile(
            definition,
            command=command,
            tenant_id=tenant,
            expected_members=members,
            universe_digest=source.attestation.content_hash,
        )
    assert refused.value.error_code == code


@pytest.mark.parametrize(
    "mutation",
    [
        "negative_assets",
        "unpaired_ending",
        "inverted_period",
        "duplicate_members",
        "beginning_date",
        "flow_outside",
        "period_end_placement",
    ],
)
def test_provider_observation_wire_refuses_ambiguous_economic_scope(mutation):
    _, wire = observation_packet(ending_assets=True)
    row = wire["rows"][0]
    if mutation == "negative_assets":
        row["beginning_assets"] = "-1"
    elif mutation == "unpaired_ending":
        row["ending_assets_date"] = None
    elif mutation == "inverted_period":
        wire["period_end"] = "2026-08-31"
    elif mutation == "duplicate_members":
        wire["rows"].append(deepcopy(row))
    elif mutation == "beginning_date":
        row["beginning_assets_date"] = "2026-09-02"
    elif mutation == "flow_outside":
        row["cash_flows"][0]["business_date"] = "2026-10-01"
    else:
        row["cash_flows"][0].update(business_date="2026-09-15", placement="PERIOD_END_AFTER_RETURN")
    with pytest.raises(ValidationError):
        CompositeExternalMemberFacts.model_validate(wire)


@pytest.mark.parametrize(
    "mutation",
    ["selection_interval", "selection_members", "profile_interval", "duplicate_provider", "definition_interval"],
)
def test_authority_wire_refuses_noncanonical_identity_and_date_windows(mutation):
    wire = shared_packet()["definition"]
    profile = wire["source_authority"]["payload"]
    if mutation == "selection_interval":
        profile["selections"][0]["effective_to"] = "2026-08-31"
    elif mutation == "selection_members":
        profile["selections"][0]["member_ids"].append(profile["selections"][0]["member_ids"][0])
    elif mutation == "profile_interval":
        profile["effective_to"] = "2026-08-31"
    elif mutation == "duplicate_provider":
        profile["providers"].append(deepcopy(profile["providers"][0]))
    else:
        wire["termination_date"] = "1900-01-01"
    with pytest.raises(ValidationError):
        ManageCompositeDefinitionV2.model_validate(wire)


@pytest.mark.parametrize("retryable", [False, True])
def test_provider_transport_refusal_preserves_retry_disposition(monkeypatch, retryable):
    from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource
    from core.errors import APIError

    packet, _ = observation_packet()
    install_test_authorities(monkeypatch, packet)
    source = admit(packet)

    class Unavailable:
        def read(self, **kwargs):
            raise APIError(
                status_code=503,
                detail="Unavailable controlled provider",
                error_code="SOURCE_UNAVAILABLE",
                retryable=retryable,
            )

    command = command_for_packet(packet)
    outcome = AuthorityCompositeMemberResultSource(source.definition, observations=Unavailable()).read_member(
        command,
        None,
        tenant_id=source.definition.tenant_id,
        member_id="external-member-a",
        membership_snapshot_id=command.membership_content_hash,
        request_headers={},
    )
    assert outcome.state == ("WAITING" if retryable else "BLOCKED")
    assert outcome.retryable is retryable
    assert outcome.fact is None
    assert outcome.reason_code == (
        "COMPOSITE_PROVIDER_OBSERVATION_PENDING" if retryable else "COMPOSITE_PROVIDER_OBSERVATION_REFUSED"
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


@pytest.mark.parametrize("wire", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1.25}', '{"x":Infinity}', "[]"])
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


@pytest.mark.parametrize("version,numerator,denominator", [("original", 1, 60), ("corrected", 49, 3050)])
def test_frozen_monthly_wire_retains_exact_raw_economics_and_requires_approved_method(
    monkeypatch, version, numerator, denominator
):
    from decimal import Decimal

    from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource
    from app.services.composite_materialization.provider_evidence_policy import require_provider_member_evidence
    from engine.composites import _build_ready_member_contributions

    packet = shared_packet(version)
    install_test_authorities(monkeypatch, packet)
    source, command = admit(packet), command_for_packet(packet)
    raw = packet["supporting_payloads"]["member_facts"]

    class Observations:
        def read(self, *, tenant_id, selection):
            return raw

    adapter = AuthorityCompositeMemberResultSource(
        source.definition, observations=Observations(), admitted_source=source
    )
    outcomes = [
        adapter.read_member(
            command,
            None,
            tenant_id="synthetic-tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
            member_id=member,
        )
        for member in source.attestation.expected_portfolio_ids
    ]
    for outcome in outcomes:
        assert outcome.state == "READY", outcome
        assert outcome.fact.ending_market_value is None and outcome.fact.calculation_id is None
        assert outcome.source_evidence.observation_wires == [raw]
        assert "cash_flows" not in raw["rows"][0]
        require_provider_member_evidence(source, command, outcome)
    total = sum((outcome.fact.beginning_market_value for outcome in outcomes), Decimal(0))
    weighted, _ = _build_ready_member_contributions(
        ready_facts=[outcome.fact for outcome in outcomes], beginning_assets=total
    )
    assert abs(weighted - Decimal(numerator) / Decimal(denominator)) < Decimal("1e-25")
    absent_admission = AuthorityCompositeMemberResultSource(source.definition, observations=Observations())
    assert (
        absent_admission.read_member(
            command,
            None,
            tenant_id="synthetic-tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
            member_id=outcomes[0].portfolio_id,
        ).state
        == "BLOCKED"
    )
    monkeypatch.setattr(ports, "method_approval_verifier", lambda: ports.UnavailableApprovalVerification())
    assert (
        adapter.read_member(
            command,
            None,
            tenant_id="synthetic-tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
            member_id=outcomes[0].portfolio_id,
        ).state
        == "BLOCKED"
    )


@pytest.mark.parametrize(
    "mutation", ["impossible", "inverted", "window", "version", "extra_flow", "negative_assets", "duplicate_members"]
)
def test_frozen_monthly_closed_schema_refuses_invalid_dates_versions_and_invented_flows(mutation):
    from app.models.composite_external_facts import SyntheticMonthlyMemberFacts

    raw = shared_packet()["supporting_payloads"]["member_facts"]
    if mutation == "impossible":
        raw.update(period_start="2026-02-30", period_end="2026-02-30")
        for row in raw["rows"]:
            row["beginning_assets_date"] = "2026-02-30"
    elif mutation == "inverted":
        raw.update(period_start="2026-09-30", period_end="2026-09-01")
    elif mutation == "window":
        raw["rows"][0]["beginning_assets_date"] = "2026-09-02"
    elif mutation == "version":
        raw["product_version"] = "v2"
    elif mutation == "negative_assets":
        raw["rows"][0]["beginning_assets"] = "-1"
    elif mutation == "duplicate_members":
        raw["rows"].append(deepcopy(raw["rows"][0]))
    else:
        raw["rows"][0]["cash_flows"] = []
    with pytest.raises(ValidationError):
        SyntheticMonthlyMemberFacts.model_validate(raw)


def test_frozen_monthly_wrong_fee_view_is_refused_by_separate_method_verification(monkeypatch):
    packet = shared_packet()
    install_test_authorities(monkeypatch, packet)
    command = command_for_packet(packet, return_view="NET_ACTUAL")
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit_pinned_source(
            command=command,
            tenant_id="synthetic-tenant-a",
            definition=packet["definition"],
            membership=packet["membership"],
            attestation=packet["attestation"],
        )
    assert refused.value.error_code == "COMPOSITE_METHOD_APPROVAL_UNAVAILABLE"
