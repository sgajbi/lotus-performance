"""Real signed read admission and full retained population before arithmetic."""

import base64
import json
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.adapters.composite_principal_credentials import PrincipalGrants
from app.core.config import get_settings
from app.services.composite_metadata_store import get_composite_metadata_store
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_principal_helpers import install_principal_deployment
from tests.integration.test_composite_projection_selection_api import publish_projection, request_for
from tests.unit.services.test_composite_annual_dispersion_service import month_record

PATH = "/performance/composites/twr"
READ = "operations.runtime.read"


def test_twr_openapi_describes_verified_read_authority():
    operation = app.openapi()["paths"][PATH]["post"]
    parameters = {entry["name"]: entry for entry in operation["parameters"]}
    assert parameters["Authorization"]["required"] is True
    assert parameters["X-Tenant-Id"]["required"] is False
    assert "credential" in operation["responses"]["401"]["description"]
    assert "403" in operation["responses"]
    for status in ("401", "403"):
        content = operation["responses"][status]["content"]["application/json"]
        assert content["schema"]["$ref"].endswith("/ErrorDetailResponse")
        assert content["example"]["error_code"] == "PRINCIPAL_ADMISSION_DENIED"
        assert content["example"]["detail"]["denial_class"] == (
            "missing_credential" if status == "401" else "capability_not_granted"
        )
    assert READ in operation["description"]


@pytest.mark.parametrize("race", [False, True])
def test_legacy_explicit_scope_stays_selected_and_refuses_new_selected_members(retained_read, monkeypatch, race):
    _, authority, mint, client, arithmetic, _ = retained_read
    from app.adapters.composite_result_candidate_scope import require_composite_member_scope
    from tests.unit.services.test_composite_calculation_service import _definition, _fact

    store = get_composite_metadata_store()
    store.upsert_definition(_definition(), tenant_id="tenant-a")
    store.upsert_member_return_fact(_fact("P1", "0.02", "100", ending_market_value="102"), tenant_id="tenant-a")
    later = _fact("P2", "0.03", "100", ending_market_value="103", restatement_sequence=2, restatement_version="v2")
    store.upsert_member_return_fact(later, tenant_id="tenant-a")
    authority.portfolios = frozenset({"P1"})

    def authorize(members, *, principal):
        assert members == frozenset({"P1"})
        require_composite_member_scope(members, principal=principal)
        if race:
            store.upsert_member_return_fact(
                later.model_copy(update={"restatement_sequence": 1, "restatement_version": "v1"}), tenant_id="tenant-a"
            )

    monkeypatch.setattr("app.services.composite_calculation_service.require_composite_member_scope", authorize)
    response = client.post(
        PATH,
        headers=headers(mint()),
        json={
            "calculation_id": str(uuid4()),
            "composite_id": _definition().composite_id,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "reporting_currency": "USD",
            "restatement_sequence": 1,
        },
    )
    assert response.status_code == (409 if race else 200), response.text
    if race:
        arithmetic.assert_not_called()
    else:
        assert response.json()["cumulative_return"] == "0.020000000000"
        arithmetic.assert_called_once()


