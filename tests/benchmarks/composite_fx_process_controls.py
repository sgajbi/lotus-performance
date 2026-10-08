"""Registered FX worker and retained reads across separate processes on owned PostgreSQL.

Only source ports and an explicitly synthetic independent verifier are configured.
The read process refuses all upstream refetches and has no child execution records.
"""

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.composite_authority import authority_digest
from app.models.composite_materialization import CompositeMaterializationCommand
from app.services.compute_job_store import compute_job_store
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from tests.composite_currency_normalization_helpers import synthetic_fx_verification
from tests.composite_materialization_helpers import source_products
from tests.integration.test_composite_materialization_api import (
    composite_request,
    run_registered_fx_money_control,
)

HEADERS = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}


def write_phase(state_path, state):
    state["versions"] = {}
    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    for label, rate, sequence in [("original", "1.4", 1), ("corrected", "1.42", 2)]:

        def capture(command, wire, receipt, periods):
            state["versions"][label] = {
                "command": command.model_dump(mode="json"),
                "wire": wire,
                "receipt": receipt,
                "periods": periods,
            }
            state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

        with pytest.MonkeyPatch.context() as monkeypatch:
            run_registered_fx_money_control(
                monkeypatch,
                normalize=True,
                eod_flow=state["eod_flow"],
                capture=capture,
                products=products,
                ending_rate=rate,
                restatement_sequence=sequence,
            )
    return {key: {"receipt": row["receipt"], "periods": row["periods"]} for key, row in state["versions"].items()}


def read_phase(state, *, known_wires):
    command = CompositeMaterializationCommand.model_validate(state["command"])
    binding = command.currency_normalization_binding

    def no_refetch(*args, **kwargs):
        raise AssertionError("Fresh retained reconstruction must not refetch source or child executions")

    def verify(request):
        assert any(request.source_digest == authority_digest(wire) for wire in known_wires)
        assert request.resolution.tenant_id == "tenant-a"
        return synthetic_fx_verification(request)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", no_refetch)
        monkeypatch.setattr(
            "app.adapters.composite_member_result_source.execution_registry.get_execution_for_tenant", no_refetch
        )
        monkeypatch.setattr(
            "app.ports.composite_currency_normalization.composite_fx_source_resolver",
            lambda: SimpleNamespace(resolve=no_refetch),
        )
        monkeypatch.setattr(
            "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
            lambda: SimpleNamespace(verify=verify),
        )
        with TestClient(app, headers=HEADERS) as client:
            path = f"/performance/composites/materializations/{command.materialization_id}"
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert response.json() == state["receipt"]
            report = client.post(
                "/performance/composites/twr", json=composite_request(command, sequence=command.restatement_sequence)
            )
            assert report.status_code == 200 and report.json()["periods"] == state["periods"], report.text
            job = compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a")
            assert client.post("/performance/composites/materializations", json=state["command"]).status_code == 202
            assert compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a") == job
            assert process_pending_jobs(limit=1) == 0
            conflicting = {
                **state["command"],
                "currency_normalization_binding": {**binding.model_dump(mode="json"), "revision": "changed"},
            }
            assert client.post("/performance/composites/materializations", json=conflicting).status_code == 409
            assert client.get(path, headers={**HEADERS, "X-Tenant-Id": "tenant-b"}).status_code == 404
            assert client.get(path).json() == state["receipt"]
    with TestClient(app, headers=HEADERS) as client:
        refused = client.get(path)
        assert refused.status_code == 503, refused.text
        assert "COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED" in refused.text
    return {
        "receipt": response.json(),
        "periods": report.json()["periods"],
        "default_verifier_status": refused.status_code,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--phase", choices=("write", "read"), required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    if args.phase == "write":
        result = write_phase(args.state, state)
    else:
        versions = state["versions"]
        wires = [row["wire"] for row in versions.values()]
        assert versions["original"]["wire"] != versions["corrected"]["wire"]
        assert versions["original"]["periods"] != versions["corrected"]["periods"]
        result = {key: read_phase(row, known_wires=wires) for key, row in versions.items()}
    print(json.dumps({"pid": os.getpid(), "phase": args.phase, "result": result}, sort_keys=True))


if __name__ == "__main__":
    main()
