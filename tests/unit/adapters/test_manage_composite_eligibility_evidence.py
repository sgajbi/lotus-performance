"""In-process exact Manage resolver admission; no deployed or financial acceptance."""

import json
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError

from app.adapters.composite_membership_source import ManageCompositeMembershipSource
from app.adapters.manage_composite_eligibility_evidence import ManageCompositeEligibilityEvidence, manage_read_headers
from app.core.config import get_settings
from app.models.composite_eligibility_evidence import SubjectFinalizationReceipt
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization.source_contract import (
    PinnedCompositeSource,
    admit_pinned_source,
    published_eligibility_from_wire,
    require_pinned_source_scope,
    source_digest,
)
from core.errors import APIError
from tests.composite_authority_helpers import command_for_packet, rehash_definition
from tests.composite_eligibility_helpers import (
    install_lifecycle_test_verifier,
    producer_fixture,
    receipt_wire,
    rehash_lifecycle,
    source_packet,
)


def install_http(monkeypatch, *, status=200, wire=None, products=None):
    packet = products or source_packet()
    responses = iter([packet[key] for key in ("definition", "membership", "attestation")])
    calls = []

    async def get(**kwargs):
        calls.append(("GET", kwargs))
        return 200, next(responses)

    async def post(**kwargs):
        calls.append(("POST", kwargs))
        response = httpx.Response(status, text=wire or json.dumps(receipt_wire()))
        return status, kwargs["response_decoder"](response)

    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "http://manage/api/v1/")
    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", get)
    monkeypatch.setattr("app.adapters.manage_composite_eligibility_evidence.post_with_retry", post)
    return calls


async def read_pinned(packet=None):
    packet = packet or source_packet()
    command = command_for_packet(packet)
    return await ManageCompositeMembershipSource().read_pinned(
        command,
        tenant_id="synthetic-tenant",
        actor_id="reader",
        role="DPM_COMPOSITE_CONSUMER",
    )


@pytest.mark.asyncio
async def test_resolver_structurally_invalid_success_has_typed_refusal(monkeypatch):
    calls = install_http(monkeypatch, wire=json.dumps({"product_name": "SubjectFinalizationReceipt"}))
    with pytest.raises(APIError) as refused:
        await read_pinned()
    assert refused.value.error_code == "COMPOSITE_ELIGIBILITY_SOURCE_SCHEMA_INVALID"
    assert [kind for kind, _ in calls] == ["GET", "GET", "GET", "POST"]


@pytest.mark.asyncio
async def test_resolver_refuses_non_lifecycle_binding_before_post(monkeypatch):
    packet = source_packet()
    packet["definition"]["source_authority"]["payload"]["eligibility_evaluation_binding"]["product_name"] = (
        "OtherApproval"
    )
    rehash_definition(packet["definition"])
    calls = install_http(monkeypatch, products=packet)
    with pytest.raises(APIError) as refused:
        await ManageCompositeEligibilityEvidence().read_published(
            command_for_packet(packet),
            tenant_id="synthetic-tenant",
            actor_id="reader",
            role="DPM_COMPOSITE_CONSUMER",
            **{key: packet[key] for key in ("definition", "membership", "attestation")},
        )
    assert refused.value.error_code == "COMPOSITE_ELIGIBILITY_RESOLUTION_BINDING_MISMATCH"
    assert calls == []


def test_nonstr_header_name_cannot_enter_upstream_authority():
    with pytest.raises(APIError) as refused:
        manage_read_headers(
            {1: "value"}, tenant_id="synthetic-tenant", actor_id="reader", role="DPM_COMPOSITE_CONSUMER"
        )
    assert refused.value.error_code == "COMPOSITE_UPSTREAM_AUTHORITY_CONFLICT"


