"""Shared durable proof driven through public routes and the real Core adapter."""

import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
from fastapi.testclient import TestClient

import main
from app.core.config import get_settings
from app.services import durable_metadata_bootstrap, http_resilience
from app.workers import compute_executor_worker
from tests.durable_schema_startup_helpers import resolved_runtime_stores

SOURCE_REFUSAL_CODE = "QCP_ANALYTICS_INSUFFICIENT_DATA"
UNTRUSTED_MARKER = "UPSTREAM_SECRET_SQL_ACCOUNT_MARKER"


def core_source_refusal():
    # Match the captured Core contract; diagnostics deliberately hostile.
    return {
        "type": "https://lotus-platform.dev/problems/query-control-plane/qcp_analytics_insufficient_data",
        "title": UNTRUSTED_MARKER,
        "status": 422,
        "detail": UNTRUSTED_MARKER,
        "instance": UNTRUSTED_MARKER,
        "error_code": SOURCE_REFUSAL_CODE,
        "correlation_id": UNTRUSTED_MARKER,
        "metadata": {"analytics_error_code": "INSUFFICIENT_DATA"},
    }


def install_core_transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(*, timeout_seconds):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout_seconds) as connection:
            yield connection

    monkeypatch.setattr(http_resilience, "_request_client", client)


def assert_durable_source_refusal(database_url, monkeypatch, tmp_path, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS", 1)
    monkeypatch.setattr(settings, "LINEAGE_STORAGE_PATH", str(tmp_path / "lineage"))
    monkeypatch.setattr(settings, "CORE_MAX_RETRIES", 2)
    outbound = []
    repaired = False

    def core(request):
        assert request.url.path == "/integration/portfolios/SOURCE_REFUSAL_TEST/analytics/portfolio-timeseries"
        assert request.headers["X-Tenant-Id"] == "tenant-refusal-owner"
        outbound.append(json.loads(request.content))
        if not repaired:
            return httpx.Response(422, json=core_source_refusal())
        return httpx.Response(
            200,
            json={
                "portfolio_open_date": "2025-01-01",
                "portfolio_currency": "USD",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": 100, "ending_market_value": 101},
                    {"valuation_date": "2025-01-02", "beginning_market_value": 101, "ending_market_value": 102},
                ],
            },
        )

    install_core_transport(monkeypatch, core)
    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "SOURCE_REFUSAL_TEST",
        "input_mode": "stateful",
        "stateful_input": {},
        "performance_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "periods": [{"period": "SI", "frequencies": ["daily"]}],
    }
    headers = {"X-Tenant-Id": "tenant-refusal-owner"}
    with resolved_runtime_stores(database_url, monkeypatch):
        durable_metadata_bootstrap.bootstrap_durable_metadata_stores()
        with TestClient(main.app) as client:
            assert client.post("/performance/workspace-summary", json=payload).status_code == 401
            assert outbound == []
            accepted = client.post("/performance/workspace-summary", headers=headers, json=payload)
            assert accepted.status_code == 202, accepted.text
            calculation_id = accepted.json()["calculation_id"]
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 1
            assert len(outbound) == 1
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 0
            assert len(outbound) == 1

    # Independent adapters and API startup reload committed state, not ORM cache.
    with resolved_runtime_stores(database_url, monkeypatch) as restarted:
        durable_metadata_bootstrap.verify_durable_metadata_stores()
        with TestClient(main.app) as client:
            result_url = f"/performance/workspace-summary/results/{calculation_id}"
            execution_url = f"/performance/executions/{calculation_id}"
            owner = {"X-Tenant-Id": "tenant-refusal-owner"}
            for url in (result_url, execution_url):
                denied = client.get(url, headers={"X-Tenant-Id": "tenant-other"})
                assert denied.status_code == 403, denied.text
                assert SOURCE_REFUSAL_CODE not in denied.text
            result = client.get(result_url, headers=owner)
            assert result.status_code == 422, result.text
            assert result.json()["error_code"] == SOURCE_REFUSAL_CODE
            assert result.json()["retryable"] is False
            evidence = client.get(execution_url, headers=owner)
            assert evidence.status_code == 200, evidence.text
            body = evidence.json()
            assert body["status"] == "failed"
            assert body["failure"]["error_code"] == SOURCE_REFUSAL_CODE
            assert body["failure"]["retryable"] is False
            assert body["compute_job"]["job_status"] == "failed"
            assert body["compute_job"]["attempt_count"] == 1
            assert body["async_result"]["result_status"] == "failed"
            assert body["async_result"]["failure"] == body["failure"]
            assert body["requested_window"]["report_end_date"] == "2025-01-02"
            snapshots = body["upstream_snapshots"]
            assert len(snapshots) == 1
            assert snapshots[0]["source_identifier"] == payload["portfolio_id"]
            assert snapshots[0]["as_of_date"] == "2025-01-02"
            assert snapshots[0]["retrieval_status"] == "422"
            assert len(snapshots[0]["request_fingerprint"]) == 64
            assert len(snapshots[0]["response_fingerprint"]) == 64
            assert UNTRUSTED_MARKER not in result.text + evidence.text + caplog.text
            failed_record = restarted["async_result_store"].get_result(UUID(calculation_id))
            assert failed_record.response_payload is None
            assert UNTRUSTED_MARKER not in failed_record.failure.to_json()
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 0
            replay = client.post("/performance/workspace-summary", headers=headers, json=payload)
            assert replay.status_code == 202, replay.text
            assert replay.json()["calculation_id"] == calculation_id
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 0
            assert len(outbound) == 1

            repaired = True
            corrected = client.post(
                "/performance/workspace-summary",
                headers=owner,
                json=payload | {"calculation_id": str(uuid4())},
            )
            assert corrected.status_code == 202, corrected.text
            corrected_id = corrected.json()["calculation_id"]
            assert corrected_id != calculation_id
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 1
            corrected_result = client.get(f"/performance/workspace-summary/results/{corrected_id}", headers=owner)
            assert corrected_result.status_code == 200, corrected_result.text
            original_result = client.get(result_url, headers=owner)
            assert original_result.status_code == 422
            assert original_result.json()["error_code"] == result.json()["error_code"]
            assert restarted["async_result_store"].get_result(UUID(calculation_id)).failure == failed_record.failure
            assert client.get(execution_url, headers=owner).json()["compute_job"]["attempt_count"] == 1
            assert len(outbound) == 2


