from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services import durable_metadata_bootstrap as schema_service
from app.services.async_result_store import AsyncResultStore
from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.source_correction_store import SourceCorrectionStore
from app.workers.compute_executor_worker import _process_pending_jobs
from main import app


@pytest.fixture
def correction_api_stores(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'source-correction-api.db'}"
    execution_store = ExecutionRegistry(database_url)
    compute_store = ComputeJobStore(database_url)
    result_store = AsyncResultStore(database_url)
    correction_store = SourceCorrectionStore(database_url)
    lineage_store = schema_service.LineageMetadataStore(database_url)
    composite_store = schema_service.CompositeMetadataStore(database_url)
    owned = {
        "execution_registry": execution_store,
        "compute_job_store": compute_store,
        "async_result_store": result_store,
        "source_correction_store": correction_store,
        "lineage_metadata_store": lineage_store,
        "composite_metadata_store": composite_store,
    }
    for name, store in owned.items():
        monkeypatch.setattr(getattr(schema_service, name), "_resolver", lambda store=store: store)
    schema_service.bootstrap_durable_metadata_stores()
    monkeypatch.setattr("app.services.source_correction_service.execution_registry", execution_store)
    monkeypatch.setattr("app.services.source_correction_service.compute_job_store", compute_store)
    monkeypatch.setattr("app.services.source_correction_service.source_correction_store", correction_store)
    try:
        yield execution_store, compute_store, result_store
    finally:
        for store in owned.values():
            store._engine.dispose()


def _retain_stateful_twr(execution_store: ExecutionRegistry):
    calculation_id = uuid4()
    request_payload = {
        "calculation_id": str(calculation_id),
        "portfolio_id": "PORT-API-CORRECTION",
        "input_mode": "stateful",
        "performance_start_date": "2026-01-01",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
    }
    execution_store.create_execution(
        calculation_id=calculation_id,
        tenant_id="bank-a",
        analytics_type="TWR",
        portfolio_id="PORT-API-CORRECTION",
        requested_window={"start_date": "2026-01-01", "end_date": "2026-01-02"},
        request_payload=request_payload,
    )
    execution_store.retain_response_payload(
        calculation_id,
        response_payload={"calculation_id": str(calculation_id), "results": {"SI": {"cumulative_return": 0.10}}},
    )
    execution_store.mark_complete(calculation_id)
    return calculation_id


def _payload():
    return {
        "correction_id": "core-event-api-1",
        "source_product": "portfolio_timeseries",
        "source_revision": "restatement-2",
        "supersedes_source_revision": "restatement-1",
        "target_type": "portfolio",
        "target_id": "PORT-API-CORRECTION",
        "effective_start_date": "2026-01-02",
        "effective_end_date": "2026-01-02",
        "observed_at_utc": "2026-01-03T10:00:00Z",
        "correction_reason": "Corrected closing valuation.",
        "source_authorization": {"issuer": "lotus-core", "evidence_id": "core-event-api-1"},
    }


def test_source_correction_http_paths_preserve_original_and_hide_foreign_tenant(correction_api_stores):
    execution_store, compute_store, _ = correction_api_stores
    original_id = _retain_stateful_twr(execution_store)

    with TestClient(app, headers={"X-Tenant-Id": "bank-a"}) as client:
        accepted = client.post("/performance/source-corrections", json=_payload())
        assert accepted.status_code == 202
        body = accepted.json()
        assert body["state"] == "recalculation_pending"
        assert body["affected_calculation_count"] == 1
        corrected_id = body["impacts"][0]["corrected_calculation_id"]

        replay = client.post("/performance/source-corrections", json=_payload())
        assert replay.status_code == 202
        assert replay.json()["replayed"] is True
        assert replay.json()["impacts"][0]["corrected_calculation_id"] == corrected_id
        assert len(compute_store.list_pending_jobs()) == 1

        original = client.get(f"/performance/executions/{original_id}/retained-result")
        assert original.status_code == 200
        assert original.json()["response"]["results"]["SI"]["cumulative_return"] == 0.10

    with TestClient(app, headers={"X-Tenant-Id": "bank-b"}) as foreign_client:
        assert foreign_client.get("/performance/source-corrections/core-event-api-1").status_code == 404
        assert foreign_client.get(f"/performance/executions/{original_id}/retained-result").status_code == 404


