"""Pinned additive scenario wires and exact pre-existing exported contracts."""

import copy
import hashlib
import importlib
import json

import pytest

from app.models.composite_authority import (
    CompositeAuthorityPayload,
    EvidenceBinding,
    ManageCompositeDefinitionV2,
    authority_digest,
)
from app.models.composite_controlled_scenario_evidence import ControlledScenarioSubjectFinalizationReceipt
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from tests.composite_controlled_scenario_helpers import CONTRACT_ROOT, fixture, graph

PRODUCER_MANIFEST_SHA256 = "ac71e6e976ce3c053524b6acac0827b972092bc90ffcb780266093295eb14f9b"


def test_all_original_producer_bytes_canonical_pins_and_companion_joins_match():
    manifest = fixture("manifest.json")
    assert hashlib.sha256((CONTRACT_ROOT / "manifest.json").read_bytes()).hexdigest() == PRODUCER_MANIFEST_SHA256
    assert manifest["consumer_enablement"] == "NOT_ADMITTED"
    assert manifest["official_activation"] == "UNAVAILABLE"
    assert manifest["posture"] == "SYNTHETIC_NON_CERTIFYING"
    for name, expected in manifest["raw_file_sha256"].items():
        wire = (CONTRACT_ROOT / name).read_bytes()
        assert hashlib.sha256(wire).hexdigest() == expected
        assert authority_digest(json.loads(wire)) == manifest["canonical_content_digests"][name]
    receipt = graph()
    assert fixture("CompositeMembership.v1.controlled.json")["content_hash"] == receipt["membership_content_hash"]
    assert (
        fixture("CompositeUniverseAttestation.v1.controlled.json")["content_hash"] == receipt["universe_content_hash"]
    )


def test_all_71_exported_legacy_schemas_are_exactly_preserved():
    expected = fixture("legacy-schema-digests.json")
    assert len(expected) == 71
    for qualified, digest in expected.items():
        module, name = qualified.rsplit(".", 1)
        schema = getattr(importlib.import_module(module), name).model_json_schema()
        assert authority_digest(schema) == "sha256:" + digest, qualified


def test_complete_new_graph_roundtrips_without_changing_any_nested_wire_or_hash():
    wire = graph()
    decoded = decode_eligibility_receipt(json.dumps(wire))
    assert isinstance(decoded, ControlledScenarioSubjectFinalizationReceipt)
    assert decoded.model_dump(mode="json") == wire
    schema = fixture("schemas.json")["CompositeEligibilityFinalizationReceipt.v4"]
    own = ControlledScenarioSubjectFinalizationReceipt.model_json_schema()
    assert set(schema["properties"]) == set(own["properties"])
    # Producer construction defaults are not absent consumer wire identities.
    assert set(schema["required"]) <= set(own["required"])
    assert set(own["required"]) - set(schema["required"]) == {
        "content_hash",
        "product_name",
        "product_version",
        "completeness",
    }
    assert own["properties"]["product_version"]["const"] == "v4"
    assert decoded.completeness == "UNVERIFIED"
    assert decoded.finalization.official_activation == "UNAVAILABLE"
    assert decoded.finalization.definition.product_version == "v3"


@pytest.mark.parametrize("field", ["content_hash", "product_name", "product_version", "completeness"])
def test_received_wire_cannot_omit_explicit_hash_product_version_or_posture(field):
    wire = graph()
    wire.pop(field)
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(wire))


def rehash_ancestors(wire, pointer, replacement):
    keys = pointer.strip("/").split("/")
    target = wire
    ancestors = [target]
    for key in keys[:-1]:
        target = target[int(key)] if isinstance(target, list) else target[key]
        ancestors.append(target)
    target[int(keys[-1]) if isinstance(target, list) else keys[-1]] = replacement
    for parent in reversed(ancestors):
        if isinstance(parent, dict) and "content_hash" in parent:
            parent["content_hash"] = authority_digest(
                {key: value for key, value in parent.items() if key != "content_hash"}
            )
    return wire


@pytest.mark.parametrize("vector", fixture("refusal-vectors.json"), ids=lambda value: value["pointer"])
def test_all_eight_source_refusal_vectors_fail_after_containing_hashes_are_repaired(vector):
    wire = rehash_ancestors(graph(), vector["pointer"], vector["replacement"])
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(wire))


