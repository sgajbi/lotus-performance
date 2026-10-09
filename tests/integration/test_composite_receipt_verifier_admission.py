"""Existing receipt port/finalization admission with controlled signed responses."""

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.composite_authority import authority_digest
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization.authority_policy import _admit_lifecycle_verification
from app.services.composite_materialization.model_fee_source_admission import _require_published_method_approval
from app.workers.compute_executor_worker import process_pending_jobs
from core.errors import APIError
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_authority_helpers import command_for_packet
from tests.composite_eligibility_helpers import install_lifecycle_test_verifier, source_packet
from tests.unit.adapters.test_composite_receipt_verifier import configured, sign, verifier_case
from tests.unit.adapters.test_manage_composite_eligibility_evidence import install_http
from tests.unit.services.test_composite_model_fee_lifecycle_admission import lifecycle_case


def test_configured_port_preserves_default_legacy_refusal_and_exact_retained_receipt(monkeypatch):
    request, verifier, _ = configured(monkeypatch)
    monkeypatch.setattr(ports, "composite_receipt_verifier", lambda: verifier)
    result = ports.composite_receipt_verifier().verify(request)
    assert isinstance(result, ports.VerifiedCompositeEvidence)
    _admit_lifecycle_verification(result.receipt, result)
    assert isinstance(ports.method_approval_verifier(), ports.UnavailableApprovalVerification)
    _, registration, payload, claims = verifier_case()
    registration["artifact_revision"] = payload["artifact_revision"] = "later.2"
    payload["content_hash"] = authority_digest({key: value for key, value in payload.items() if key != "content_hash"})
    claims["payload_hash"] = authority_digest(payload)
    _, later, _ = configured(monkeypatch, registration=registration, payload=payload, claims=claims)
    replacement = later.verify(request)
    assert isinstance(replacement, ports.VerifiedCompositeEvidence)
    with pytest.raises(APIError) as error:
        _admit_lifecycle_verification(result.receipt, replacement)
    assert error.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_ARTIFACT_MISMATCH"


def test_factory_only_uses_deployment_configuration_and_invalid_wire_fails_closed(monkeypatch):
    request, registration, _, _ = verifier_case()
    settings = get_settings()
    monkeypatch.setattr(settings, "COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON", None)
    assert isinstance(ports.composite_receipt_verifier().verify(request), ports.UnavailableCompositeEvidence)
    monkeypatch.setattr(
        settings, "COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON", json.dumps({"registrations": [registration]})
    )
    assert type(ports.composite_receipt_verifier()).__name__ == "ConfiguredCompositeReceiptVerifier"
    monkeypatch.setattr(settings, "COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON", '{"registrations":[],"registrations":[]}')
    assert isinstance(ports.composite_receipt_verifier().verify(request), ports.UnavailableCompositeEvidence)


def test_nested_deployment_configuration_within_byte_bound_is_unavailable(monkeypatch):
    request, _, _, _ = verifier_case()
    wire = '{"registrations":' + "[" * 20000 + "0" + "]" * 20000 + "}"
    assert len(wire.encode("utf-8")) <= 262144
    monkeypatch.setattr(get_settings(), "COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON", wire)
    assert isinstance(ports.composite_receipt_verifier().verify(request), ports.UnavailableCompositeEvidence)


def test_real_http_configured_factory_exact_signed_receipt_and_owned_shutdown(monkeypatch):
    request, registration, payload, claims = verifier_case()
    now = int(datetime.now(UTC).timestamp())
    claims.update(nbf=now - 1, exp=now + 120)
    response = json.dumps(
        {"owner_service": registration["owner_service"], "payload": payload, "credential": sign(claims)}
    ).encode()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    registration.update(endpoint=f"http://127.0.0.1:{server.server_port}/verify", synthetic_loopback=True)
    monkeypatch.setenv(registration["credential_env"], "synthetic-outbound-credential")
    monkeypatch.setattr(
        get_settings(), "COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON", json.dumps({"registrations": [registration]})
    )
    thread.start()
    try:
        result = ports.composite_receipt_verifier().verify(request)
        assert isinstance(result, ports.VerifiedCompositeEvidence)
        _admit_lifecycle_verification(result.receipt, result)
        assert received == [("/verify", "Bearer synthetic-outbound-credential", request.model_dump(mode="json"))]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


