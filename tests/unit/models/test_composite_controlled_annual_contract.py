"""Actual producer Slice A graph, full nested custody and old-family isolation."""

import base64
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.models.composite_authority import ManageCompositeDefinitionV2, authority_digest, decode_governed_definition
from app.models.composite_controlled_annual_authority import ControlledAnnualDefinitionV4
from app.models.composite_controlled_annual_evidence import ControlledAnnualFinalizationReceipt
from app.models.composite_controlled_scenario_definition import (
    ControlledAnnualCompositeDefinition,
    decode_retained_definition,
)
from app.models.composite_controlled_scenario_evidence import ControlledScenarioSubjectFinalizationReceipt
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from tests.composite_controlled_annual_helpers import CONTRACT_ROOT, competing_receipt, graph, hash_envelope
from tests.unit.models.test_composite_controlled_scenario_contract import rehash_ancestors


def changing_monthly_population_receipt():
    """Signed software-only variant: February adds a member; March removes a January member."""
    wire = graph()
    definition = wire["finalization"]["definition"]
    payload = definition["source_authority"]["payload"]
    basis = payload["basis_mapping"]["basis"]
    original = payload["member_identities"]
    added = {**original[-1], "member_id": "synthetic-member-8", "source_member_id": "synthetic-member-8"}
    union = [*original, added]
    payload["member_identities"] = deepcopy(union)
    basis["member_identities"] = deepcopy(union)
    for rules in (payload["authority_rules"], basis["authority_rules"]):
        for rule in rules:
            rule["member_ids"] = [member["member_id"] for member in union]
    for index, candidate in enumerate(definition["authority_approval"]["verification"]["candidate_evidence"]):
        if index == 0:
            continue
        candidate["members"] = deepcopy(union if index == 1 else union[1:])
        binding = candidate["registry_binding"]
        binding["digest"] = authority_digest(
            {
                "classification": "SOFTWARE_ONLY_SYNTHETIC_NON_CERTIFYING",
                "month": candidate["month"],
                "members": candidate["members"],
            }
        )
        candidate["source_products"][0]["content_hash"] = binding["digest"]
        basis["months"][index]["candidate_registry_binding"] = deepcopy(binding)
        hash_envelope(candidate)
    return competing_receipt(wire)


def test_annual_union_preserves_distinct_monthly_candidate_addition_and_removal():
    receipt = decode_eligibility_receipt(json.dumps(changing_monthly_population_receipt()))
    proof = receipt.finalization.year_authority_verification
    january, february, march = proof.candidate_evidence[:3]
    assert [len(item.members) for item in (january, february, march)] == [7, 8, 7]
    assert february.members[-1].member_id == "synthetic-member-8"
    assert january.members[0] not in march.members
    assert proof.basis_mapping.basis.member_identities == february.members
    assert receipt.finalization.subject.universe == january
    assert receipt.finalization.official_activation == "UNAVAILABLE" and receipt.completeness == "UNVERIFIED"


def test_signed_year_cannot_change_a_source_identity_under_the_same_member_id():
    wire = changing_monthly_population_receipt()
    candidate = wire["finalization"]["definition"]["authority_approval"]["verification"]["candidate_evidence"][1]
    candidate["members"][0]["source_member_id"] = "another-source-member"
    hash_envelope(candidate)
    with pytest.raises(ValueError, match="COMPOSITE_YEAR_MEMBER_MAP_MISMATCH"):
        decode_eligibility_receipt(json.dumps(competing_receipt(wire)))


def test_signed_year_cannot_omit_a_month_candidate():
    wire = changing_monthly_population_receipt()
    wire["finalization"]["definition"]["authority_approval"]["verification"]["candidate_evidence"].pop(1)
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(competing_receipt(wire)))


def test_complete_producer_graph_roundtrips_with_year_basis_and_actual_january_publication():
    wire = graph()
    receipt = decode_eligibility_receipt(json.dumps(wire))
    assert isinstance(receipt, ControlledAnnualFinalizationReceipt)
    assert receipt.model_dump(mode="json") == wire
    definition = receipt.finalization.definition
    assert isinstance(decode_governed_definition(definition.model_dump()), ControlledAnnualDefinitionV4)
    assert len(receipt.finalization.year_authority_verification.candidate_evidence) == 12
    assert definition.source_authority.payload.mode == "INTERNAL"
    assert definition.source_authority.payload.source_qualification == "UNQUALIFIED"
    assert receipt.completeness == "UNVERIFIED" and receipt.finalization.official_activation == "UNAVAILABLE"
    projection = definition.performance_definition()
    assert isinstance(
        decode_retained_definition(projection.model_dump(mode="json")), ControlledAnnualCompositeDefinition
    )
    assert projection.source_authority == definition.source_authority
    assert [r.request.purpose for r in receipt.finalization.verifications] == [
        "RETURN_METHOD_CALENDAR",
        "PROVIDER_REGISTRATION",
        "PROVIDER_REGISTRATION",
    ]
    assert (
        receipt.finalization.year_authority_verification.request.revision
        == receipt.finalization.subject.subject_revision
    )
    proof = receipt.finalization.year_authority_verification
    assert proof.request.profile_configuration_digest == proof.configuration_digest