@pytest.mark.asyncio
async def test_exact_resolver_post_and_separate_canonical_reads_with_independent_synthetic_verifier(monkeypatch):
    calls = install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)
    source = await read_pinned()
    assert [method for method, _ in calls] == ["GET", "GET", "GET", "POST"]
    post = calls[-1][1]
    assert (
        post["url"]
        == "http://manage/api/v1/rebalance/composites/synthetic-composite/definitions/synthetic-definition/eligibility-evidence/resolve"
    )
    binding = source.definition.source_authority.payload.eligibility_evaluation_binding
    assert post["json_body"] == binding.model_dump()
    assert set(post["json_body"]) == {"product_name", "product_version", "revision", "digest"}
    assert post["headers"]["X-Tenant-Id"] == "synthetic-tenant"
    assert post["headers"]["X-Actor-Id"] == "reader"
    assert post["headers"]["X-Role"] == "DPM_COMPOSITE_CONSUMER"
    assert post["timeout_seconds"] == get_settings().MANAGE_TIMEOUT_SECONDS
    assert post["max_retries"] == get_settings().CORE_MAX_RETRIES
    assert post["backoff_seconds"] == get_settings().CORE_RETRY_BACKOFF_SECONDS
    assert source.published_eligibility.receipt.model_dump() == receipt_wire()
    assert source.published_eligibility.receipt.finalization.official_activation == "UNAVAILABLE"
    assert source.wire_evidence.definition == source_packet()["definition"]
    restored = PinnedCompositeSource.model_validate_json(source.model_dump_json())
    require_pinned_source_scope(restored, command=command_for_packet(source_packet()), tenant_id="synthetic-tenant")
    assert restored.published_eligibility.receipt.model_dump() == receipt_wire()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (404, "COMPOSITE_ELIGIBILITY_SOURCE_REFUSED", False),
        (409, "COMPOSITE_ELIGIBILITY_SOURCE_REFUSED", False),
        (422, "COMPOSITE_ELIGIBILITY_SOURCE_REFUSED", False),
        (429, "COMPOSITE_ELIGIBILITY_SOURCE_UNAVAILABLE", True),
        (503, "COMPOSITE_ELIGIBILITY_SOURCE_UNAVAILABLE", True),
    ],
)
async def test_staged_only_missing_publication_foreign_or_unavailable_resolver_refuses(
    monkeypatch, status, code, retryable
):
    calls = install_http(monkeypatch, status=status, wire='{"detail":"not published"}')
    install_lifecycle_test_verifier(monkeypatch)
    with pytest.raises(APIError) as error:
        await read_pinned()
    assert (error.value.error_code, error.value.retryable) == (code, retryable)
    assert len(calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wire",
    [
        '{"content_hash":"x","content_hash":"y"}',
        '{"amount":0.10}',
        '{"amount":NaN}',
    ],
)
async def test_raw_successful_resolver_json_rejects_duplicate_keys_and_nonstring_decimals(monkeypatch, wire):
    install_http(monkeypatch, wire=wire)
    install_lifecycle_test_verifier(monkeypatch)
    with pytest.raises(APIError) as error:
        await read_pinned()
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_SOURCE_SCHEMA_INVALID"


@pytest.mark.asyncio
async def test_resolver_reply_cannot_replace_exact_final_definition(monkeypatch):
    wire = receipt_wire()
    # A self-consistent final definition carrying a different authority approval is still a different canonical product.
    definition = wire["finalization"]["definition"]
    definition["authority_approval"]["claims"]["approving_identity"] = "other-checker"
    from app.models.composite_authority import authority_digest
    from tests.composite_authority_helpers import rehash_definition

    rehash_definition(definition)
    verification = wire["finalization"]["verifications"][0]
    verification["request"]["claims_digest"] = authority_digest(definition["authority_approval"]["claims"])
    rehash_lifecycle(wire)
    install_http(monkeypatch, wire=json.dumps(wire))
    with pytest.raises(APIError) as error:
        await read_pinned()
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_FINAL_DEFINITION_MISMATCH"


@pytest.mark.asyncio
async def test_canonical_hash_corruption_refuses_before_resolver_post(monkeypatch):
    packet = source_packet()
    packet["membership"]["decided_by"] = "mutated"
    calls = install_http(monkeypatch, products=packet)
    with pytest.raises(APIError) as error:
        await read_pinned(source_packet())
    assert error.value.error_code == "COMPOSITE_SOURCE_HASH_MISMATCH"
    assert [method for method, _ in calls] == ["GET", "GET", "GET"]


