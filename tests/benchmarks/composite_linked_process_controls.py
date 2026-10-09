"""Registered worker write and fresh-interpreter retained read; synthetic sources only."""

import argparse
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from app.adapters.composite_materialization_repository import get_composite_materialization_store
from app.core.config import get_settings
from main import app
from tests.composite_authority_helpers import install_test_authorities
from tests.composite_linked_contribution_helpers import (
    LINKED_PATH,
    assert_or13,
    linked_packet,
    linked_request,
    publish_pairs,
)
from tests.integration.test_composite_provider_materialization_api import HEADERS, install_provider_wires


def _response(client, payload):
    response = client.post(LINKED_PATH, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def write_phase(client, monkeypatch, path):
    pairs = [linked_packet(month) for month in (1, 2)]
    correction = linked_packet(1, corrected=True)
    all_pairs = [*pairs, correction]
    packets, wires = map(list, zip(*all_pairs, strict=True))
    install_test_authorities(monkeypatch, packets)
    install_provider_wires(monkeypatch, packets, wires)
    commands = publish_pairs(client, pairs)
    original_payload = linked_request(commands)
    original = _response(client, original_payload)
    assert_or13(original)
    corrected = publish_pairs(client, [correction], sequence_start=3)[0]
    corrected_payload = linked_request([corrected, commands[1]])
    revised = _response(client, corrected_payload)
    assert _response(client, original_payload) == original
    state = {
        "packets": packets,
        "original_payload": original_payload,
        "corrected_payload": corrected_payload,
        "original": original,
        "corrected": revised,
    }
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return {"original": original, "corrected": revised}


def _snapshot(store):
    with store._engine.connect() as connection:
        return {
            table: sorted((tuple(row) for row in connection.execute(text(f"SELECT * FROM {table}"))), key=repr)
            for table in (
                "composite_materializations",
                "composite_member_return_facts",
                "composite_member_return_fact_publications",
            )
        }


def read_phase(client, monkeypatch, path):
    state = json.loads(path.read_text(encoding="utf-8"))
    install_test_authorities(monkeypatch, state["packets"])

    # Retained receipt replay must not consult mutable upstream observations.
    def forbidden_read(**kwargs):
        raise AssertionError("Pinned replay attempted upstream fan-out")

    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", forbidden_read)
    store = get_composite_materialization_store()
    assert store._engine.dialect.name == "postgresql"
    before = _snapshot(store)
    observations = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        if connection.engine.url == store._engine.url:
            assert statement.lstrip().split(None, 1)[0].upper() in {"SELECT", "SHOW"}, statement
            if "FROM composite_materializations" in statement:
                observations.append(connection.get_isolation_level())

    event.listen(Engine, "before_cursor_execute", observe)
    try:
        original = _response(client, state["original_payload"])
        corrected = _response(client, state["corrected_payload"])
        assert original == state["original"] and corrected == state["corrected"]
        assert_or13(original)
        foreign = client.post(
            LINKED_PATH, json=state["original_payload"], headers={**HEADERS, "X-Tenant-Id": "synthetic-tenant-b"}
        )
        assert foreign.status_code == 404 and "members" not in foreign.json()
        gap = client.post(
            LINKED_PATH,
            json={
                **state["original_payload"],
                "materialization_ids": state["original_payload"]["materialization_ids"][:1],
            },
        )
        assert gap.status_code == 409 and gap.json()["error_code"] == "REQUIRED_PERIOD_UNAVAILABLE"
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    assert observations and set(observations) == {"REPEATABLE READ"}
    assert before == _snapshot(store)
    return {
        "original": original,
        "corrected": corrected,
        "read_isolation": "REPEATABLE READ",
        "unchanged_rows": True,
        "foreign_status": 404,
        "missing_status": 409,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--phase", choices=("write", "read"), required=True)
    args = parser.parse_args()
    assert get_settings().LINEAGE_METADATA_DATABASE_URL.startswith("postgresql")
    with pytest.MonkeyPatch.context() as monkeypatch, TestClient(app, headers=HEADERS) as client:
        result = (
            write_phase(client, monkeypatch, args.state)
            if args.phase == "write"
            else read_phase(client, monkeypatch, args.state)
        )
    print(json.dumps({"pid": os.getpid(), "phase": args.phase, "result": result}, sort_keys=True))


if __name__ == "__main__":
    main()
