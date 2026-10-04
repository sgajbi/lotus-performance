from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

from app.adapters.composite_annual_dispersion import RetainedAnnualDispersionReceiptReader
from app.adapters.composite_materialization_records import CompositeMaterializationModel
from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.api.dependencies.composite_annual_dispersion import (
    annual_comparison_openapi_examples,
    get_annual_dispersion_receipt_reader,
)
from main import app
from tests.unit.adapters.test_composite_annual_dispersion_adapter import persist_records
from tests.unit.services.test_composite_annual_comparison_service import candidate_records, pair_request
from tests.unit.services.test_composite_annual_dispersion_service import year_records

PATH = "/performance/composites/analytics/comparison"
HEADERS = {
    "X-Tenant-Id": "tenant-a",
    "X-Correlation-Id": "annual-comparison-example",
    "X-Request-Id": "annual-comparison-request",
}


@contextmanager
def registered_client(url):
    previous = app.dependency_overrides.copy()
    store = CompositeMaterializationStore(url)
    app.dependency_overrides[get_annual_dispersion_receipt_reader] = lambda: RetainedAnnualDispersionReceiptReader(
        store
    )
    try:
        with TestClient(app) as client:
            yield client, store
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close()


def registered_comparison_error(case, tmp_path, side="candidate"):
    baseline = year_records()
    candidate = candidate_records(count=5, **({"policy_version": "policy.v2"} if case == "comparison_basis" else {}))
    url = "sqlite:///" + (tmp_path / f"{case}-{side}.db").as_posix()
    persist_records(url, baseline + candidate)
    payload = pair_request(baseline, candidate).model_dump(mode="json")
    selected = baseline if side == "baseline" else candidate
    if case in {"incomplete", "retained_evidence"}:
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                values = {"state": "WAITING"} if case == "incomplete" else {"source_json": "{}"}
                connection.execute(
                    update(CompositeMaterializationModel)
                    .where(
                        CompositeMaterializationModel.materialization_id == str(selected[0].command.materialization_id)
                    )
                    .values(**values)
                )
        finally:
            engine.dispose()
    elif case == "not_found":
        payload[side]["materialization_ids"][0] = "00000000-0000-0000-0000-000000000001"
    elif case == "request_validation":
        payload[side]["materialization_ids"].pop()
    elif case == "domain_admission":
        payload["baseline"]["year"] = payload["candidate"]["year"] = 2025
    with registered_client(url) as (client, _):
        return client.post(PATH, json=payload, headers=HEADERS)


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("not_found", 404),
        ("incomplete", 409),
        ("request_validation", 422),
        ("domain_admission", 422),
        ("comparison_basis", 422),
        ("retained_evidence", 503),
    ],
)
@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_either_side_refuses_partial_or_incompatible_evidence(case, status, side, tmp_path):
    response = registered_comparison_error(case, tmp_path, side)
    assert response.status_code == status, response.text
    assert "baseline" not in response.json() and "candidate" not in response.json()
    if side == "candidate":
        assert response.json() == annual_comparison_openapi_examples()["errors"][case]


def test_real_registered_positive_population_delta_reverse_tenant_and_reopen_replay(tmp_path):
    baseline, candidate = year_records(), candidate_records(count=7, excluded=("6",))
    url = "sqlite:///" + (tmp_path / "positive.db").as_posix()
    persist_records(url, baseline)
    payload = pair_request(baseline, baseline).model_dump(mode="json")
    with registered_client(url) as (client, _):
        old = client.post(PATH, json=payload, headers=HEADERS)
        assert old.status_code == 200
        assert old.json()["value"] == "0E-12"
    persist_records(url, candidate)
    with registered_client(url) as (client, _):
        response = client.post(PATH, json=pair_request(baseline, candidate).model_dump(mode="json"), headers=HEADERS)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["baseline"]["value"] == "0.018708286934"
        assert data["candidate"]["value"] == "0.021602468995"
        assert data["value"] == "0.002894182061"
        assert data["full_year_members_added"] == ["7"] and data["full_year_members_removed"] == ["6"]
        reverse = client.post(PATH, json=pair_request(candidate, baseline).model_dump(mode="json"), headers=HEADERS)
        assert reverse.status_code == 200 and reverse.json()["value"] == "-0.002894182061"
        assert client.post(PATH, json=payload, headers={"X-Tenant-Id": "tenant-b"}).status_code == 404
        assert client.post(PATH, json=payload).status_code == 401
        assert client.post(PATH, json=payload, headers=HEADERS).json() == old.json()


def test_packaged_full_success_matches_real_reopened_corrected_vector(tmp_path):
    baseline, candidate = year_records(), year_records(corrected=True)
    url = "sqlite:///" + (tmp_path / "example.db").as_posix()
    persist_records(url, baseline + candidate)
    examples = annual_comparison_openapi_examples()
    assert examples["request"] == pair_request(baseline, candidate).model_dump(mode="json")
    with registered_client(url) as (client, _):
        response = client.post(PATH, json=examples["request"], headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == examples["response"]
    with registered_client(url) as (client, _):
        assert client.post(PATH, json=examples["request"], headers=HEADERS).json() == examples["response"]