@pytest.mark.parametrize(
    "suffix,value",
    [
        ("scenario_approved_at", "2026-09-01T00:00:00.000000Z"),
        ("scenario_proposed_at", "2026-08-21T00:00:00.000000Z"),
        ("scenario_approved_by", "synthetic-maker"),
        ("original_approved_at", "2026-08-20T00:00:00.000000Z"),
        ("actual_issued_at", "2099-01-01T00:00:00.000000Z"),
        ("reporting_currency", "EUR"),
    ],
)
def test_scenario_clock_identity_and_legacy_alias_mutations_refuse(suffix, value):
    pointer = "/finalization/evaluation_approval/operation_verification/mapping/" + suffix
    wire = rehash_ancestors(graph(), pointer, value)
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(wire))


@pytest.mark.parametrize("field", ["signer_principal_id", "signer_key_digest"])
def test_actual_issuance_verifier_independence_is_mandatory(field):
    wire = graph()
    proof = wire["finalization"]["evaluation_approval"]["operation_verification"]
    replacement = proof["verifier_principal_id" if field == "signer_principal_id" else "verifier_key_digest"]
    rehash_ancestors(wire, "/finalization/evaluation_approval/operation_verification/" + field, replacement)
    with pytest.raises(ValueError, match="INDEPENDENCE_REQUIRED"):
        decode_eligibility_receipt(json.dumps(wire))


def test_old_definition_authority_and_generic_binding_never_admit_new_binding():
    definition = graph()["finalization"]["definition"]
    profile = definition["source_authority"]["payload"]
    binding = profile["eligibility_evaluation_binding"]
    with pytest.raises(ValueError):
        EvidenceBinding.model_validate(binding)
    with pytest.raises(ValueError):
        ManageCompositeDefinitionV2.model_validate(definition)
    mixed = copy.deepcopy(profile)
    mixed["product_version"] = "v2"
    with pytest.raises(ValueError):
        CompositeAuthorityPayload.model_validate(mixed)


@pytest.mark.parametrize("product", ["definition", "authority"])
def test_new_graph_refuses_old_definition_and_authority_even_after_outer_rehash(product):
    suffix = "" if product == "definition" else "/source_authority/payload"
    wire = rehash_ancestors(graph(), "/finalization/definition" + suffix + "/product_version", "v2")
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(wire))


@pytest.mark.parametrize(
    "field", ["posture", "original_signature_status", "signature_semantics", "current_revocation_status"]
)
def test_scenario_proof_cannot_escalate_qualification_or_relabel_historical_signatures(field):
    wire = rehash_ancestors(
        graph(), "/finalization/evaluation_approval/operation_verification/" + field, "QUALIFIED_RECEIPT"
    )
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(wire))


@pytest.mark.parametrize(
    "suffix,value,reason",
    [
        ("verifier_id", "foreign-verifier", "VERIFIER_SIGNATURE_INVALID"),
        ("verifier_credential", "AAAA", "VERIFIER_SIGNATURE_INVALID"),
        ("request/actor_id", "foreign-actor", "VERIFIER_SIGNATURE_INVALID"),
        ("request/scope/tenant_id", "foreign-tenant", "MAPPING_MISMATCH"),
        ("request/month", "2026-10", "MAPPING_MISMATCH"),
        ("request/reporting_currency", "EUR", "MAPPING_MISMATCH"),
        ("expires_at", "2099-01-01T00:00:00.000000Z", "ADMISSION_WINDOW_INVALID"),
        ("admitted_at", "2000-01-01T00:00:00.000000Z", "ADMISSION_WINDOW_INVALID"),
    ],
)
def test_rehashed_proof_tampering_still_refuses_signature_scope_and_admission_window(suffix, value, reason):
    wire = rehash_ancestors(graph(), "/finalization/evaluation_approval/operation_verification/" + suffix, value)
    with pytest.raises(ValueError, match=reason):
        decode_eligibility_receipt(json.dumps(wire))


@pytest.mark.parametrize(
    "suffix,value",
    [
        ("observation_binding/owner_service", "foreign-owner"),
        ("observation_binding/source_cut_id", "foreign-cut"),
        ("observations/portfolios/0/currency", "EUR"),
        ("observations/expected_portfolio_ids/0", "foreign-member"),
    ],
)
def test_rehashed_evaluation_cannot_replace_source_owner_cut_currency_or_members(suffix, value):
    wire = rehash_ancestors(graph(), "/finalization/evaluation_approval/proposal/" + suffix, value)
    with pytest.raises(ValueError):
        decode_eligibility_receipt(json.dumps(wire))
