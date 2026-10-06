"""Registered oracle materializations and retained replay; no alternate financial pipeline."""

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from app.adapters.composite_materialization_repository import get_composite_materialization_store
from app.services.composite_metadata_store import composite_metadata_store
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from tests.composite_authority_helpers import (
    command_for_packet,
    install_test_authorities,
    numerical_oracles,
    oracle_month_packet,
)
from tests.integration.test_composite_provider_materialization_api import HEADERS, install_provider_wires, request_for


def scenario_pairs(name):
    months = (1,) if name == "OR-01" else (1, 2) if name == "OR-02" else (1, 2, 3)
    return [
        oracle_month_packet(month, missing_member=name == "OR-18" and month == 2, composite_id=f"SYNTHETIC_{name}")
        for month in months
    ]


def prove_oracle(client, name, payload):
    spec = next(item for item in numerical_oracles()["fixtures"] if item["id"] == name)
    response = client.post("/performance/composites/twr", json=payload)
    if name == "OR-18":
        assert response.status_code == 409, response.text
        assert response.json()["error_code"] == spec["expected"]["reason"]
        assert "cumulative_return" not in response.json()
        return {"http_status": 409, "reason": response.json()["error_code"], "financial_payload": "ABSENT_REFUSED"}
    assert response.status_code == 200, response.text
    body = response.json()
    expected = Decimal(spec["expected"].get("return", spec["expected"].get("cumulative_return")))
    assert abs(Decimal(str(body["cumulative_return"])) - expected) <= Decimal(
        numerical_oracles()["numeric_comparison_absolute_tolerance"]
    )
    assert [str(item["materialization_id"]) for item in body["selection_manifest"]["windows"]] == payload[
        "materialization_ids"
    ]
    assert all(
        row["calculation_id"] is None and row["source_authority_identity"]["source_kind"] == "EXTERNAL_PROVIDER"
        for period in body["periods"]
        for row in period["member_contributions"]
    )
    if name == "OR-01":
        rows = body["periods"][0]["member_contributions"]
        assert [Decimal(str(row["beginning_asset_weight"])) for row in rows] == list(
            map(Decimal, spec["expected"]["weights"])
        )
        assert [Decimal(str(row["contribution"])) for row in rows] == list(
            map(Decimal, spec["expected"]["contributions"])
        )
    return body


def write_phase(client, monkeypatch, path):
    state = {
        "payloads": {},
        "packets": [],
        "receipts": {},
        "oracle_source_sha256": numerical_oracles()["source_sha256"],
    }
    results = {}
    for name in ("OR-01", "OR-02", "OR-18"):
        pairs = scenario_pairs(name)
        packets, wires = map(list, zip(*pairs, strict=True))
        install_test_authorities(monkeypatch, packets)
        install_provider_wires(monkeypatch, packets, wires)
        identities = []
        for sequence, (packet, wire) in enumerate(pairs, 1):
            command = command_for_packet(
                packet, period_start=wire["period_start"], period_end=wire["period_end"], restatement_sequence=sequence
            )
            accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
            assert accepted.status_code == 202, accepted.text
            assert process_pending_jobs(limit=1) == 1
            receipt = client.get(accepted.json()["result_path"])
            assert receipt.status_code == 200
            body = receipt.json()
            if name == "OR-18" and sequence == 2:
                assert body["expected_count"] == 2 and body["ready_count"] == body["blocked_count"] == 1
                assert body["state"] == "BLOCKED" and body["members"][1]["fact"] is None
                with composite_metadata_store._engine.connect() as connection:
                    for table in ("composite_member_return_facts", "composite_member_return_fact_publications"):
                        assert (
                            connection.execute(
                                text(
                                    f"SELECT count(*) FROM {table} WHERE composite_id=:composite AND restatement_sequence=2"
                                ),
                                {"composite": command.composite_id},
                            ).scalar_one()
                            == 0
                        )
            else:
                assert body["state"] == "COMPLETE"
            identities.append(str(command.materialization_id))
            state["receipts"][str(command.materialization_id)] = body
        payload = {
            **request_for(command),
            "period_start": wires[0]["period_start"],
            "materialization_ids": identities,
            "calculation_id": str(command.calculation_id),
        }
        results[name] = prove_oracle(client, name, payload)
        state["payloads"][name] = payload
        state["packets"].extend(packets)
    corrected, wire = oracle_month_packet(1, corrected=True, composite_id="SYNTHETIC_OR-02")
    install_test_authorities(monkeypatch, [*state["packets"], corrected])
    correction = command_for_packet(
        corrected, period_start=wire["period_start"], period_end=wire["period_end"], restatement_sequence=3
    )
    assert (
        client.post("/performance/composites/materializations", json=correction.model_dump(mode="json")).status_code
        == 202
    )
    assert prove_oracle(client, "OR-02", state["payloads"]["OR-02"]) == results["OR-02"]
    state.update(
        corrected_packet=corrected, corrected_wire=wire, correction=correction.model_dump(mode="json"), oracles=results
    )
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return {"oracles": results, "oracle_source_sha256": state["oracle_source_sha256"]}


def read_phase(client, monkeypatch, path):
    state = json.loads(path.read_text(encoding="utf-8"))
    packets = [*state["packets"], state["corrected_packet"]]
    install_test_authorities(monkeypatch, packets)
    # Only the new correction may fetch observations; originals must be retained reads.
    install_provider_wires(monkeypatch, packets, [state["corrected_wire"]])
    results = {}
    snapshot = {}
    trigger = False
    store = get_composite_materialization_store()

    def after_select(connection, cursor, statement, parameters, context, executemany):
        nonlocal trigger
        if trigger or connection.get_execution_options().get("isolation_level") != "REPEATABLE READ":
            return
        if "FROM composite_materializations" not in statement:
            return
        trigger = True
        snapshot["isolation"] = connection.get_isolation_level()
        query = text(
            "SELECT count(*) FROM composite_materializations WHERE composite_id='SYNTHETIC_OR-02' AND state='COMPLETE'"
        )
        snapshot["before"] = connection.execute(query).scalar_one()
        # Separate worker connection commits the already-admitted correction while
        # this retained vector is being read. No rows/results are patched.
        assert process_pending_jobs(limit=1) == 1
        snapshot["after"] = connection.execute(query).scalar_one()
        with store._engine.connect() as outside:
            snapshot["outside"] = outside.execute(query).scalar_one()

    for name in ("OR-02", "OR-01", "OR-18"):
        if name == "OR-02":
            event.listen(Engine, "after_cursor_execute", after_select)
        try:
            results[name] = prove_oracle(client, name, state["payloads"][name])
        finally:
            if name == "OR-02":
                event.remove(Engine, "after_cursor_execute", after_select)
    assert snapshot == {"isolation": "REPEATABLE READ", "before": 2, "after": 2, "outside": 3}
    for identity, expected in state["receipts"].items():
        retained = client.get(f"/performance/composites/materializations/{identity}")
        assert retained.status_code == 200 and retained.json() == expected
    return {"oracles": results, "snapshot": snapshot, "oracle_source_sha256": state["oracle_source_sha256"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--phase", choices=("write", "read"), required=True)
    args = parser.parse_args()
    with pytest.MonkeyPatch.context() as monkeypatch, TestClient(app, headers=HEADERS) as client:
        result = (
            write_phase(client, monkeypatch, args.state)
            if args.phase == "write"
            else read_phase(client, monkeypatch, args.state)
        )
    print(json.dumps({"pid": os.getpid(), "phase": args.phase, "result": result}, sort_keys=True))


if __name__ == "__main__":
    main()
