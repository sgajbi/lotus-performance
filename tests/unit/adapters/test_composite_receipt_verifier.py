"""Controlled signed authority transport; no genuine issuer or bank approval claim."""

import base64
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from app.adapters.composite_receipt_verification.configuration import (
    ReceiptVerifierConfiguration,
    decode_receipt_verifier_configuration,
)
from app.adapters.composite_receipt_verification.transport import ConfiguredCompositeReceiptVerifier
from app.models.composite_authority import authority_digest
from app.models.composite_eligibility_evidence import VerificationRequest
from app.ports.composite_external_evidence import UnavailableCompositeEvidence, VerifiedCompositeEvidence

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
KEY = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def sign(claims, header=None):
    header = header or {"alg": "EdDSA", "kid": "synthetic.key", "typ": "JWT"}
    segments = [b64(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()) for value in (header, claims)]
    joined = ".".join(segments)
    return joined + "." + b64(KEY.sign(joined.encode()))


def verifier_case():
    binding = {
        "product_name": "CompositeScheduledModelFeeProfile",
        "product_version": "v1",
        "revision": "method.1",
        "digest": "sha256:" + "a" * 64,
    }
    request = VerificationRequest.model_validate(
        {
            "binding": binding,
            "claims_digest": binding["digest"],
            "composite_id": "synthetic.composite",
            "definition_version": "definition.1",
            "effective_from": "2026-01-01",
            "effective_to": "2026-01-31",
            "purpose": "RETURN_METHOD_CALENDAR",
            "source_product": None,
            "subject_content_hash": "sha256:" + "b" * 64,
            "tenant_id": "tenant-a",
        }
    )
    registration = {
        "tenant_id": request.tenant_id,
        "composite_id": request.composite_id,
        "definition_version": request.definition_version,
        "subject_content_hash": request.subject_content_hash,
        "purpose": request.purpose,
        "method_binding": binding,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "verifier_id": "synthetic.method-verifier",
        "issuer_id": "synthetic.receipt-issuer",
        "artifact_revision": "approved-artifact.1",
        "artifact_digest": "sha256:" + "c" * 64,
        "owner_service": "synthetic-verifier",
        "endpoint": "https://verifier.test/verify",
        "issuer_uri": "https://issuer.test",
        "principal_id": "synthetic-verifier",
        "credential_env": "LOTUS_TEST_RECEIPT_CREDENTIAL",
        "jwks": {
            "keys": [
                {
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "kid": "synthetic.key",
                    "alg": "EdDSA",
                    "x": b64(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
                }
            ]
        },
    }
    payload = {
        "product_name": "CompositeEvidenceVerificationReceipt",
        "product_version": "v1",
        "request": request.model_dump(mode="json"),
        "posture": "SYNTHETIC_NON_CERTIFYING",
        **{key: registration[key] for key in ("verifier_id", "issuer_id", "artifact_revision", "artifact_digest")},
    }
    payload["content_hash"] = authority_digest(payload)
    claims = {
        "iss": registration["issuer_uri"],
        "aud": "lotus-performance",
        "sub": registration["principal_id"],
        "tenant_id": request.tenant_id,
        "operation": "composite-evidence.verify",
        "jti": "synthetic.token.1",
        "nbf": int(NOW.timestamp()) - 1,
        "exp": int(NOW.timestamp()) + 120,
        "request_hash": authority_digest(request.model_dump(mode="json")),
        "payload_hash": authority_digest(payload),
    }
    return request, registration, payload, claims


def configured(monkeypatch, *, registration=None, payload=None, claims=None, header=None, response=None):
    request, original_registration, original_payload, original_claims = verifier_case()
    registration = registration or original_registration
    payload = payload or original_payload
    claims = claims or original_claims
    monkeypatch.setenv(registration["credential_env"], "synthetic-outbound-credential")
    calls = []

    def handle(sent):
        calls.append(sent)
        assert sent.headers["Authorization"] == "Bearer synthetic-outbound-credential"
        assert json.loads(sent.content) == request.model_dump(mode="json")
        return response or httpx.Response(
            200,
            json={
                "owner_service": registration["owner_service"],
                "payload": payload,
                "credential": sign(claims, header),
            },
        )

    config = ReceiptVerifierConfiguration.model_validate({"registrations": [registration]})
    return (
        request,
        ConfiguredCompositeReceiptVerifier(config, transport=httpx.MockTransport(handle), now=lambda: NOW),
        calls,
    )


def test_documented_configuration_matches_signed_synthetic_contract(monkeypatch):
    example_path = Path(__file__).resolve().parents[3] / "docs/examples/composite_receipt_verifier.synthetic.json"
    example = ReceiptVerifierConfiguration.model_validate_json(example_path.read_text(encoding="utf-8"))
    request, expected_registration, _, _ = verifier_case()
    assert (
        example.registrations[0]
        == ReceiptVerifierConfiguration.model_validate({"registrations": [expected_registration]}).registrations[0]
    )
    assert example.registration_for(request) is example.registrations[0]
    _, verifier, _ = configured(monkeypatch, registration=example.registrations[0].model_dump(mode="json"))
    assert isinstance(verifier.verify(request), VerifiedCompositeEvidence)


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_invalid_deployment_endpoint_port_refuses_configuration(port):
    _, registration, _, _ = verifier_case()
    registration["endpoint"] = f"https://verifier.test:{port}/verify"
    with pytest.raises(ValueError):
        ReceiptVerifierConfiguration.model_validate({"registrations": [registration]})


@pytest.mark.parametrize("first,last", [("2026-02-01", "2026-01-31"), ("20260101", "2026-01-31")])
def test_registration_requires_canonical_ordered_dates(first, last):
    _, registration, _, _ = verifier_case()
    registration.update(effective_from=first, effective_to=last)
    with pytest.raises(ValueError):
        ReceiptVerifierConfiguration.model_validate({"registrations": [registration]})


@pytest.mark.parametrize(
    "endpoint", ["https://user:password@verifier.test/verify", "https://verifier.test/#fragment", "https:///verify"]
)
def test_registration_refuses_ambiguous_endpoint_identity(endpoint):
    _, registration, _, _ = verifier_case()
    registration["endpoint"] = endpoint
    with pytest.raises(ValueError):
        ReceiptVerifierConfiguration.model_validate({"registrations": [registration]})


@pytest.mark.parametrize("jwks", [{}, {"keys": {}}, {"keys": []}, {"keys": [{}] * 9}])
def test_registration_requires_a_bounded_signing_key_list(jwks):
    _, registration, _, _ = verifier_case()
    registration["jwks"] = jwks
    with pytest.raises(ValueError):
        ReceiptVerifierConfiguration.model_validate({"registrations": [registration]})


def test_configuration_byte_limit_accepts_exact_bound_and_refuses_one_more_byte():
    _, registration, _, _ = verifier_case()
    registration["issuer_uri"] += "/é"
    wire = json.dumps({"registrations": [registration]}, ensure_ascii=False)
    wire += " " * (262144 - len(wire.encode("utf-8")))
    assert len(wire.encode("utf-8")) == 262144 and len(wire) < 262144
    assert decode_receipt_verifier_configuration(wire).registrations[0].issuer_uri.endswith("/é")
    with pytest.raises(ValueError, match="bounded deployment size"):
        decode_receipt_verifier_configuration(wire + " ")


@pytest.mark.parametrize("fault", ["owner", "extra"])
def test_transport_refuses_response_envelope_identity_before_receipt_admission(monkeypatch, fault):
    _, registration, payload, claims = verifier_case()
    envelope = {"owner_service": registration["owner_service"], "payload": payload, "credential": sign(claims)}
    if fault == "owner":
        envelope["owner_service"] = "foreign-owner"
    else:
        envelope["unexpected"] = "caller-selected"
    request, verifier, calls = configured(monkeypatch, response=httpx.Response(200, json=envelope))
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence) and len(calls) == 1


