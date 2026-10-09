"""Registered ASGI routes, actual signed principal admission and enterprise audit."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import composite_result_authority as dependencies
from app.core.config import get_settings
from app.models.composite_result_authority import AuthorityProposalResponse
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_principal_helpers import install_principal_deployment
from tests.composite_result_authority_helpers import AuthorityFixture

PATH = "/performance/composites/result-authorities"


@pytest.fixture
def authority_http(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "http-authority.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    fixture = AuthorityFixture(url, monkeypatch)
    _, mint = install_principal_deployment(monkeypatch, app, tenant="tenant-a", portfolios=["A", "B", "C"])
    monkeypatch.setattr(dependencies, "get_composite_metadata_store", lambda: fixture.store)
    monkeypatch.setattr(dependencies, "get_async_result_store", lambda: fixture.results)
    monkeypatch.delattr(app.state, "composite_financial_authority", raising=False)
    try:
        with TestClient(app) as client:
            yield fixture, client, mint
    finally:
        fixture.close()


def headers(mint, subject):
    return {
        "Authorization": "Bearer " + mint(sub=subject),
        "X-Tenant-Id": "forged-tenant",
        "X-Actor-Id": "forged-actor",
    }


def propose(fixture, client, mint):
    original = fixture.candidate()
    response = client.post(
        PATH + "/proposals",
        headers=headers(mint, "maker"),
        json={
            "proposal_id": str(uuid4()),
            "action": "SELECT_INITIAL",
            "targets": [{"candidate_id": original["candidate_id"], "expected_revision": 0}],
            "reason": "Synthetic registered HTTP workflow",
            "evidence_refs": ["synthetic-http"],
        },
    )
    fixture.record("http_proposal_response", {"status": response.status_code, "body": response.json()})
    assert response.status_code == 200, response.text
    return original, AuthorityProposalResponse.model_validate(response.json())


def test_registered_authority_denies_missing_and_wrong_audience_credentials(authority_http, caplog):
    fixture, client, mint = authority_http
    before = fixture.counts()
    with caplog.at_level("INFO", logger="http.access"):
        for request_headers in ({}, {"Authorization": "Bearer " + mint(aud="wrong-audience")}):
            response = client.post(PATH + "/proposals", headers=request_headers, json={})
            fixture.record("http_principal_denial", {"status": response.status_code, "body": response.json()})
            assert response.status_code == 401
            assert response.json()["error_code"] == "PRINCIPAL_ADMISSION_DENIED"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Request-Id"] and response.headers["X-Trace-Id"]
    assert fixture.counts() == before
    assert any(record.name == "http.access" for record in caplog.records)


def test_registered_approval_default_unavailable_preserves_proposal_without_selection(authority_http):
    fixture, client, mint = authority_http
    _, proposal = propose(fixture, client, mint)
    request = fixture.financial_request(proposal)
    before = fixture.counts()
    response = client.post(
        PATH + "/proposals/" + str(proposal.proposal_id) + "/approvals",
        headers=headers(mint, "checker"),
        json=request.model_dump(mode="json"),
    )
    fixture.record("http_unavailable_response", {"status": response.status_code, "body": response.json()})
    assert response.status_code == 503
    assert fixture.counts() == before


def test_registered_synthetic_workflow_returns_original_and_verified_audit_actor(authority_http, monkeypatch, caplog):
    fixture, client, mint = authority_http
    monkeypatch.setattr(app.state, "composite_financial_authority", fixture.verifier, raising=False)
    with caplog.at_level("INFO", logger="enterprise_readiness"):
        original, proposal = propose(fixture, client, mint)
        bad_request = fixture.financial_request(proposal, claim_changes={"purpose": "SOURCE_RECEIPT_ONLY"})
        before = fixture.counts()
        refusal = client.post(
            PATH + "/proposals/" + str(proposal.proposal_id) + "/approvals",
            headers=headers(mint, "checker"),
            json=bad_request.model_dump(mode="json"),
        )
        assert refusal.status_code == 403 and fixture.counts() == before
        request = fixture.financial_request(proposal)
        approved = client.post(
            PATH + "/proposals/" + str(proposal.proposal_id) + "/approvals",
            headers=headers(mint, "checker"),
            json=request.model_dump(mode="json"),
        )
        fixture.record("http_approval_response", {"status": approved.status_code, "body": approved.json()})
        assert approved.status_code == 200, approved.text
        apply_request = {"decision_id": str(uuid4()), "approval_id": str(request.approval_id)}
        decision = client.post(
            PATH + "/proposals/" + str(proposal.proposal_id) + "/apply",
            headers=headers(mint, "checker"),
            json=apply_request,
        )
        fixture.record("http_decision_response", {"status": decision.status_code, "body": decision.json()})
        assert decision.status_code == 200, decision.text
        scope = decision.json()["selections"][0]["scope"]["scope_id"]
        read = client.get(PATH + "/" + scope, headers=headers(mint, "checker"))
        fixture.record("http_read_response", {"status": read.status_code, "body": read.json()})
        assert read.status_code == 200 and read.json()["original"] == original
        assert read.json()["institution_activation"] == "UNAVAILABLE"
        retry = client.post(
            PATH + "/proposals/" + str(proposal.proposal_id) + "/apply",
            headers=headers(mint, "checker"),
            json=apply_request,
        )
        assert retry.json() == decision.json()
    audits = [record.audit for record in caplog.records if hasattr(record, "audit")]
    relevant = [audit for audit in audits if audit["action"].startswith(("POST " + PATH, "GET " + PATH))]
    assert relevant and all(audit["tenant_id"] == "tenant-a" for audit in relevant)
    assert {audit["actor_id"] for audit in relevant} == {"maker", "checker"}