@pytest.mark.asyncio
async def test_unconfigured_or_foreign_tenant_resolver_never_posts(monkeypatch):
    calls = install_http(monkeypatch)
    packet = source_packet()
    command = command_for_packet(packet)
    adapter = ManageCompositeEligibilityEvidence()
    with pytest.raises(APIError) as error:
        await adapter.read_published(
            command, tenant_id="foreign-tenant", actor_id="reader", role="DPM_COMPOSITE_CONSUMER", **packet
        )
    assert error.value.error_code == "COMPOSITE_SOURCE_SCOPE_MISMATCH"
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    with pytest.raises(APIError) as error:
        await adapter.read_published(
            command, tenant_id="synthetic-tenant", actor_id="reader", role="DPM_COMPOSITE_CONSUMER", **packet
        )
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_SOURCE_UNAVAILABLE"
    assert calls == []


def test_real_admission_requires_resolved_publication_before_any_calculation(monkeypatch):
    packet = source_packet()
    install_lifecycle_test_verifier(monkeypatch)
    with pytest.raises(APIError) as error:
        admit_pinned_source(command=command_for_packet(packet), tenant_id="synthetic-tenant", **packet)
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_PUBLISHED_CUSTODY_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", ["default", "boolean", "body-only"])
async def test_resolved_http_receipt_is_insufficient_without_independent_typed_verifier(monkeypatch, proof):
    install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)

    class UnqualifiedVerifier:
        def verify(self, request):
            return (
                True
                if proof == "boolean"
                else SubjectFinalizationReceipt.model_validate(receipt_wire()).finalization.verifications[0]
            )

    if proof == "default":
        monkeypatch.setattr(ports, "composite_receipt_verifier", ports.UnavailableReceiptVerification)
    else:
        monkeypatch.setattr(ports, "composite_receipt_verifier", UnqualifiedVerifier)
    with pytest.raises(APIError) as error:
        await read_pinned()
    assert error.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_retained_policy_headers_reach_all_reads_and_resolver_without_unrelated_leak(monkeypatch):
    calls = install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)
    retained = {
        "x-TENANT-id": "synthetic-tenant",
        "X-ACTOR-ID": "reader",
        "x-role": "DPM_COMPOSITE_CONSUMER",
        "x-SERVICE-identity": "local-network-proof",
        "X-capabilities": "manage.write",
        "x-correlation-ID": "retained-origin",
        "Authorization": "must-not-forward",
        "Cookie": "must-not-forward",
    }
    adapter = ManageCompositeMembershipSource(request_headers=retained)
    retained["X-capabilities"] = "mutated-after-composition"
    await adapter.read_pinned(
        command_for_packet(source_packet()),
        tenant_id="synthetic-tenant",
        actor_id="reader",
        role="DPM_COMPOSITE_CONSUMER",
    )
    assert len(calls) == 4
    for _, call in calls:
        headers = call["headers"]
        assert headers["X-Tenant-Id"] == "synthetic-tenant"
        assert headers["X-Actor-Id"] == "reader"
        assert headers["X-Role"] == "DPM_COMPOSITE_CONSUMER"
        assert headers["X-Service-Identity"] == "local-network-proof"
        assert headers["X-Capabilities"] == "manage.write"
        assert headers["X-Correlation-Id"] == "retained-origin"
        assert "authorization" not in {name.lower() for name in headers}
        assert "cookie" not in {name.lower() for name in headers}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retained",
    [
        {"X-Tenant-Id": "other-tenant"},
        {"X-Actor-Id": "other-actor"},
        {"X-Role": "other-role"},
        {"X-Tenant-Id": "synthetic-tenant", "x-tenant-id": "other-tenant"},
        {"X-Actor-Id": "reader", "x-actor-id": "reader"},
        {"X-Service-Identity": "one", "x-service-identity": "two"},
    ],
)
@pytest.mark.parametrize("adapter_name", ["membership", "eligibility"])
async def test_conflicting_or_duplicate_retained_authority_refuses_before_network(monkeypatch, retained, adapter_name):
    calls = install_http(monkeypatch)
    packet = source_packet()
    command = command_for_packet(packet)
    with pytest.raises(APIError) as error:
        if adapter_name == "membership":
            await ManageCompositeMembershipSource(request_headers=retained).read_pinned(
                command, tenant_id="synthetic-tenant", actor_id="reader", role="DPM_COMPOSITE_CONSUMER"
            )
        else:
            await ManageCompositeEligibilityEvidence(request_headers=retained).read_published(
                command, tenant_id="synthetic-tenant", actor_id="reader", role="DPM_COMPOSITE_CONSUMER", **packet
            )
    assert error.value.error_code == "COMPOSITE_UPSTREAM_AUTHORITY_CONFLICT"
    assert calls == []