def test_transport_invalid_url_returns_unavailable_evidence(monkeypatch):
    request, verifier, _ = configured(monkeypatch)

    def invalid_url(_request):
        raise httpx.InvalidURL("Controlled invalid deployment endpoint")

    verifier.transport = httpx.MockTransport(invalid_url)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


@pytest.mark.parametrize("credential_id", ["opaque/token+id", "token with spaces"])
def test_every_admitted_opaque_credential_id_can_be_revoked(monkeypatch, credential_id):
    _, registration, _, claims = verifier_case()
    claims["jti"] = credential_id
    request, verifier, _ = configured(monkeypatch, claims=claims)
    assert isinstance(verifier.verify(request), VerifiedCompositeEvidence)
    registration["revoked_credential_ids"] = [credential_id]
    request, verifier, _ = configured(monkeypatch, registration=registration, claims=claims)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


@pytest.mark.parametrize("credential_id", ["", "x" * 129, 1])
def test_revocation_ids_preserve_the_strict_credential_id_bound(credential_id):
    _, registration, _, _ = verifier_case()
    registration["revoked_credential_ids"] = [credential_id]
    with pytest.raises(ValueError):
        ReceiptVerifierConfiguration.model_validate({"registrations": [registration]})


def test_signed_receipt_matches_independently_registered_artifact(monkeypatch):
    request, verifier, calls = configured(monkeypatch)
    result = verifier.verify(request)
    assert isinstance(result, VerifiedCompositeEvidence) and len(calls) == 1
    assert result.expectation.request == request == result.receipt.request
    assert result.expectation.artifact_digest == "sha256:" + "c" * 64
    assert result.receipt.posture == "SYNTHETIC_NON_CERTIFYING"


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "https://foreign.test"),
        ("aud", "lotus-manage"),
        ("aud", ["lotus-performance"]),
        ("sub", "foreign-verifier"),
        ("tenant_id", "foreign-tenant"),
        ("operation", "approve"),
        ("delegated_actor", "maker"),
        ("exp", int(NOW.timestamp())),
        ("exp", True),
        ("exp", int(NOW.timestamp()) + 301),
        ("nbf", int(NOW.timestamp()) + 1),
        ("jti", ""),
        ("request_hash", "sha256:" + "d" * 64),
        ("payload_hash", "sha256:" + "d" * 64),
    ],
)
def test_signed_wrong_claims_do_not_confer_receipt_trust(monkeypatch, field, value):
    _, _, _, claims = verifier_case()
    claims[field] = value
    request, verifier, _ = configured(monkeypatch, claims=claims)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_revision", "different.2"),
        ("artifact_digest", "sha256:" + "d" * 64),
        ("verifier_id", "foreign-verifier"),
        ("issuer_id", "foreign-issuer"),
        ("posture", "QUALIFIED_RECEIPT"),
    ],
)
def test_rehashed_resigned_receipt_cannot_choose_its_expected_artifact(monkeypatch, field, value):
    _, _, payload, claims = verifier_case()
    payload[field] = value
    payload["content_hash"] = authority_digest({key: value for key, value in payload.items() if key != "content_hash"})
    claims["payload_hash"] = authority_digest(payload)
    request, verifier, _ = configured(monkeypatch, payload=payload, claims=claims)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "HS256", "kid": "synthetic.key"},
        {"alg": "EdDSA", "kid": "unknown"},
        {"alg": "EdDSA", "kid": "synthetic.key", "jku": "https://caller.test"},
        {"alg": "EdDSA", "kid": "synthetic.key", "crit": ["anything"]},
    ],
)
def test_unadmitted_signing_headers_refuse(monkeypatch, header):
    request, verifier, _ = configured(monkeypatch, header=header)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "foreign"),
        ("composite_id", "foreign"),
        ("definition_version", "different.2"),
        ("subject_content_hash", "sha256:" + "d" * 64),
        ("effective_to", "2027-01-01"),
    ],
)
def test_unregistered_request_scope_refuses_before_transport(monkeypatch, field, value):
    request, verifier, calls = configured(monkeypatch)
    request = request.model_copy(update={field: value})
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence) and not calls


