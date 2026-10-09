"""Registered worker and durable monthly evidence; unsupported finance stays refused."""

import json
from contextlib import closing

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.core.config import get_settings
from app.models.composite_monthly_eligibility_evidence import CompositeMonthlyEligibilityPublicationReceipt
from app.services.composite_materialization.source_contract import require_pinned_source_scope
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_authority_helpers import command_for_packet
from tests.composite_monthly_eligibility_helpers import install_monthly_test_authorities, synthetic_monthly_packet


@pytest.fixture
def monthly_runtime_database(monkeypatch, tmp_path):
    url = "sqlite:///" + (tmp_path / "monthly.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    return url


def exercise_registered_monthly_retention(monkeypatch, database_url, *, source_available):
    packet, wire = synthetic_monthly_packet()
    calls = install_monthly_test_authorities(monkeypatch, packet, wire, source_available=source_available)
    reads = []

    async def get(**kwargs):
        reads.append(("GET", kwargs))
        product = (
            "attestation"
            if "universe-attestations" in kwargs["url"]
            else "membership"
            if "/membership/" in kwargs["url"]
            else "definition"
        )
        return 200, packet[product]

    async def post(**kwargs):
        reads.append(("POST", kwargs))
        assert kwargs["json_body"]["digest"] == wire["approval"]["content_hash"]
        return 200, kwargs["response_decoder"](httpx.Response(200, text=json.dumps(wire)))

    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "https://manage.test/api/v1")
    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", get)
    monkeypatch.setattr("app.adapters.manage_composite_eligibility_evidence.post_with_retry", post)
    command = command_for_packet(packet)
    headers = {"X-Tenant-Id": "synthetic-tenant", "X-Actor-Id": "reader", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        response = client.get(accepted.json()["result_path"])
        assert response.status_code == 200, response.text
        progress = response.json()
        # SyntheticAssets/Returns are intentionally unsupported financial products.
        assert progress["state"] == "BLOCKED", progress
        assert progress["ready_count"] == 0
        assert [method for method, _ in reads] == ["GET", "GET", "GET", "POST"]
        foreign = client.get(accepted.json()["result_path"], headers={**headers, "X-Tenant-Id": "foreign-tenant"})
        assert foreign.status_code == 404
        assert (
            client.post("/performance/composites/materializations", json=command.model_dump(mode="json")).status_code
            == 202
        )
        assert client.get(accepted.json()["result_path"]).json() == progress
    with closing(CompositeMaterializationStore(database_url)) as reopened:
        retained = reopened.get(command.materialization_id, tenant_id="synthetic-tenant")
        if source_available:
            assert isinstance(
                retained.source.published_eligibility.receipt, CompositeMonthlyEligibilityPublicationReceipt
            )
            assert retained.source.published_eligibility.receipt.model_dump() == wire
            require_pinned_source_scope(retained.source, command=command, tenant_id="synthetic-tenant")
            assert {request.purpose for request in calls} == {
                "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE",
                "RETURN_METHOD_CALENDAR",
                "ELIGIBILITY_POLICY",
                "COMPOSITE_MONTHLY_MEMBERSHIP_APPROVAL",
            }
        else:
            assert retained.source is None
            assert retained.outcomes == []
            assert calls == []


@pytest.mark.parametrize("source_available", [False, True])
def test_registered_monthly_admission_retention_reopen_and_financial_refusal(
    monkeypatch, monthly_runtime_database, source_available
):
    exercise_registered_monthly_retention(monkeypatch, monthly_runtime_database, source_available=source_available)
