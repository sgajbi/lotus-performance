"""Registered calculation and original capture under actual signature admission."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.core.config import get_settings
from app.observability import tenant_id_var
from app.services.async_result_store import get_async_result_store
from app.services.composite_metadata_store import get_composite_metadata_store
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_annual_fx_helpers import normalized_month_record
from tests.composite_currency_normalization_helpers import synthetic_fx_verification
from tests.composite_principal_helpers import install_principal_deployment
from tests.integration.test_composite_projection_selection_api import publish_projection, request_for
from tests.unit.services.test_composite_annual_dispersion_service import month_record

PATH = "/performance/composites/result-candidates"
BUILD = "c100c885752c86b8d950d7970c99a8d223e6376a"


def test_concurrent_verified_tenants_keep_request_context_and_audit_isolated(monkeypatch, tmp_path, caplog):
    url = f"sqlite:///{tmp_path / 'concurrent-tenants.db'}"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    authority, mint = install_principal_deployment(monkeypatch, app, tenant="tenant-a", portfolios=["member-a"])
    monkeypatch.setattr(authority, "tenant_member", lambda subject, tenant: subject == "maker-" + tenant)
    store = get_composite_metadata_store()
    original_read = store.get_result_candidate
    overlap = Barrier(2)
    observed = []

    def overlapping_read(**arguments):
        tenant = arguments["tenant_id"]
        observed.append((tenant, arguments["principal"].subject, tenant_id_var.get()))
        overlap.wait(timeout=10)
        assert tenant_id_var.get() == tenant
        return original_read(**arguments)

    monkeypatch.setattr(store, "get_result_candidate", overlapping_read)
    outside_context = tenant_id_var.get()
    with TestClient(app) as client, caplog.at_level("INFO", logger="enterprise_readiness"):

        def read(tenant):
            response = client.get(
                PATH + "/" + str(uuid4()),
                headers={
                    "Authorization": "Bearer " + mint(tenant=tenant, sub="maker-" + tenant),
                    "X-Tenant-Id": "forged-tenant",
                    "X-Actor-Id": "forged-maker",
                },
            )
            assert response.status_code == 404, response.text

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(read, tenant) for tenant in ("tenant-a", "tenant-b")]
            for future in futures:
                future.result(timeout=15)
    assert sorted(observed) == [
        ("tenant-a", "maker-tenant-a", "tenant-a"),
        ("tenant-b", "maker-tenant-b", "tenant-b"),
    ]
    audits = [record.audit for record in caplog.records if hasattr(record, "audit")]
    assert {
        (audit["tenant_id"], audit["actor_id"]) for audit in audits if audit["action"].startswith("GET " + PATH)
    } == {("tenant-a", "maker-tenant-a"), ("tenant-b", "maker-tenant-b")}
    assert tenant_id_var.get() == outside_context


def test_registered_candidate_original_retry_retention_audit_and_current_scope(
    monkeypatch, tmp_path, caplog, database_url=None
):
    url = database_url or f"sqlite:///{tmp_path / 'registered-candidate.db'}"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    monkeypatch.setattr(get_settings(), "APP_GIT_COMMIT_SHA", BUILD)
    assert apply_durable_schema(database_url=url).status == "passed"
    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
        lambda: SimpleNamespace(verify=synthetic_fx_verification),
    )
    record = normalized_month_record(month_record(1))
    publish_projection(url, record)
    members = record.source.attestation.expected_portfolio_ids
    authority, mint = install_principal_deployment(monkeypatch, app, tenant="tenant-a", portfolios=members)
    calculation = {
        **request_for(record),
        "calculation_id": str(uuid4()),
        "materialization_ids": [str(record.command.materialization_id)],
    }
    body = {"candidate_id": str(uuid4()), "calculation": calculation}
    store, results = get_composite_metadata_store(), get_async_result_store()

    def counts():
        with store._engine.connect() as connection:
            return tuple(
                connection.scalar(text(f"SELECT count(*) FROM {table}"))
                for table in ("analytics_async_result", "composite_result_candidates")
            )

    with TestClient(app) as client:
        legacy = client.post("/performance/composites/twr", json=calculation, headers={"X-Tenant-Id": "tenant-a"})
        assert legacy.status_code == 200, legacy.text
        assert counts() == (0, 0)
        headers = [
            ("Authorization", "Bearer " + mint()),
            ("X-Tenant-Id", "forged-tenant"),
            ("X-Tenant-Id", "another-forged"),
            ("X-Actor-Id", "forged-maker"),
            ("X-Role", "FORGED_ADMIN"),
            ("X-Capabilities", "all"),
        ]
        with caplog.at_level("INFO", logger="enterprise_readiness"):
            captured = client.post(PATH, json=body, headers=headers)
        assert captured.status_code == 200, captured.text
        original = captured.json()
        assert original["response"] == legacy.json()
        assert original["captured_by"] == "verified-test-maker" and original["tenant_id"] == "tenant-a"
        audits = [
            record.audit
            for record in caplog.records
            if hasattr(record, "audit") and record.audit["action"] == "POST " + PATH
        ]
        assert audits and audits[-1]["actor_id"] == "verified-test-maker" and audits[-1]["tenant_id"] == "tenant-a"
        body["candidate_id"], body["calculation"]["calculation_id"] = str(uuid4()), str(uuid4())
        retried = client.post(PATH, json=body, headers=headers)
        assert retried.status_code == 200, retried.text
        assert retried.json() == original
        assert counts() == (1, 1)
        assert results.prune_results_older_than(datetime.now(UTC) + timedelta(days=1)) == 0
        monkeypatch.setattr(get_settings(), "APP_GIT_COMMIT_SHA", "f" * 40)
        monkeypatch.setattr(get_settings(), "CALCULATION_ENGINE_VERSION", "future-engine")
        historical = client.get(PATH + "/" + original["candidate_id"], headers={"Authorization": "Bearer " + mint()})
        assert historical.status_code == 200 and historical.json() == original
        authority.portfolios = frozenset()
        statements = []

        def observe(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(store._engine, "before_cursor_execute", observe)
        try:
            denied = client.get(PATH + "/" + original["candidate_id"], headers={"Authorization": "Bearer " + mint()})
            assert denied.status_code == 403, denied.text
            assert not any("FROM ANALYTICS_ASYNC_RESULT" in statement.upper() for statement in statements)
        finally:
            event.remove(store._engine, "before_cursor_execute", observe)
    assert tenant_id_var.get() != "tenant-a"


@pytest.mark.parametrize(
    "denial",
    [
        "missing",
        "unverified",
        "wrong_audience",
        "grant_store",
        "capability",
        "tenant",
        "duplicate_authorization",
        "portfolio",
    ],
)
def test_registered_candidate_denial_reads_no_financial_result_or_fact(monkeypatch, tmp_path, denial):
    url = f"sqlite:///{tmp_path / 'denial.db'}"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    monkeypatch.setattr(get_settings(), "APP_GIT_COMMIT_SHA", BUILD)
    assert apply_durable_schema(database_url=url).status == "passed"
    record = month_record(1)
    publish_projection(url, record)
    authority, mint = install_principal_deployment(
        monkeypatch, app, tenant="tenant-a", portfolios=record.source.attestation.expected_portfolio_ids
    )
    credential = (
        mint(aud="lotus-gateway")
        if denial == "wrong_audience"
        else mint(tenant="other-tenant")
        if denial == "tenant"
        else mint()
    )
    if denial == "grant_store":
        authority.available = False
    if denial == "capability":
        authority.capabilities = frozenset()
    if denial == "portfolio":
        authority.portfolios = frozenset()
    if denial == "unverified":
        credential = credential[:-5] + "AAAAA"
    headers = [
        ("Authorization", "Bearer " + credential),
        ("X-Tenant-Id", "tenant-a"),
        ("X-Actor-Id", "forged"),
        ("X-Role", "admin"),
        ("X-Capabilities", "operations.runtime.manage"),
    ]
    if denial == "missing":
        headers = headers[1:]
    if denial == "duplicate_authorization":
        headers.insert(0, ("Authorization", "Bearer " + mint()))
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(get_composite_metadata_store()._engine, "before_cursor_execute", observe)
    try:
        with TestClient(app) as client:
            statements.clear()  # startup catalog verification is separate
            result = client.post(
                PATH,
                json={
                    "candidate_id": str(uuid4()),
                    "calculation": {
                        **request_for(record),
                        "materialization_ids": [str(record.command.materialization_id)],
                    },
                },
                headers=headers,
            )
        assert result.status_code in (401, 403), result.text
        assert not any(
            "analytics_async_result" in statement or "composite_member_return_facts" in statement
            for statement in statements
        )
        assert not any(
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements
        )
    finally:
        event.remove(get_composite_metadata_store()._engine, "before_cursor_execute", observe)