def assert_retryable_source_failure(database_url, monkeypatch, status, tmp_path, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS", 1)
    monkeypatch.setattr(settings, "COMPUTE_EXECUTOR_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "CORE_MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "CORE_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(settings, "LINEAGE_STORAGE_PATH", str(tmp_path / "lineage"))
    outbound = []

    def core(request):
        outbound.append(request)
        if status == "timeout":
            raise httpx.ReadTimeout(UNTRUSTED_MARKER, request=request)
        if status == "malformed":
            return httpx.Response(422, text=UNTRUSTED_MARKER)
        payload = core_source_refusal()
        if status == 422:
            payload["metadata"]["source_product"] = "AnalyticsExportJob"
        return httpx.Response(status, json=payload)

    install_core_transport(monkeypatch, core)
    with resolved_runtime_stores(database_url, monkeypatch):
        durable_metadata_bootstrap.bootstrap_durable_metadata_stores()
        with TestClient(main.app, headers={"X-Tenant-Id": "tenant-refusal-owner"}) as client:
            accepted = client.post(
                "/performance/workspace-summary",
                json={
                    "portfolio_id": "SOURCE_REFUSAL_RETRY_TEST",
                    "input_mode": "stateful",
                    "stateful_input": {},
                    "performance_start_date": "2025-01-01",
                    "report_end_date": "2025-01-02",
                    "periods": [{"period": "SI", "frequencies": ["daily"]}],
                },
            )
            assert accepted.status_code == 202, accepted.text
            calculation_id = accepted.json()["calculation_id"]
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 1
            per_attempt = 3 if status in (429, 502, 503, 504, "timeout") else 1
            assert len(outbound) == per_attempt
            poll_url = f"/performance/executions/{calculation_id}"
            body = client.get(poll_url).json()
            assert body["compute_job"]["job_status"] == "pending"
            assert body["compute_job"]["attempt_count"] == 1
            assert body["compute_job"]["failure"]["retryable"] is True
            assert body["async_result"] is None
            assert client.get(f"/performance/workspace-summary/results/{calculation_id}").status_code == 202

    with resolved_runtime_stores(database_url, monkeypatch):
        with TestClient(main.app, headers={"X-Tenant-Id": "tenant-refusal-owner"}) as client:
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 1
            assert len(outbound) == per_attempt * 2
            body = client.get(poll_url).json()
            assert body["compute_job"]["job_status"] == "failed"
            assert body["compute_job"]["attempt_count"] == 2
            assert body["failure"]["status_code"] == 503
            assert body["failure"]["error_code"] == "SOURCE_UNAVAILABLE"
            assert body["failure"]["retryable"] is True
            assert body["async_result"]["result_status"] == "failed"
            result = client.get(f"/performance/workspace-summary/results/{calculation_id}")
            assert result.status_code == 503
            assert result.json()["retryable"] is True
            assert UNTRUSTED_MARKER not in result.text + json.dumps(body) + caplog.text
            assert compute_executor_worker.process_pending_jobs(limit=1, settings=settings) == 0
            assert len(outbound) == per_attempt * 2