def test_revoked_and_missing_outbound_credentials_refuse(monkeypatch):
    _, registration, _, _ = verifier_case()
    registration["revoked_credential_ids"] = ["synthetic.token.1"]
    request, verifier, _ = configured(monkeypatch, registration=registration)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)
    monkeypatch.delenv(registration["credential_env"])
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://other.test"}),
        httpx.Response(503),
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, content=b'{"payload":{},"payload":{}}'),
        httpx.Response(200, json={"owner_service": "synthetic-verifier", "payload": {}, "credential": "unsigned"}),
    ],
)
def test_bad_or_unbounded_transport_refuses(monkeypatch, response):
    request, verifier, calls = configured(monkeypatch, response=response)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence) and len(calls) == 1


def test_ambiguous_artifact_configuration_and_unsafe_endpoint_refuse(monkeypatch):
    request, registration, _, _ = verifier_case()
    config = ReceiptVerifierConfiguration.model_validate({"registrations": [registration, deepcopy(registration)]})
    assert config.registration_for(request) is None
    registration["endpoint"] = "http://untrusted.test/verify"
    with pytest.raises(ValidationError):
        ReceiptVerifierConfiguration.model_validate({"registrations": [registration]})


def test_resigned_receipt_for_different_request_is_not_current_approval(monkeypatch):
    _, _, payload, claims = verifier_case()
    payload["request"]["subject_content_hash"] = "sha256:" + "d" * 64
    payload["content_hash"] = authority_digest({key: value for key, value in payload.items() if key != "content_hash"})
    claims["payload_hash"] = authority_digest(payload)
    request, verifier, _ = configured(monkeypatch, payload=payload, claims=claims)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