def test_source_correction_http_requires_tenant_authority(correction_api_stores):
    with TestClient(app) as client:
        response = client.post("/performance/source-corrections", json=_payload())

    assert response.status_code == 401
    assert response.json()["error_code"] == "TENANT_AUTHORITY_REQUIRED"


def test_source_correction_http_cancellation(correction_api_stores):
    execution_store, _, _ = correction_api_stores
    _retain_stateful_twr(execution_store)
    with TestClient(app, headers={"X-Tenant-Id": "bank-a"}) as client:
        assert client.post("/performance/source-corrections", json=_payload()).status_code == 202
        cancelled = client.delete("/performance/source-corrections/core-event-api-1")

    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"


def test_source_correction_recalculates_registered_stateful_twr_against_changed_source(
    correction_api_stores,
    monkeypatch,
):
    execution_store, compute_store, result_store = correction_api_stores
    ending_value = {"amount": "110"}

    async def _stateful_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-01-01",
                "observations": [
                    {
                        "valuation_date": "2026-01-02",
                        "beginning_market_value": "100",
                        "ending_market_value": ending_value["amount"],
                        "cash_flows": [],
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _stateful_timeseries,
    )
    for module_name in (
        "app.services.execution_lifecycle_service",
        "app.services.stateful_execution_policy_service",
        "app.services.submission_fencing_service",
        "app.services.twr_calculation_service",
        "app.services.twr_mode_service",
        "app.services.twr_service",
    ):
        monkeypatch.setattr(f"{module_name}.execution_registry", execution_store)
    monkeypatch.setattr(
        "app.services.execution_lifecycle_service.lineage_service.enqueue_capture",
        lambda **kwargs: None,
    )

    twr_request = {
        "portfolio_id": "PORT-API-CORRECTION",
        "performance_start_date": "2026-01-01",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }
    headers = {"X-Tenant-Id": "bank-a"}
    with TestClient(app, headers=headers) as client:
        original_response = client.post("/performance/twr", json=twr_request)
        assert original_response.status_code == 200
        original_body = original_response.json()
        original_id = original_body["calculation_id"]
        original_return = original_body["results_by_period"]["SI"]["portfolio"]["summary"]["period_return"]["base"]
        assert original_return == pytest.approx(10.0)
        retained = execution_store.get_execution(UUID(original_id)).request_payload
        assert retained["source_request"]["input_mode"] == "stateful"
        assert retained["source_request"]["stateful_input"] == {}
        assert retained["resolved_request"]["portfolio"]["valuation_points"][0]["end_mv"] == "110"
        execution_store.mark_complete(UUID(original_id))

        ending_value["amount"] = "108"
        correction_response = client.post("/performance/source-corrections", json=_payload())
        assert correction_response.status_code == 202
        corrected_id = correction_response.json()["impacts"][0]["corrected_calculation_id"]
        corrected_command = compute_store.get_job(UUID(corrected_id)).request_payload
        assert corrected_command["input_mode"] == "stateful"
        assert "resolved_request" not in corrected_command
        assert "source_asset_evidence" not in corrected_command

    assert (
        _process_pending_jobs(
            limit=1,
            job_store=compute_store,
            execution_store=execution_store,
            result_store=result_store,
            settings=get_settings(),
        )
        == 1
    )
    execution_store.mark_complete(UUID(corrected_id))

    with TestClient(app, headers=headers) as client:
        completed = client.get(f"/performance/source-corrections/{_payload()['correction_id']}")
        original = client.get(f"/performance/executions/{original_id}/retained-result")
        corrected = client.get(f"/performance/executions/{corrected_id}/retained-result")

    assert completed.status_code == 200
    assert completed.json()["state"] == "complete"
    assert completed.json()["impacts"][0]["output_changed"] is True
    original_result = original.json()["response"]["results_by_period"]["SI"]["portfolio"]["summary"]
    corrected_result = corrected.json()["response"]["results_by_period"]["SI"]["portfolio"]["summary"]
    assert original_result["period_return"]["base"] == pytest.approx(10.0)
    assert corrected_result["period_return"]["base"] == pytest.approx(8.0)
