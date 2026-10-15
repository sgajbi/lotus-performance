"""Historical proof integrity and additive version boundaries; source authority is separate."""

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.models import composite_eligibility_evidence as legacy
from app.models import composite_historical_subject_evidence as historical
from app.models.composite_authority import EvidenceBinding, HistoricalSubjectApprovalBinding, authority_digest
from app.models.composite_historical_subject_evidence import HistoricalPolicyVerification
from tests.composite_eligibility_helpers import receipt_wire

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "composite_historical_subject"
PRODUCER_MANIFEST_SHA256 = "2a0ed5df7ec2d3431d9db5d9c1983f64495d3cee96c9f369d3f2caee9d01bd99"


def contract_graph():
    return json.loads((CONTRACT_ROOT / "CompositeEligibilityFinalizationReceipt.v3.controlled.json").read_bytes())


@pytest.mark.parametrize("graph", [receipt_wire, contract_graph], ids=["legacy-v1", "historical-v3"])
def test_provider_claims_binding_refuses_semantic_mutation_after_all_envelope_rehashes(graph):
    wire = graph()
    assert legacy.decode_eligibility_receipt(json.dumps(wire)).model_dump(mode="json") == wire
    provider = next(
        item for item in wire["finalization"]["verifications"] if item["request"]["purpose"] == "PROVIDER_REGISTRATION"
    )
    provider["request"]["claims_digest"] = "sha256:" + "0" * 64
    for envelope in (provider, wire["finalization"], wire):
        envelope["content_hash"] = authority_digest(
            {key: value for key, value in envelope.items() if key != "content_hash"}
        )
    with pytest.raises(ValueError, match="COMPOSITE_VERIFICATION_PROVIDER_BINDING_MISMATCH"):
        legacy.decode_eligibility_receipt(json.dumps(wire))


def graph_nodes(receipt):
    finalization = receipt["finalization"]
    evaluation = finalization["evaluation_approval"]
    proposal = evaluation["proposal"]
    policy = proposal["policy_approval"]
    return (policy["proposal"], policy, proposal, evaluation, finalization, receipt)