def configured_lifecycle_method(monkeypatch, *, registered_subject=True):
    source, model_request, receipt = lifecycle_case()
    request = receipt.request
    _, registration, _, claims = verifier_case()
    for field in ("tenant_id", "composite_id", "definition_version", "subject_content_hash", "purpose"):
        registration[field] = getattr(request, field)
    registration.update(
        method_binding=request.binding.model_dump(mode="json"),
        effective_from=request.effective_from,
        effective_to=request.effective_to,
        **{
            field: getattr(receipt, field)
            for field in ("verifier_id", "issuer_id", "artifact_revision", "artifact_digest")
        },
    )
    if not registered_subject:
        registration["subject_content_hash"] = "sha256:" + "f" * 64
    payload = receipt.model_dump(mode="json")
    now = int(datetime.now(UTC).timestamp())
    claims.update(
        tenant_id=request.tenant_id,
        request_hash=authority_digest(request.model_dump(mode="json")),
        payload_hash=authority_digest(payload),
        nbf=now - 1,
        exp=now + 120,
    )
    calls = []

    def respond(sent):
        calls.append(json.loads(sent.content))
        return httpx.Response(
            200, json={"owner_service": registration["owner_service"], "payload": payload, "credential": sign(claims)}
        )

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client_type(**{**kwargs, "transport": httpx.MockTransport(respond)})
    )
    monkeypatch.setenv(registration["credential_env"], "synthetic-outbound-credential")
    monkeypatch.setattr(
        get_settings(), "COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON", json.dumps({"registrations": [registration]})
    )
    return source, model_request, receipt, calls


@pytest.mark.parametrize("registered_subject", [True, False])
def test_configured_factory_drives_existing_published_model_fee_admission(monkeypatch, registered_subject):
    source, model_request, receipt, calls = configured_lifecycle_method(
        monkeypatch, registered_subject=registered_subject
    )
    request = receipt.request
    if registered_subject:
        _require_published_method_approval(source, model_request)
        assert calls == [request.model_dump(mode="json")]
    else:
        with pytest.raises(APIError) as error:
            _require_published_method_approval(source, model_request)
        assert error.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"
        assert calls == []


def test_registered_worker_refuses_missing_peer_verifiers_despite_valid_configured_method(monkeypatch, tmp_path):
    database_url = "sqlite:///" + (tmp_path / "method-only-lifecycle.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", database_url)
    assert apply_durable_schema(database_url=database_url).status == "passed"
    production_factory = ports.composite_receipt_verifier
    # Only provider registration is independently fixed here; other receipt purposes remain unavailable.
    install_lifecycle_test_verifier(monkeypatch)
    verification_requests = []

    class ObservedConfiguredVerifier:
        def verify(self, request):
            verification_requests.append(request)
            return production_factory().verify(request)

    monkeypatch.setattr(ports, "composite_receipt_verifier", ObservedConfiguredVerifier)
    source, model_request, receipt, method_calls = configured_lifecycle_method(monkeypatch)
    _require_published_method_approval(source, model_request)
    assert method_calls == [receipt.request.model_dump(mode="json")]
    upstream_calls = install_http(monkeypatch)
    packet = source_packet()
    headers = {"X-Tenant-Id": "synthetic-tenant", "X-Actor-Id": "reader", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        command = command_for_packet(packet)
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=1) == 1
        result = client.get(accepted.json()["result_path"])
        assert result.status_code == 200, result.text
        assert result.json()["state"] == "BLOCKED" and result.json()["ready_count"] == 0
        assert result.json()["reason_code"] == "COMPOSITE_SOURCE_REFUSED"
    assert method_calls == [receipt.request.model_dump(mode="json")]
    assert verification_requests == [
        receipt.request,
        source.published_eligibility.receipt.finalization.evaluation_approval.proposal.policy_approval.verification.request,
    ]
    assert [method for method, _ in upstream_calls] == ["GET", "GET", "GET", "POST"]
