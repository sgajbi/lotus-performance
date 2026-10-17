"""Frozen producer software evidence and separately fixed non-certifying trust."""

import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.models.composite_authority import authority_digest
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.ports import composite_controlled_annual_evidence as year_ports
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization import authority_policy, controlled_annual_authority
from tests.composite_authority_helpers import command_for_packet
from tests.composite_eligibility_helpers import verification_expectation

CONTRACT_ROOT = Path(__file__).parent / "fixtures" / "composite_controlled_annual"
SOURCE_PUBLIC_KEY = "JUO5L/EJVRFHatyDadtt3JM2ZaEZeN2hQE7hBmypVZ0="


def fixture():
    return json.loads((CONTRACT_ROOT / "valid-graph.json").read_bytes())


def graph():
    return fixture()["receipt"]


def source_packet():
    item = fixture()
    return {
        "definition": item["receipt"]["finalization"]["definition"],
        "membership": item["membership"],
        "attestation": item["universe"],
    }


def command(packet=None, **changes):
    packet = packet or source_packet()
    return command_for_packet(
        packet,
        period_start=packet["attestation"]["coverage_from"],
        period_end=packet["attestation"]["coverage_to"],
        **changes,
    )


def install_independent_test_trust(monkeypatch, *, denied_purpose=None, denied_year=False):
    finalization = decode_eligibility_receipt(json.dumps(graph())).finalization
    proposal = finalization.evaluation_approval.proposal
    receipts = [
        proposal.policy_approval.proposal.verification,
        proposal.policy_approval.verification,
        finalization.evaluation_approval.verification,
        *finalization.verifications,
    ]
    if proposal.source_assembly_evidence is not None:
        receipts.append(proposal.source_assembly_evidence.verification)
    proof = finalization.year_authority_verification
    expectation = year_ports.ControlledYearVerificationExpectation(
        request=proof.request.model_copy(deep=True),
        verifier_id=proof.verifier_id,
        signer_principal_id=proof.signer_principal_id,
        verifier_principal_id=proof.verifier_principal_id,
        configuration_digest=proof.configuration_digest,
        signer_key_digest=proof.signer_key_digest,
        verifier_key_digest=proof.verifier_key_digest,
        source_public_key_base64=SOURCE_PUBLIC_KEY,
        source_key_valid_from="2000-01-01T00:00:00.000000Z",
        source_key_valid_to="2100-01-01T00:00:00.000000Z",
        verifier_key_valid_from="2000-01-01T00:00:00.000000Z",
        verifier_key_valid_to="2100-01-01T00:00:00.000000Z",
        revocation_revision=proof.revocation_revision,
        revocation_digest=proof.revocation_digest,
        source_evidence_digest=proof.source_evidence_digest,
    )
    calls = []

    class FixedYearVerifier:
        def verify(self, request):
            calls.append(request)
            if not denied_year and request == proof.request:
                return year_ports.VerifiedControlledYearEvidence(proof.model_copy(deep=True), expectation)
            return None

    class FixedReceiptVerifier:
        def verify(self, request):
            calls.append(request)
            for receipt in receipts:
                if request == receipt.request and request.purpose != denied_purpose:
                    return ports.VerifiedCompositeEvidence(
                        receipt.model_copy(deep=True), verification_expectation(receipt)
                    )
            return ports.UnavailableCompositeEvidence()

    payload = finalization.definition.source_authority.payload
    providers = {item.provider_id: item for item in payload.providers}
    registrations = [
        authority_policy.ProviderTrustRequest(
            payload.tenant_id,
            rule.provider_id,
            providers[rule.provider_id].registry_revision,
            providers[rule.provider_id].registry_digest,
            rule.source_product,
            rule.effective_from,
            rule.effective_to,
        )
        for rule in payload.authority_rules
    ]

    class FixedRegistration:
        def resolve(self, request):
            if request in registrations and denied_purpose != "PROVIDER_TRUST":
                return authority_policy.ProviderTrustResolution(
                    "SYNTHETIC_TEST_ONLY", "FIXED_YEAR_TEST_RECORD", request.registry_digest
                )
            return authority_policy.ProviderTrustResolution("UNAVAILABLE", "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")

    monkeypatch.setattr(year_ports, "controlled_year_verifier", FixedYearVerifier)
    monkeypatch.setattr(ports, "composite_receipt_verifier", FixedReceiptVerifier)
    monkeypatch.setattr(controlled_annual_authority, "provider_trust_resolver", FixedRegistration)
    return calls


def competing_receipt(receipt=None):
    """Another valid software declaration B; never trusted by A's fixed records."""
    item = deepcopy(receipt or graph())
    finalization = item["finalization"]
    definition = finalization["definition"]
    profile = definition["source_authority"]
    profile["payload"]["eligibility_evaluation_binding"]["digest"] = finalization["evaluation_approval"]["content_hash"]
    mapping = profile["payload"]["basis_mapping"]
    basis = mapping["basis"]
    basis["artifact_id"] += ".competing"
    # Public, fixed unit-test material; never an application/provider key.
    source_key = Ed25519PrivateKey.from_private_bytes(bytes([17]) * 32)
    verifier_key = Ed25519PrivateKey.from_private_bytes(bytes([19]) * 32)
    raw = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    mapping["reference"].update(
        artifact_id=basis["artifact_id"], raw_digest="sha256:" + hashlib.sha256(raw).hexdigest()
    )
    mapping["raw_original_base64"] = base64.b64encode(raw).decode()
    mapping["original_credential"] = base64.b64encode(source_key.sign(raw)).decode()
    hash_envelope(mapping)
    profile["profile_digest"] = authority_digest(profile["payload"])
    definition["definition_payload_digest"] = authority_digest(
        {
            key: value
            for key, value in definition.items()
            if key not in {"content_hash", "authority_approval", "definition_payload_digest"}
        }
    )
    approval = definition["authority_approval"]
    claims = approval["claims"]
    claims.update(
        profile_digest=profile["profile_digest"],
        definition_payload_digest=definition["definition_payload_digest"],
        basis_raw_digest=mapping["reference"]["raw_digest"],
        eligibility_evidence_digest=profile["payload"]["eligibility_evaluation_binding"]["digest"],
    )
    proof = approval["verification"]
    proof["basis_mapping"] = deepcopy(mapping)
    proof["claims"] = deepcopy(claims)
    proof["request"].update(basis_reference=deepcopy(mapping["reference"]), intent_digest=authority_digest(claims))
    proof["source_evidence_digest"] = authority_digest(
        {"basis_mapping": mapping, "candidate_evidence": proof["candidate_evidence"]}
    )
    public = verifier_key.public_key().public_bytes_raw()
    proof.update(
        signer_key_digest="sha256:" + hashlib.sha256(source_key.public_key().public_bytes_raw()).hexdigest(),
        verifier_key_digest="sha256:" + hashlib.sha256(public).hexdigest(),
        verifier_public_key_base64=base64.b64encode(public).decode(),
    )
    unsigned = {key: value for key, value in proof.items() if key not in {"content_hash", "verifier_credential"}}
    proof["verifier_credential"] = base64.b64encode(verifier_key.sign(authority_digest(unsigned).encode())).decode()
    hash_envelope(proof)
    hash_envelope(definition)
    finalization["year_authority_verification"] = deepcopy(proof)
    hash_envelope(finalization)
    hash_envelope(item)
    return item


def hash_envelope(value):
    value["content_hash"] = authority_digest({key: item for key, item in value.items() if key != "content_hash"})
    return value