@pytest.fixture
def retained_read(monkeypatch, tmp_path):
    url = "sqlite:///" + (tmp_path / "verified-twr.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    record = month_record(1, count=3)
    publish_projection(url, record)
    authority, mint = install_principal_deployment(monkeypatch, app, tenant="tenant-a", portfolios=("1", "2", "3"))
    authority.capabilities = frozenset({READ})
    import app.services.composite_calculation_service as calculation

    arithmetic = Mock(wraps=calculation.calculate_with_model_fee_context)
    monkeypatch.setattr(calculation, "calculate_with_model_fee_context", arithmetic)
    statements = []
    engine = get_composite_metadata_store()._engine

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    with TestClient(app) as client:
        yield record, authority, mint, client, arithmetic, statements
    event.remove(engine, "before_cursor_execute", observe)


def headers(token):
    return {"Authorization": "Bearer " + token, "X-Correlation-Id": "signed-twr-read"}


@pytest.mark.parametrize("vector", [False, True])
@pytest.mark.parametrize("application_members", [("1", "2", "3"), ("1", "2")])
def test_delegated_read_intersects_application_and_user_scope(retained_read, monkeypatch, vector, application_members):
    record, authority, mint, client, arithmetic, _ = retained_read
    monkeypatch.setattr(
        authority,
        "application_grants",
        lambda *args: PrincipalGrants(frozenset({READ}), frozenset(application_members)),
    )
    response = client.post(
        PATH, json=payload(record, vector), headers=headers(mint(principal_kind="delegated", act="report-test"))
    )
    assert response.status_code == (200 if "3" in application_members else 403), response.text
    assert arithmetic.call_count == (1 if "3" in application_members else 0)


def payload(record, vector):
    return {
        **request_for(record),
        "calculation_id": str(uuid4()),
        **({"materialization_ids": [str(record.command.materialization_id)]} if vector else {}),
    }


@pytest.mark.parametrize("vector", [False, True])
def test_signed_read_only_post_is_stable_and_has_no_financial_writes(retained_read, monkeypatch, vector):
    record, authority, mint, client, arithmetic, statements = retained_read
    audit = []
    monkeypatch.setattr("app.enterprise_readiness.emit_audit_event", lambda **entry: audit.append(entry))
    request = payload(record, vector)
    response = client.post(PATH, json=request, headers=headers(mint(principal_kind="service")))
    assert response.status_code == 200, response.text
    assert response.json()["cumulative_return"] == "0.020000000000"
    retry = client.post(PATH, json=request, headers=headers(mint(principal_kind="service")))
    assert retry.json() == response.json()
    assert arithmetic.call_count == 2
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    allowed = [entry for entry in audit if entry["action"] == "POST " + PATH]
    assert allowed and all(entry["metadata"]["access_mode"] == "privileged_read" for entry in allowed)
    assert all(entry["metadata"]["required_capability"] == READ for entry in allowed)
    assert all(entry["actor_id"] == "verified-test-maker" for entry in allowed)
    capture = client.post(
        "/performance/composites/result-candidates",
        json={"candidate_id": str(uuid4()), "calculation": payload(record, True)},
        headers=headers(mint(principal_kind="service")),
    )
    assert capture.status_code == 403
    assert capture.json()["detail"]["denial_class"] == "capability_not_granted"
    assert arithmetic.call_count == 2


DENIALS = (
    "missing_credential",
    "malformed_credential",
    "expired_credential",
    "wrong_audience",
    "wrong_issuer",
    "unknown_key_id",
    "revoked_principal",
    "present_but_unverified",
    "tenant_not_a_member",
    "capability_not_granted",
    "portfolio_outside_scope",
    "grant_store_unavailable",
    "delegated_capability_not_held_by_user",
)


def denial_credential(case, authority, mint, monkeypatch):
    changes = {
        "expired_credential": {"exp": 0},
        "wrong_audience": {"aud": "lotus-report"},
        "wrong_issuer": {"iss": "https://foreign.test"},
        "revoked_principal": {"jti": "revoked"},
        "delegated_capability_not_held_by_user": {"principal_kind": "delegated", "act": "report-test"},
    }
    token = mint(**changes.get(case, {}))
    if case == "missing_credential":
        return None
    if case == "malformed_credential":
        return "malformed"
    if case == "unknown_key_id":
        segments = token.split(".")
        segments[0] = (
            base64.urlsafe_b64encode(json.dumps({"alg": "EdDSA", "kid": "unknown"}).encode()).rstrip(b"=").decode()
        )
        return ".".join(segments)
    if case == "present_but_unverified":
        deployment = app.state.composite_principal_deployment
        _, foreign_mint = install_principal_deployment(monkeypatch, app, tenant="tenant-a", portfolios=("1", "2", "3"))
        token = foreign_mint()
        monkeypatch.setattr(app.state, "composite_principal_deployment", deployment)
    if case == "revoked_principal":
        authority.revoked_ids.add("revoked")
    if case == "tenant_not_a_member":
        monkeypatch.setattr(authority, "tenant_member", lambda *args: False)
    if case in ("capability_not_granted", "delegated_capability_not_held_by_user"):
        authority.capabilities = frozenset({"operations.runtime.manage"})
        monkeypatch.setattr(
            authority, "application_grants", lambda *args: PrincipalGrants(frozenset({READ}), authority.portfolios)
        )
    if case == "portfolio_outside_scope":
        authority.portfolios = frozenset({"1", "2"})
    if case == "grant_store_unavailable":
        authority.available = False
    return token


@pytest.mark.parametrize("case", DENIALS)
@pytest.mark.parametrize("vector", [False, True])
def test_all_native_denials_refuse_before_arithmetic(retained_read, monkeypatch, case, vector):
    record, authority, mint, client, arithmetic, statements = retained_read
    token = denial_credential(case, authority, mint, monkeypatch)
    assertions = {
        "X-Tenant-Id": "tenant-a",
        "X-Actor-Id": "admin",
        "X-Role": "admin",
        "X-Capabilities": READ,
        "X-Service-Identity": "claimed-report",
    }
    response = client.post(
        PATH, json=payload(record, vector), headers={**assertions, **(headers(token) if token else {})}
    )
    assert response.status_code in (401, 403), response.text
    if case != "portfolio_outside_scope":
        assert response.json()["detail"]["denial_class"] == case
    arithmetic.assert_not_called()
    assert not any("return_value" in sql or "beginning_market_value" in sql for sql in statements)


def test_verified_defaults_and_conflicting_tenant_never_fall_back(retained_read, monkeypatch):
    record, _, mint, client, arithmetic, _ = retained_read
    request = payload(record, True)
    mismatch = client.post(PATH, json=request, headers={**headers(mint()), "X-Tenant-Id": "foreign"})
    assert mismatch.status_code == 403
    for tenant_headers in (
        [("X-Tenant-Id", "a" * 129)],
        [("X-Tenant-Id", "tenant-a"), ("X-Tenant-Id", "tenant-a")],
        [("X-Tenant-Id", "tenant-a"), ("X-Tenant-Id", "foreign")],
    ):
        malformed = client.post(PATH, json=request, headers=[*headers(mint()).items(), *tenant_headers])
        assert malformed.status_code == 400
        assert malformed.json()["error_code"] == "TENANT_AUTHORITY_MALFORMED"
    monkeypatch.delattr(app.state, "composite_principal_deployment")
    unavailable = client.post(PATH, json=request, headers=headers(mint()))
    assert unavailable.status_code == 401
    assert unavailable.json()["detail"]["denial_class"] == "present_but_unverified"
    arithmetic.assert_not_called()


@pytest.mark.parametrize("vector", [False, True])
def test_historical_excluded_member_is_still_required(retained_read, vector):
    record, authority, mint, client, arithmetic, _ = retained_read
    record = month_record(1, count=3, excluded=("3",), corrected=True)
    publish_projection(str(get_composite_metadata_store()._engine.url), record)
    # Even members with no contribution cannot be removed from the attested population.
    authority.portfolios = frozenset({"1", "2"})
    response = client.post(PATH, json=payload(record, vector), headers=headers(mint()))
    assert response.status_code == 403
    arithmetic.assert_not_called()


def test_pinned_fact_selection_does_not_move_to_a_later_correction(retained_read, monkeypatch):
    record, _, mint, client, arithmetic, _ = retained_read
    from app.adapters import composite_result_candidate_scope as scope

    original = scope.require_composite_member_scope
    correction = month_record(1, count=3, corrected=True)

    def authorize_then_publish(members, *, principal):
        original(members, principal=principal)
        publish_projection(str(get_composite_metadata_store()._engine.url), correction)

    monkeypatch.setattr(
        "app.services.composite_calculation_service.require_composite_member_scope", authorize_then_publish
    )
    response = client.post(PATH, json=payload(record, False), headers=headers(mint()))
    assert response.status_code == 200, response.text
    assert response.json()["cumulative_return"] == "0.020000000000"
    arithmetic.assert_called_once()


def test_vector_copies_selected_ids_before_scope_admission(retained_read, monkeypatch):
    record, _, mint, _, _, _ = retained_read
    from app.models.composites import CompositeTWRRequest
    from app.services import composite_calculation_service as calculation

    request = CompositeTWRRequest.model_validate(payload(record, True))
    original = calculation.require_candidate_member_scope
    principal = app.state.composite_principal_deployment
    from datetime import UTC, datetime

    from app.adapters.composite_principal_credentials import resolve_composite_principal

    admitted = resolve_composite_principal(
        mint(),
        trust=principal.trust,
        authority=principal.authority,
        now=datetime.now(UTC),
        required_capabilities=frozenset({READ}),
    )

    def authorize_then_mutate(store, **kwargs):
        original(store, **kwargs)
        request.materialization_ids[:] = [uuid4()]

    monkeypatch.setattr(calculation, "require_candidate_member_scope", authorize_then_mutate)
    result, windows = calculation.calculate_composite_twr_from_materializations(
        tenant_id="tenant-a", request=request, principal=admitted
    )
    assert windows[0].materialization_id == record.command.materialization_id
    assert str(result.cumulative_return) == "0.020000000000"