@pytest.mark.asyncio
async def test_absent_service_identity_and_capability_are_never_invented(monkeypatch):
    calls = install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)
    await read_pinned()
    for _, call in calls:
        assert "X-Service-Identity" not in call["headers"]
        assert "X-Capabilities" not in call["headers"]


@pytest.mark.asyncio
async def test_restored_typed_publication_cannot_coerce_boolean_sequence_into_custody(monkeypatch):
    install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)
    source = await read_pinned()
    wire = source.model_dump(mode="json")
    wire["published_eligibility"]["publication_sequence"] = True
    with pytest.raises(ValidationError, match="publication_sequence"):
        PinnedCompositeSource.model_validate(wire)


@pytest.mark.parametrize("wire", ['{"count":1,"count":2}', '{"count":1.0}', '{"count":NaN}'])
def test_v2_canonical_membership_and_universe_raw_decoder_refuses_ambiguous_wire(wire):
    from app.adapters.composite_membership_source import strict_composite_response_payload

    with pytest.raises(APIError) as error:
        strict_composite_response_payload(httpx.Response(200, text=wire))
    assert error.value.error_code == "COMPOSITE_SOURCE_SCHEMA_INVALID"


def test_v2_canonical_raw_decoder_preserves_existing_legacy_publication_hash_inputs():
    from app.adapters.composite_membership_source import strict_composite_response_payload

    fixture = producer_fixture()
    for product in (fixture["membership"], fixture["universe"]):
        decoded = strict_composite_response_payload(httpx.Response(200, text=json.dumps(product)))
        assert decoded == product
        assert source_digest(decoded) == product["content_hash"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer_id", "body-selected-issuer"),
        ("verifier_id", "body-selected-verifier"),
        ("artifact_revision", "body-selected-revision"),
        ("artifact_digest", "sha256:" + "a" * 64),
    ],
)
async def test_rehashed_resolver_body_cannot_override_independent_verifier_metadata(monkeypatch, field, value):
    wire = receipt_wire()
    wire["finalization"]["verifications"][0][field] = value
    rehash_lifecycle(wire)
    install_http(monkeypatch, wire=json.dumps(wire))
    install_lifecycle_test_verifier(monkeypatch)
    with pytest.raises(APIError) as error:
        await read_pinned()
    assert error.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_ARTIFACT_MISMATCH"