def test_resigned_year_proof_cannot_bind_request_to_another_configuration():
    wire = graph()
    finalization = wire["finalization"]
    definition = finalization["definition"]
    proof = definition["authority_approval"]["verification"]
    original_configuration = proof["configuration_digest"]
    other_configuration = authority_digest({"configuration": "another-synthetic-profile"})
    assert other_configuration != original_configuration
    proof["request"]["profile_configuration_digest"] = other_configuration
    # Public fixture key: preserve every other proof field and re-sign the changed request.
    verifier_key = Ed25519PrivateKey.from_private_bytes(bytes(range(96, 128)))
    assert (
        base64.b64encode(verifier_key.public_key().public_bytes_raw()).decode() == proof["verifier_public_key_base64"]
    )
    unsigned = {key: value for key, value in proof.items() if key not in {"content_hash", "verifier_credential"}}
    proof["verifier_credential"] = base64.b64encode(verifier_key.sign(authority_digest(unsigned).encode())).decode()
    hash_envelope(proof)
    hash_envelope(definition)
    finalization["year_authority_verification"] = deepcopy(proof)
    hash_envelope(finalization)
    hash_envelope(wire)
    assert proof["configuration_digest"] == original_configuration
    with pytest.raises(ValueError, match="COMPOSITE_YEAR_REQUEST_MISMATCH"):
        decode_eligibility_receipt(json.dumps(wire))


def test_same_scope_competing_basis_is_structurally_valid_but_has_a_distinct_immutable_definition():
    original = decode_eligibility_receipt(json.dumps(graph()))
    competing = decode_eligibility_receipt(json.dumps(competing_receipt()))
    assert competing.finalization.subject == original.finalization.subject
    assert competing.finalization.evaluation_approval == original.finalization.evaluation_approval
    assert competing.finalization.definition.content_hash != original.finalization.definition.content_hash


@pytest.mark.parametrize("field", ["content_hash", "product_name", "product_version", "completeness"])
def test_required_received_identity_and_posture_cannot_default(field):
    wire = graph()
    wire.pop(field)
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(wire))


@pytest.mark.parametrize(
    "pointer,value",
    [
        ("/product_version", "v4"),
        ("/publication_sequence", True),
        ("/membership_content_hash", "sha256:" + "0" * 64),
        ("/finalization/definition/product_version", "v3"),
        ("/finalization/definition/source_authority/payload/mode", "HYBRID"),
        ("/finalization/definition/source_authority/payload/population_verification", "VERIFIED"),
        ("/finalization/year_authority_verification/request/revision", "another-subject"),
        ("/finalization/year_authority_verification/request/actor_id", "another-checker"),
        ("/finalization/year_authority_verification/request/purpose", "COMPOSITE_CONTROLLED_MONTH_INPUT_PREPARATION"),
        ("/finalization/year_authority_verification/request/year", 2024),
        ("/finalization/year_authority_verification/current_revocation_status", "REVOKED"),
        (
            "/finalization/year_authority_verification/candidate_evidence/11/source_products/0/content_hash",
            "sha256:" + "0" * 64,
        ),
        ("/finalization/year_authority_verification/candidate_evidence/11/generated_at", "2026-10-17T00:00:00.000000Z"),
    ],
)
def test_rehashed_outer_envelopes_cannot_hide_version_scope_intent_or_nested_source_tampering(pointer, value):
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(rehash_ancestors(graph(), pointer, value)))


def test_old_closed_models_do_not_accept_new_annual_wire():
    wire = graph()
    with pytest.raises(ValueError):
        ControlledScenarioSubjectFinalizationReceipt.model_validate(wire)
    with pytest.raises(ValueError):
        ManageCompositeDefinitionV2.model_validate(wire["finalization"]["definition"])


def test_duplicate_raw_json_keys_refuse_before_projection():
    wire = json.dumps(graph()).replace('"product_version": "v5"', '"product_version": "v5", "product_version": "v5"', 1)
    with pytest.raises(ValueError, match="Duplicate authority JSON key"):
        decode_eligibility_receipt(wire)


