"""Fresh-process, registered/default-worker controls on an owned PostgreSQL schema.

Only upstream source/observation and separate synthetic verification ports are injected.
No financial output, successful fact, execution, ledger, or worker result is replaced.
"""

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters import composite_provider_member_source as provider_adapter
from app.models.composite_authority import authority_digest
from app.models.composite_materialization import CompositeMaterializationCommand
from app.models.composites import CompositeMemberReturnFact
from app.workers.compute_executor_worker import process_pending_jobs
from core.errors import APIError
from engine.composites import _build_ready_member_contributions
from main import app
from tests.composite_authority_helpers import install_test_authorities, observation_packet, shared_packet
from tests.integration.test_composite_provider_materialization_api import HEADERS, request_for


def packets_for(shape):
    if shape == "frozen":
        packets = [shared_packet(version) for version in ("original", "corrected")]
        return packets, [packet["supporting_payloads"]["member_facts"] for packet in packets]
    pairs = [observation_packet(corrected=corrected) for corrected in (False, True)]
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def install_process_controls(monkeypatch, packets, wires, phase):
    install_test_authorities(monkeypatch, packets)

    async def manage_read(**kwargs):
        assert kwargs["headers"]["X-Tenant-Id"] == "synthetic-tenant-a"
        packet = next(packet for packet in packets if packet["definition"]["definition_version"] in kwargs["url"])
        product = (
            "attestation"
            if "universe-attestations" in kwargs["url"]
            else ("membership" if "/membership/" in kwargs["url"] else "definition")
        )
        return 200, packet[product]

    class Observations:
        def read(self, *, tenant_id, selection):
            assert tenant_id == "synthetic-tenant-a"
            if phase == "read":
                raise AssertionError("Fresh retained reads must use retained observation wires")
            if phase == "waiting":
                raise APIError(
                    status_code=503,
                    detail="Controlled transient observation outage",
                    error_code="TEST_TRANSIENT_PROVIDER_OUTAGE",
                    retryable=True,
                )
            return next(wire for wire in wires if wire["revision"] == selection.source_revision)

    def no_internal(*args, **kwargs):
        raise AssertionError("External proof must not fabricate or consult internal calculation/Core evidence")

    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", manage_read)
    monkeypatch.setattr(provider_adapter, "provider_observation_source", Observations)
    monkeypatch.setattr(provider_adapter.RetainedCompositeMemberResultSource, "read_member", no_internal)


def receipt_for(client, command):
    response = client.get(f"/performance/composites/materializations/{command.materialization_id}")
    assert response.status_code == 200, response.text
    return response.json()


def prove_receipt(client, command, *, shape, corrected):
    receipt = receipt_for(client, command)
    assert receipt["state"] == "COMPLETE" and receipt["ready_count"] == 3, receipt
    facts = [CompositeMemberReturnFact.model_validate(member["fact"]) for member in receipt["members"]]
    assert all(fact.calculation_id is None for fact in facts)
    total = sum((fact.beginning_market_value for fact in facts), Decimal(0))
    weighted, contributions = _build_ready_member_contributions(ready_facts=facts, beginning_assets=total)
    expected = Decimal(49) / Decimal(3050) if corrected else Decimal(1) / Decimal(60)
    assert abs(weighted - expected) < Decimal("1e-25")
    assert sum((item.weight for item in contributions), Decimal(0)) == 1
    result = client.post("/performance/composites/twr", json=request_for(command, command.restatement_sequence))
    if shape == "frozen":
        assert all(fact.ending_market_value is None for fact in facts)
        assert result.status_code == 422 and "COMPOSITE_ENDING_ASSETS_UNAVAILABLE" in result.text
        for member in receipt["members"]:
            raw = member["source_evidence"]["observation_wires"][0]
            assert raw["product_name"] == "SyntheticMonthlyMemberFacts"
            assert all("cash_flows" not in row and "ending_assets" not in row for row in raw["rows"])
    else:
        assert result.status_code == 200, result.text
        period = result.json()["periods"][0]
        assert abs(Decimal(str(period["return_value"])) - expected) < Decimal("1e-12")
        assert Decimal(str(period["ending_market_value"])) == (Decimal("649.8") if corrected else Decimal(640))
    return {
        "receipt": receipt,
        "receipt_digest": authority_digest(receipt),
        "weighted_return": str(weighted),
        "asset_report_status": result.status_code,
    }


def submit_and_work(client, command):
    response = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
    assert response.status_code == 202, response.text
    assert process_pending_jobs(limit=1) == 1


def execute_phase(state, phase):
    commands = {key: CompositeMaterializationCommand.model_validate(value) for key, value in state["commands"].items()}
    packets, wires = packets_for(state["shape"])
    with pytest.MonkeyPatch.context() as monkeypatch:
        install_process_controls(monkeypatch, packets, wires, phase)
        with TestClient(app, headers=HEADERS) as client:
            return run_phase(client, commands, state["shape"], phase)


def run_phase(client, commands, shape, phase):
    if phase in {"original", "corrected", "recover"}:
        command = commands[phase]
        submit_and_work(client, command)
        return prove_receipt(client, command, shape=shape, corrected=phase != "original")
    if phase == "waiting":
        command = commands[phase]
        submit_and_work(client, command)
        receipt = receipt_for(client, command)
        assert receipt["state"] == "WAITING" and receipt["waiting_count"] == 3, receipt
        latest = client.post("/performance/composites/twr", json=request_for(command))
        assert latest.status_code == 409 and "COMPOSITE_FACT_SELECTION_INCOMPLETE" in latest.text
        return {"receipt": receipt, "asset_report_status": latest.status_code}
    return prove_retained_replay(client, commands, shape)


def prove_retained_replay(client, commands, shape):
    original = prove_receipt(client, commands["original"], shape=shape, corrected=False)
    corrected = prove_receipt(client, commands["corrected"], shape=shape, corrected=True)
    exact = client.post("/performance/composites/materializations", json=commands["original"].model_dump(mode="json"))
    assert exact.status_code == 202, exact.text
    conflict = commands["original"].model_dump(mode="json")
    conflict["restatement_sequence"] = 99
    refused = client.post("/performance/composites/materializations", json=conflict)
    assert refused.status_code == 409, refused.text
    assert authority_digest(receipt_for(client, commands["original"])) == original["receipt_digest"]
    assert authority_digest(receipt_for(client, commands["corrected"])) == corrected["receipt_digest"]
    return {
        "original": original,
        "corrected": corrected,
        "exact_replay_status": exact.status_code,
        "conflicting_replay_status": refused.status_code,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--phase", choices=("original", "corrected", "read", "waiting", "recover"), required=True)
    args = parser.parse_args()
    result = execute_phase(json.loads(args.state.read_text(encoding="utf-8")), args.phase)
    print(json.dumps({"pid": os.getpid(), "phase": args.phase, "result": result}, sort_keys=True))


if __name__ == "__main__":
    main()