def test_source_manifest_raw_schema_and_six_example_hashes_are_pinned():
    manifest_raw = (CONTRACT_ROOT / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == PRODUCER_MANIFEST_SHA256
    manifest = json.loads(manifest_raw)
    assert manifest["production_adapter"] == "UNAVAILABLE"
    assert manifest["consumer_enablement"] == "NOT_ADMITTED"
    for path in CONTRACT_ROOT.glob("*.json"):
        if path.name == "manifest.json":
            continue
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == manifest["raw_file_sha256"][path.name]
        assert authority_digest(json.loads(raw)) == manifest["canonical_content_digests"][path.name]
    for node in graph_nodes(contract_graph()):
        name = node["product_name"] + "." + node["product_version"] + ".controlled.json"
        # The full receipt contains all six source examples. Reconstruct the
        # source's canonical pretty wire instead of storing duplicate graphs.
        raw = (json.dumps(node, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
        assert hashlib.sha256(raw).hexdigest() == manifest["raw_file_sha256"][name]
        assert authority_digest(node) == manifest["canonical_content_digests"][name]


@pytest.mark.parametrize(
    "index,model",
    [
        (0, historical.HistoricalSubjectPolicyProposal),
        (1, historical.HistoricalSubjectPolicyApproval),
        (2, historical.HistoricalSubjectEvaluationProposal),
        (3, historical.HistoricalSubjectEvaluationApproval),
        (4, historical.HistoricalSubjectFinalization),
        (5, historical.HistoricalSubjectFinalizationReceipt),
    ],
)
def test_exact_source_owned_historical_model_and_schema_roundtrip(index, model):
    node = graph_nodes(contract_graph())[index]
    decoded = model.model_validate(node)
    assert decoded.model_dump(mode="json") == node
    assert (
        authority_digest({key: value for key, value in node.items() if key != "content_hash"}) == decoded.content_hash
    )
    name = node["product_name"] + "." + node["product_version"] + ".schema.json"
    source_schema = json.loads((CONTRACT_ROOT / name).read_bytes())
    consumer_schema = model.model_json_schema()
    assert set(source_schema["properties"]) == set(consumer_schema["properties"])
    assert (
        source_schema["properties"]["product_version"]["const"]
        == consumer_schema["properties"]["product_version"]["const"]
    )


@pytest.mark.parametrize(
    "vector", json.loads((CONTRACT_ROOT / "refusal-vectors.json").read_bytes()), ids=lambda value: value["case"]
)
def test_source_owned_tampered_and_mixed_version_vectors_refuse_after_outer_rehash(vector):
    wire = contract_graph()
    keys = vector["pointer"].strip("/").split("/")
    target = wire
    ancestors = [target]
    for key in keys[:-1]:
        target = target[key]
        ancestors.append(target)
    target[keys[-1]] = vector["replacement"]
    # Preserve deliberately corrupt nested hashes, but make every containing
    # envelope coherent so a top-level hash guard cannot mask missing admission.
    for parent in reversed(ancestors):
        if "content_hash" in parent and not (parent is target and keys[-1] == "content_hash"):
            parent["content_hash"] = authority_digest(
                {key: value for key, value in parent.items() if key != "content_hash"}
            )
    with pytest.raises(ValueError):
        legacy.decode_eligibility_receipt(json.dumps(wire))


def test_source_v3_receipt_decoder_retains_full_graph_and_explicit_unavailable_posture():
    wire = contract_graph()
    decoded = legacy.decode_eligibility_receipt(json.dumps(wire))
    assert isinstance(decoded, historical.HistoricalSubjectFinalizationReceipt)
    assert decoded.model_dump(mode="json") == wire
    assert decoded.finalization.evaluation_approval.proposal.source_assembly_evidence is not None
    assert decoded.completeness == "UNVERIFIED"
    assert decoded.finalization.official_activation == "UNAVAILABLE"


def historical_proof():
    original = receipt_wire()["finalization"]["evaluation_approval"]["proposal"]["policy_approval"]["proposal"][
        "proposal"
    ]
    raw = b"controlled original historical policy bytes"
    reference = {
        "issuer_id": "original-issuer",
        "artifact_id": "original-policy",
        "revision": "original-v1",
        "raw_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "signing_contract": "controlled-original-contract",
    }
    mapping = {
        "reference": reference,
        "raw_original_base64": base64.b64encode(raw).decode(),
        "original_credential": "retained-original-format-credential",
        "policy": original["policy"],
        "eligibility_policy_version": original["eligibility_policy_version"],
        "reporting_currency": "USD",
        "attachments": original["attachments"],
        "original_proposed_by": "original-maker",
        "original_approved_by": "original-checker",
        "original_proposed_at": "2026-08-01T00:00:00.000000Z",
        "original_approved_at": "2026-08-02T00:00:00.000000Z",
    }
    mapping["content_hash"] = authority_digest(mapping)
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    digest = "sha256:" + "a" * 64
    proof = {
        "product_name": "CompositeHistoricalPolicyVerification",
        "product_version": "v1",
        "posture": "SYNTHETIC_NON_CERTIFYING",
        "original_signature_status": "VERIFIED_AT_ORIGINAL_APPROVAL",
        "current_revocation_status": "CLEAR",
        "request": {
            "product_name": "CompositeHistoricalPolicyVerificationRequest",
            "product_version": "v1",
            "purpose": "COMPOSITE_HISTORICAL_MONTHLY_POLICY_ADMISSION",
            "operation": "EVALUATION_PROPOSAL",
            "reference": reference,
            "scope": original["policy"]["scope"],
            "month": original["policy"]["month"],
            "eligibility_policy_version": original["eligibility_policy_version"],
            "reporting_currency": "USD",
            "revision": "evaluation-v1",
            "actor_id": "current-maker",
            "requested_at": "2026-10-14T00:00:01.000000Z",
            "intent_digest": digest,
        },
        "mapping": mapping,
        "verifier_id": "independent-verifier",
        "signer_principal_id": "original-signer",
        "verifier_principal_id": "verifier-principal",
        "configuration_digest": digest,
        "signer_key_digest": digest,
        "verifier_key_digest": "sha256:" + hashlib.sha256(public).hexdigest(),
        "verifier_public_key_base64": base64.b64encode(public).decode(),
        "revocation_revision": "current-v1",
        "revocation_digest": digest,
        "checked_at": "2026-10-14T00:00:00.000000Z",
        "admitted_at": "2026-10-14T00:00:01.000000Z",
        "expires_at": "2026-10-14T00:05:00.000000Z",
    }
    proof["verifier_credential"] = base64.b64encode(key.sign(authority_digest(proof).encode())).decode()
    proof["content_hash"] = authority_digest(proof)
    return proof


def test_historical_proof_preserves_original_dates_and_current_admission_signature():
    wire = historical_proof()
    assert HistoricalPolicyVerification.model_validate(wire).model_dump(mode="json") == wire
    assert wire["mapping"]["original_approved_at"] < wire["mapping"]["policy"]["month"]
    assert wire["request"]["requested_at"] > wire["mapping"]["policy"]["month"]


@pytest.mark.parametrize("invalid", ["raw", "mapping", "signature", "key", "window", "independence", "qualified"])
def test_rehashing_outer_proof_never_hides_tampered_original_or_signature(invalid):
    wire = historical_proof()
    if invalid == "raw":
        wire["mapping"]["raw_original_base64"] = base64.b64encode(b"altered original").decode()
        wire["mapping"]["content_hash"] = authority_digest(
            {key: value for key, value in wire["mapping"].items() if key != "content_hash"}
        )
    elif invalid == "mapping":
        wire["request"]["reporting_currency"] = "EUR"
    elif invalid == "signature":
        wire["verifier_credential"] = base64.b64encode(bytes(64)).decode()
    elif invalid == "key":
        wire["verifier_key_digest"] = "sha256:" + "c" * 64
    elif invalid == "window":
        wire["expires_at"] = "2026-10-14T00:06:00.000000Z"
    elif invalid == "independence":
        wire["signer_principal_id"] = wire["verifier_principal_id"]
    else:
        wire["posture"] = "QUALIFIED_RECEIPT"
    wire["content_hash"] = authority_digest({key: value for key, value in wire.items() if key != "content_hash"})
    with pytest.raises(ValueError):
        HistoricalPolicyVerification.model_validate(wire)


def test_generic_v1_binding_is_not_widened_for_historical_control():
    wire = {
        "product_name": "CompositeSubjectEvaluationApproval",
        "product_version": "v2",
        "revision": "v2",
        "digest": "sha256:" + "a" * 64,
    }
    assert HistoricalSubjectApprovalBinding.model_validate(wire).product_version == "v2"
    with pytest.raises(ValueError):
        EvidenceBinding.model_validate(wire)
    with pytest.raises(ValueError):
        HistoricalSubjectApprovalBinding.model_validate({**wire, "product_name": "RETURN_METHOD_CALENDAR"})


@pytest.mark.parametrize("version", ["v2", "v3", "v4"])
def test_decoder_refuses_unknown_or_mixed_historical_receipt_graph(version):
    wire = copy.deepcopy(receipt_wire())
    wire["product_version"] = version
    wire["content_hash"] = authority_digest({key: value for key, value in wire.items() if key != "content_hash"})
    with pytest.raises(ValueError):
        legacy.decode_eligibility_receipt(json.dumps(wire))


def test_legacy_concrete_schema_versions_remain_v1():
    for model in (
        legacy.SubjectPolicyProposal,
        legacy.SubjectPolicyApproval,
        legacy.SubjectEvaluationProposal,
        legacy.SubjectEvaluationApproval,
        legacy.SubjectFinalization,
        legacy.SubjectFinalizationReceipt,
    ):
        assert model.model_json_schema()["properties"]["product_version"]["const"] == "v1"
