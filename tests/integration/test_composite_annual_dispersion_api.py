from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

from app.adapters.composite_annual_dispersion import RetainedAnnualDispersionReceiptReader
from app.adapters.composite_materialization_records import CompositeMaterializationModel
from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.api.dependencies.composite_annual_dispersion import (
    annual_dispersion_openapi_examples,
    get_annual_dispersion_receipt_reader,
)
from app.models.composite_materialization import CompositeMaterializationState
from main import app
from tests.unit.adapters.test_composite_annual_dispersion_adapter import persist_records
from tests.unit.services.test_composite_annual_dispersion_service import (
    MemoryReader,
    annual_request,
    month_record,
    year_records,
)


@pytest.mark.parametrize(
    "endpoint", ["/performance/composites/analytics", "/performance/composites/analytics/comparison"]
)
@pytest.mark.parametrize("mismatch", [None, "order", "membership", "method", "member-regime", "excluded-member-regime"])
def test_registered_annual_vectors_require_shared_fx_authority(
    monkeypatch, tmp_path, endpoint, mismatch, database_url=None
):
    from app.core.config import get_settings
    from scripts.durable_schema_apply import apply_durable_schema
    from tests.composite_annual_fx_helpers import normalized_year_records
    from tests.unit.services.test_composite_annual_comparison_service import pair_request

    records = normalized_year_records(monkeypatch, mismatch=mismatch)
    url = database_url or "sqlite:///" + (tmp_path / "annual-fx.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    persist_records(url, records)
    selected = list(reversed(records)) if mismatch == "order" else records
    payload = annual_request(selected) if endpoint.endswith("analytics") else pair_request(selected, selected)
    previous = app.dependency_overrides.copy()
    store = CompositeMaterializationStore(url)
    app.dependency_overrides[get_annual_dispersion_receipt_reader] = lambda: RetainedAnnualDispersionReceiptReader(
        store
    )
    try:
        with TestClient(app) as client:
            response = client.post(endpoint, json=payload.model_dump(mode="json"), headers={"X-Tenant-Id": "tenant-a"})
        if mismatch in (None, "order", "membership", "excluded-member-regime"):
            assert response.status_code == 200, response.text
            assert response.json()["value"] == ("0.018708286934" if endpoint.endswith("analytics") else "0E-12")
        else:
            assert response.status_code == 422, response.text
            assert response.json()["error_code"] == (
                "COMPOSITE_VECTOR_METHOD_MISMATCH"
                if mismatch == "method"
                else "COMPOSITE_VECTOR_CURRENCY_REGIME_UNAVAILABLE"
            )
            assert "members" not in response.json() and "baseline" not in response.json()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close()


ERROR_EXAMPLE_HEADERS = {
    "X-Tenant-Id": "tenant-a",
    "X-Correlation-Id": "annual-dispersion-example",
    "X-Request-Id": "annual-dispersion-request",
}


def registered_error_response(case, tmp_path):
    records = year_records()
    payload = annual_request(records).model_dump(mode="json")
    headers = ERROR_EXAMPLE_HEADERS.copy()
    store = None
    if case in {"not_found", "retained_evidence"}:
        url = "sqlite:///" + (tmp_path / f"{case}.db").as_posix()
        persist_records(url, records)
        if case == "retained_evidence":
            engine = create_engine(url)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        update(CompositeMaterializationModel)
                        .where(
                            CompositeMaterializationModel.materialization_id
                            == str(records[0].command.materialization_id)
                        )
                        .values(source_json="{}")
                    )
            finally:
                engine.dispose()
        else:
            headers["X-Tenant-Id"] = "tenant-b"
        store = CompositeMaterializationStore(url)
        reader = RetainedAnnualDispersionReceiptReader(store)
    else:
        if case == "incomplete":
            records[0] = replace(records[0], state=CompositeMaterializationState.WAITING)
        elif case == "request_validation":
            payload["materialization_ids"].pop()
        elif case == "domain_admission":
            payload["year"] = 2025
        reader = MemoryReader(records)
    prior_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_annual_dispersion_receipt_reader] = lambda: reader
    try:
        with TestClient(app) as client:
            return client.post("/performance/composites/analytics", json=payload, headers=headers)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior_overrides)
        if store is not None:
            store.close()


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("not_found", 404),
        ("incomplete", 409),
        ("request_validation", 422),
        ("domain_admission", 422),
        ("retained_evidence", 503),
    ],
)
def test_registered_error_examples_match_actual_governed_http_envelopes(case, status, tmp_path):
    response = registered_error_response(case, tmp_path)
    assert response.status_code == status
    assert response.json() == annual_dispersion_openapi_examples()["errors"][case]


def test_registered_api_replays_exact_completed_publications_after_correction_and_reopen(tmp_path):
    url = "sqlite:///" + (tmp_path / "registered-annual.db").as_posix()
    original, corrected = year_records(), year_records(corrected=True)
    persist_records(url, original + corrected)
    prior_overrides = app.dependency_overrides.copy()
    store = CompositeMaterializationStore(url)
    app.dependency_overrides[get_annual_dispersion_receipt_reader] = lambda: RetainedAnnualDispersionReceiptReader(
        store
    )
    try:
        with TestClient(app) as client:
            payload = annual_request(original).model_dump(mode="json")
            old = client.post("/performance/composites/analytics", json=payload, headers={"X-Tenant-Id": "tenant-a"})
            assert old.status_code == 200
            assert old.json() == annual_dispersion_openapi_examples()["response"]
            updated = client.post(
                "/performance/composites/analytics",
                json=annual_request(corrected).model_dump(mode="json"),
                headers={"X-Tenant-Id": "tenant-a"},
            )
            assert updated.status_code == 200
            assert updated.json()["result_fingerprint"] != old.json()["result_fingerprint"]
            assert updated.json()["members"][0]["annual_return"] == "0.07"
            assert (
                client.post(
                    "/performance/composites/analytics", json=payload, headers={"X-Tenant-Id": "tenant-b"}
                ).status_code
                == 404
            )
            store.close()
            store = CompositeMaterializationStore(url)
            replay = client.post("/performance/composites/analytics", json=payload, headers={"X-Tenant-Id": "tenant-a"})
            assert replay.status_code == 200
            assert replay.json() == old.json()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior_overrides)
        store.close()