def test_timeout_and_oversized_headers_are_unavailable(monkeypatch):
    request, verifier, _ = configured(monkeypatch, response=httpx.Response(200, headers={"X-Large": "x" * 16385}))
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)

    def unavailable(_request):
        raise httpx.ReadTimeout("controlled verifier timeout")

    verifier.transport = httpx.MockTransport(unavailable)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


def test_nested_response_within_byte_bound_returns_unavailable(monkeypatch):
    wire = b'{"nested":' + b"[" * 20000 + b"0" + b"]" * 20000 + b"}"
    assert len(wire) <= 65536
    request, verifier, _ = configured(monkeypatch, response=httpx.Response(200, content=wire))
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)


@pytest.mark.parametrize("segment,depth", [("header", 650), ("header", 5000), ("claims", 5500)])
def test_nested_token_segments_within_total_byte_bound_return_unavailable(monkeypatch, segment, depth):
    _, registration, payload, claims = verifier_case()
    header = {"alg": "EdDSA", "kid": "synthetic.key", "typ": "JWT"}
    raw = [json.dumps(value, sort_keys=True, separators=(",", ":")) for value in (header, claims)]
    index = 0 if segment == "header" else 1
    raw[index] = raw[index][:-1] + ',"nested":' + "[" * depth + "0" + "]" * depth + "}"
    segments = [b64(value.encode()) for value in raw]
    joined = ".".join(segments)
    credential = joined + "." + b64(KEY.sign(joined.encode()))
    assert len(credential) <= 16384
    if segment == "header" and depth == 650:
        assert len(segments[0]) <= 2048
    response = httpx.Response(
        200, json={"owner_service": registration["owner_service"], "payload": payload, "credential": credential}
    )
    request, verifier, _ = configured(monkeypatch, response=response)
    assert isinstance(verifier.verify(request), UnavailableCompositeEvidence)