def test_raw_year_basis_cannot_gain_financial_or_self_hash_fields():
    from app.models.composite_controlled_annual_basis import CompositeControlledYearBasis

    basis = deepcopy(graph()["finalization"]["definition"]["source_authority"]["payload"]["basis_mapping"]["basis"])
    basis["definition_content_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        CompositeControlledYearBasis.model_validate(basis)


def test_rule_ordered_duplicate_provider_requests_remain_valid_without_deduplication():
    wire = graph()
    payload = wire["finalization"]["definition"]["source_authority"]["payload"]
    ending = deepcopy(payload["authority_rules"][0])
    ending.update(rule_id="rule-3", fact="ENDING_ASSETS")
    payload["authority_rules"].append(ending)
    payload["basis_mapping"]["basis"]["authority_rules"].append(deepcopy(ending))
    wire["finalization"]["verifications"].append(deepcopy(wire["finalization"]["verifications"][1]))
    receipt = decode_eligibility_receipt(json.dumps(competing_receipt(wire)))
    assert len(receipt.finalization.verifications) == 4
    assert receipt.finalization.verifications[1] == receipt.finalization.verifications[3]


def test_provider_receipt_order_is_part_of_the_publication_contract():
    wire = graph()
    rows = wire["finalization"]["verifications"]
    rows[1], rows[2] = rows[2], rows[1]
    hash_envelope(wire["finalization"])
    hash_envelope(wire)
    with pytest.raises(ValueError, match="PROVIDER_BINDING_MISMATCH"):
        decode_eligibility_receipt(json.dumps(wire))


def test_original_source_actual_issuance_cannot_be_after_its_retained_admission():
    wire = graph()
    wire["finalization"]["definition"]["source_authority"]["payload"]["basis_mapping"]["basis"]["actual_issued_at"] = (
        "2099-01-01T00:00:00.000000Z"
    )
    with pytest.raises(ValueError, match="COMPOSITE_YEAR_CLOCK_MISMATCH"):
        decode_eligibility_receipt(json.dumps(competing_receipt(wire)))


def test_rule_coverage_accepts_adjacent_intervals_and_refuses_a_real_gap():
    from app.models.composite_controlled_annual_basis import CompositeControlledYearBasis, year_rules_for_window

    basis = deepcopy(graph()["finalization"]["definition"]["source_authority"]["payload"]["basis_mapping"]["basis"])
    initial = basis["authority_rules"][0]
    successor = deepcopy(initial)
    initial["effective_to"] = "2025-01-15"
    successor.update(rule_id="rule-3", effective_from="2025-01-16")
    basis["authority_rules"].append(successor)
    typed = CompositeControlledYearBasis.model_validate(basis)
    rules = year_rules_for_window(
        typed, typed.member_identities[0].member_id, "BEGINNING_ASSETS", "2025-01-01", "2025-01-31"
    )
    assert len(rules) == 2
    successor["effective_from"] = "2025-01-17"
    typed = CompositeControlledYearBasis.model_validate(basis)
    with pytest.raises(ValueError, match="COVERAGE_MISMATCH"):
        year_rules_for_window(
            typed, typed.member_identities[0].member_id, "BEGINNING_ASSETS", "2025-01-01", "2025-01-31"
        )


def test_validly_signed_competing_basis_cannot_name_another_first_month_policy_original():
    wire = graph()
    basis = wire["finalization"]["definition"]["source_authority"]["payload"]["basis_mapping"]["basis"]
    basis["months"][0]["monthly_policy_reference"]["artifact_id"] = "another-january-original"
    with pytest.raises(ValueError, match="COMPOSITE_YEAR_POLICY_REFERENCE_MISMATCH"):
        decode_eligibility_receipt(json.dumps(competing_receipt(wire)))


def test_registry_generation_may_follow_request_creation_but_cannot_follow_admission():
    wire = graph()
    proof = wire["finalization"]["definition"]["authority_approval"]["verification"]
    admitted = datetime.fromisoformat(proof["admitted_at"])
    proof["candidate_evidence"][11]["generated_at"] = proof["admitted_at"]
    hash_envelope(proof["candidate_evidence"][11])
    valid = decode_eligibility_receipt(json.dumps(competing_receipt(wire)))
    assert valid.finalization.year_authority_verification.candidate_evidence[11].generated_at == proof["admitted_at"]
    proof["candidate_evidence"][11]["generated_at"] = (admitted + timedelta(microseconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    hash_envelope(proof["candidate_evidence"][11])
    with pytest.raises(ValueError, match="CANDIDATE_CLOCK_MISMATCH"):
        decode_eligibility_receipt(json.dumps(competing_receipt(wire)))


def test_frozen_source_artifacts_and_published_consumer_schemas_match():
    from app.models.composite_authority import authority_digest

    manifest = json.loads((CONTRACT_ROOT / "manifest.json").read_bytes())
    for name, expected in manifest["raw_file_sha256"].items():
        raw = (CONTRACT_ROOT / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        assert len(raw) == manifest["raw_file_bytes"][name]
    assert (
        authority_digest(json.loads((CONTRACT_ROOT / "valid-graph.json").read_bytes()))
        == manifest["canonical_content_digest"]
    )
    schemas = json.loads((CONTRACT_ROOT / "schemas.json").read_bytes())
    assert schemas["CompositeDefinition.v4"] == ControlledAnnualDefinitionV4.model_json_schema()
    assert (
        schemas["CompositeEligibilityFinalizationReceipt.v5"] == ControlledAnnualFinalizationReceipt.model_json_schema()
    )