@pytest.fixture
def annual_client():
    records = year_records()
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_annual_dispersion_receipt_reader] = lambda: MemoryReader(records)
    try:
        with TestClient(app) as client:
            yield client, records
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


def test_registered_annual_api_returns_independent_or11_with_source_limits(annual_client):
    client, records = annual_client
    response = client.post(
        "/performance/composites/analytics",
        json=annual_request(records).model_dump(mode="json"),
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["value"] == "0.018708286934"
    assert data["full_year_member_count"] == data["year_end_member_count"] == 6
    assert data["qualification"] == "RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"
    assert data["publication_state"] == "CALCULATED_ANALYSIS"
    assert len(data["months"]) == 12
    examples = annual_dispersion_openapi_examples()
    assert annual_request(records).model_dump(mode="json") == examples["request"]
    assert data == examples["response"]


def test_registered_annual_api_refuses_untrusted_or_wrong_tenant(annual_client):
    client, records = annual_client
    payload = annual_request(records).model_dump(mode="json")
    assert client.post("/performance/composites/analytics", json=payload).status_code == 401
    response = client.post("/performance/composites/analytics", json=payload, headers={"X-Tenant-Id": "tenant-b"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "COMPOSITE_SOURCE_SCOPE_MISMATCH"


def test_registered_api_missing_month_is_refused_before_calculation(annual_client):
    client, records = annual_client
    payload = annual_request(records).model_dump(mode="json")
    payload["materialization_ids"].pop()
    assert (
        client.post("/performance/composites/analytics", json=payload, headers={"X-Tenant-Id": "tenant-a"}).status_code
        == 422
    )


def test_registered_api_normal_exclusion_retains_computable_five_member_dispersion(annual_client):
    client, records = annual_client
    records[4] = month_record(5, excluded=("6",))
    response = client.post(
        "/performance/composites/analytics",
        json=annual_request(records).model_dump(mode="json"),
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert response.status_code == 200
    assert response.json()["value"] == "0.015811388301"
    assert response.json()["reporting_applicability"] == "REQUIRES_PROFILE_REVIEW"
    assert response.json()["reporting_applicability_reason"] == "APPROVED_REPORTING_PROFILE_NOT_BOUND"
    assert response.json()["reason_codes"] == []


@pytest.mark.parametrize("field", ["reporting_profile", "approved_reporting_profile", "reporting_applicability"])
def test_registered_annual_api_refuses_caller_supplied_reporting_authority(annual_client, field):
    client, records = annual_client
    payload = {**annual_request(records).model_dump(mode="json"), field: "APPROVED"}
    response = client.post("/performance/composites/analytics", json=payload, headers={"X-Tenant-Id": "tenant-a"})
    assert response.status_code == 422
    assert "value" not in response.json() and "members" not in response.json()


@pytest.mark.parametrize("count,value", [(1, None), (5, "0.015811388301"), (6, "0.018708286934")])
def test_registered_annual_api_reports_unbound_profile_separately_from_financial_availability(
    annual_client, count, value
):
    client, records = annual_client
    records[:] = year_records(count=count)
    response = client.post(
        "/performance/composites/analytics",
        json=annual_request(records).model_dump(mode="json"),
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["value"] == value
    assert data["status"] == ("UNAVAILABLE" if count == 1 else "AVAILABLE")
    assert data["reason_codes"] == (["ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS"] if count == 1 else [])
    assert data["full_year_member_count"] == data["year_end_member_count"] == count
    assert data["reporting_applicability"] == "REQUIRES_PROFILE_REVIEW"
    assert data["reporting_applicability_reason"] == "APPROVED_REPORTING_PROFILE_NOT_BOUND"


def test_registered_retained_weighted_analysis_preserves_economics_without_reporting_authority(tmp_path):
    records = year_records(count=3, excluded=("2",), assets={"1": "1", "3": "3"})
    url = "sqlite:///" + (tmp_path / "weighted-unbound.db").as_posix()
    persist_records(url, records)
    previous = app.dependency_overrides.copy()
    store = CompositeMaterializationStore(url)
    app.dependency_overrides[get_annual_dispersion_receipt_reader] = lambda: RetainedAnnualDispersionReceiptReader(
        store
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/performance/composites/analytics",
                json=annual_request(records, method="YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV").model_dump(
                    mode="json"
                ),
                headers={"X-Tenant-Id": "tenant-a"},
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["value"] == "0.008660254038" and data["status"] == "AVAILABLE"
        assert data["reason_codes"] == []
        assert data["full_year_member_count"] == data["year_end_member_count"] == 2
        assert data["reporting_applicability"] == "REQUIRES_PROFILE_REVIEW"
        assert data["reporting_applicability_reason"] == "APPROVED_REPORTING_PROFILE_NOT_BOUND"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close()