@pytest.mark.parametrize(
    "change,code",
    [
        ("source-products", "COMPOSITE_ELIGIBILITY_PUBLISHED_SOURCE_PRODUCTS_MISMATCH"),
        ("decisions", "COMPOSITE_ELIGIBILITY_PUBLISHED_DECISION_MISMATCH"),
    ],
)
def test_rehashed_canonical_products_cannot_disagree_with_approval_publication_graph(change, code):
    packet = source_packet()
    wire = receipt_wire()
    if change == "source-products":
        packet["attestation"]["source_products"][1]["source_watermark"] = "other-revision"
    else:
        packet["membership"]["decisions"][0]["status"] = "EXCLUDED"
        packet["membership"]["decisions"][0]["reason_code"] = "SYNTHETIC_TEST_EXCLUSION"
        packet["membership"]["content_hash"] = source_digest(packet["membership"])
        packet["attestation"]["membership_content_hash"] = packet["membership"]["content_hash"]
        wire["finalization"]["evaluation_approval"]["membership_content_hash"] = packet["membership"]["content_hash"]
        wire["membership_content_hash"] = packet["membership"]["content_hash"]
    packet["attestation"]["content_hash"] = source_digest(packet["attestation"])
    wire["finalization"]["evaluation_approval"]["universe_content_hash"] = packet["attestation"]["content_hash"]
    wire["universe_content_hash"] = packet["attestation"]["content_hash"]
    # Keep the exact evaluation binding in the final definition and pinned command after legitimate envelope rehashing.
    rehash_lifecycle(wire)
    from tests.composite_authority_helpers import rehash_definition

    wire["finalization"]["definition"]["source_authority"]["payload"]["eligibility_evaluation_binding"]["digest"] = (
        wire["finalization"]["evaluation_approval"]["content_hash"]
    )
    wire["finalization"]["definition"]["authority_approval"]["claims"]["eligibility_evidence_digest"] = wire[
        "finalization"
    ]["evaluation_approval"]["content_hash"]
    rehash_definition(wire["finalization"]["definition"])
    from app.models.composite_authority import authority_digest

    wire["finalization"]["verifications"][0]["request"]["claims_digest"] = authority_digest(
        wire["finalization"]["definition"]["authority_approval"]["claims"]
    )
    rehash_lifecycle(wire)
    packet["definition"] = deepcopy(wire["finalization"]["definition"])
    with pytest.raises(APIError) as error:
        published_eligibility_from_wire(
            command=command_for_packet(packet),
            tenant_id="synthetic-tenant",
            **packet,
            receipt=SubjectFinalizationReceipt.model_validate(wire),
        )
    assert error.value.error_code == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,code",
    [
        ("unavailable", "COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE"),
        ("request", "COMPOSITE_RECEIPT_VERIFICATION_REQUEST_MISMATCH"),
        ("artifact", "COMPOSITE_RECEIPT_VERIFICATION_ARTIFACT_MISMATCH"),
    ],
)
async def test_materialization_rechecks_independent_verifier_after_source_read(monkeypatch, mutation, code):
    from dataclasses import replace

    from app.services.composite_materialization.authority_policy import admit_authority_profile

    install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)
    source = await read_pinned()
    original = ports.composite_receipt_verifier()

    class ChangedVerifier:
        def verify(self, request):
            result = original.verify(request)
            if mutation == "unavailable":
                return ports.UnavailableCompositeEvidence()
            expectation = result.expectation
            if mutation == "request":
                expectation = replace(expectation, request=request.model_copy(update={"tenant_id": "foreign-tenant"}))
            else:
                expectation = replace(expectation, artifact_revision="unrecognized-revision")
            return replace(result, expectation=expectation)

    monkeypatch.setattr(ports, "composite_receipt_verifier", ChangedVerifier)
    with pytest.raises(APIError) as refused:
        admit_authority_profile(
            source.definition,
            command=command_for_packet(source_packet()),
            tenant_id="synthetic-tenant",
            expected_members=source.attestation.expected_portfolio_ids,
            universe_digest=source.attestation.content_hash,
            published_eligibility=source.published_eligibility,
        )
    assert refused.value.error_code == code
    if mutation == "artifact":
        assert isinstance(refused.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_missing_retained_publication_refuses_materialization_progress_before_outcomes(monkeypatch):
    from app.models.composite_materialization import CompositeMaterializationState
    from app.services.composite_materialization.progress_policy import require_retained_progress

    install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)
    source = await read_pinned()
    source.published_eligibility = None
    with pytest.raises(APIError) as error:
        require_retained_progress(
            command=command_for_packet(source_packet()),
            tenant_id="synthetic-tenant",
            source=source,
            outcomes=[],
            state=CompositeMaterializationState.WAITING,
        )
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_PUBLISHED_CUSTODY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_lifecycle_receipts_do_not_invent_financial_products_or_core_ids(monkeypatch):
    from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource
    from app.models.composite_materialization import CompositeMemberOutcomeState

    install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)
    source = await read_pinned()
    resolver = AuthorityCompositeMemberResultSource(source.definition, admitted_source=source)
    outcome = resolver.read_member(
        command_for_packet(source_packet()),
        None,
        tenant_id="synthetic-tenant",
        membership_snapshot_id=source.membership.content_hash,
        request_headers={},
        member_id="synthetic-member",
    )
    assert outcome.state == CompositeMemberOutcomeState.BLOCKED
    assert outcome.reason_code == "COMPOSITE_PROVIDER_OBSERVATION_REFUSED"
    assert outcome.fact is None
    assert source.definition.source_authority.payload.member_identities[0].identity_kind == "EXTERNAL_MEMBER"


@pytest.mark.asyncio
async def test_typed_body_receipt_without_independent_trust_configuration_is_unavailable(monkeypatch):
    install_http(monkeypatch)
    install_lifecycle_test_verifier(monkeypatch)

    class BodyVerifier:
        def verify(self, request):
            finalization = SubjectFinalizationReceipt.model_validate(receipt_wire()).finalization
            return ports.VerifiedCompositeEvidence(
                finalization.evaluation_approval.proposal.policy_approval.verification
            )

    monkeypatch.setattr(ports, "composite_receipt_verifier", BodyVerifier)
    with pytest.raises(APIError) as error:
        await read_pinned()
    assert error.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE"
