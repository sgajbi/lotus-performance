"""Original producer-controlled software fixtures; never ordinary deployment inputs."""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization import authority_policy
from tests.composite_eligibility_helpers import verification_expectation

CONTRACT_ROOT = Path(__file__).parent / "fixtures" / "composite_controlled_scenario"


def fixture(name):
    return json.loads((CONTRACT_ROOT / name).read_bytes())


def graph():
    return fixture("valid-graph.json")


def source_packet():
    return {
        "definition": graph()["finalization"]["definition"],
        "membership": fixture("CompositeMembership.v1.controlled.json"),
        "attestation": fixture("CompositeUniverseAttestation.v1.controlled.json"),
    }


def install_independent_test_trust(monkeypatch, *, denied_purpose=None):
    """Explicit fixed test registration records; no request-selected owner/trust."""
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
    calls = []

    class FixedVerifier:
        def verify(self, request):
            calls.append(request)
            for receipt in receipts:
                if receipt.request == request and request.purpose != denied_purpose:
                    return ports.VerifiedCompositeEvidence(
                        receipt.model_copy(deep=True), verification_expectation(receipt)
                    )
            return ports.UnavailableCompositeEvidence()

    profile = finalization.definition.source_authority.payload
    providers = {provider.provider_id: provider for provider in profile.providers}
    registrations = [
        authority_policy.ProviderTrustRequest(
            profile.tenant_id,
            selection.provider_id,
            providers[selection.provider_id].registry_revision,
            providers[selection.provider_id].registry_digest,
            selection.source_product,
            selection.effective_from,
            selection.effective_to,
        )
        for selection in profile.selections
    ]

    class FixedRegistration:
        def resolve(self, request):
            if request in registrations:
                return authority_policy.ProviderTrustResolution(
                    "SYNTHETIC_TEST_ONLY", "EXPLICIT_CONTROLLED_TEST_REGISTRATION", request.registry_digest
                )
            return authority_policy.ProviderTrustResolution("UNAVAILABLE", "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")

    monkeypatch.setattr(ports, "composite_receipt_verifier", FixedVerifier)
    monkeypatch.setattr(authority_policy, "provider_trust_resolver", FixedRegistration)
    return calls


def install_http_transport(monkeypatch, *, packet=None, receipt=None, status=200):
    """Use the real adapter/retry/decoder path; MockTransport opens no socket."""
    packet = deepcopy(packet or source_packet())
    receipt = deepcopy(receipt or graph())
    definition, membership, attestation = (packet[key] for key in ("definition", "membership", "attestation"))
    prefix = f"/api/v1/rebalance/composites/{definition['composite_id']}/definitions/{definition['definition_version']}"
    membership_path = prefix + "/membership/" + membership["membership_revision"]
    products = {
        prefix: definition,
        membership_path: membership,
        membership_path + "/universe-attestations/" + attestation["attestation_version"]: attestation,
    }
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "manage.test"
        if request.method == "GET":
            assert request.url.path in products
            return httpx.Response(200, json=products[request.url.path])
        assert request.method == "POST" and request.url.path == prefix + "/eligibility-evidence/resolve"
        assert (
            json.loads(request.content) == definition["source_authority"]["payload"]["eligibility_evaluation_binding"]
        )
        return httpx.Response(status, json=receipt)

    @asynccontextmanager
    async def mock_client(*, timeout_seconds):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), timeout=timeout_seconds) as client:
            yield client

    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "http://manage.test/api/v1")
    monkeypatch.setattr(get_settings(), "CORE_MAX_RETRIES", 0)
    monkeypatch.setattr("app.services.http_resilience._request_client", mock_client)
    return calls
