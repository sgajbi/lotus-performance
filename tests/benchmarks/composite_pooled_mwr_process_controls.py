"""Fresh-interpreter pooled custody proof using controlled synthetic suppliers only."""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine

from app.adapters import composite_pooled_mwr_source as sources
from app.core.config import get_settings
from app.models.composite_authority import authority_digest
from app.services.durable_database_engine import create_durable_database_engine
from main import app
from tests.composite_principal_helpers import install_principal_deployment
from tests.integration.test_composite_pooled_mwr_api import PATH, ControlledPooledReader, _run_request

FINANCIAL_TABLES = ("composite_pooled_mwr_inputs", "analytics_async_result")


def snapshot(engine, *, all_tables=False):
    """Capture complete rows, preserving retained JSON and database timestamps."""
    with engine.connect() as connection:
        tables = inspect(connection).get_table_names() if all_tables else FINANCIAL_TABLES
        return {
            table: sorted(
                connection.exec_driver_sql(
                    f"SELECT row_to_json(t)::text FROM {connection.dialect.identifier_preparer.quote(table)} t"
                ).scalars()
            )
            for table in sorted(tables)
        }


def write_phase(client, monkeypatch, headers, path):
    reader = ControlledPooledReader()
    monkeypatch.setattr(sources, "_deployment", sources.PooledMonetarySourceDeployment(reader))
    runtime = client, reader, None, None, headers
    original, accepted, result = _run_request(runtime)
    reader.add_correction()
    correction = original.model_copy(
        update={
            "calculation_id": uuid4(),
            "source_manifest_id": "controlled-correction-v2",
            "correction_of_calculation_id": original.calculation_id,
        }
    )
    _, corrected_accepted, corrected = _run_request(runtime, correction)
    assert corrected["input_manifest_digest"] != result["input_manifest_digest"]
    assert reader.money_reads == 2
    state = {
        "requests": [original.model_dump(mode="json"), correction.model_dump(mode="json")],
        "paths": [accepted["result_path"], corrected_accepted["result_path"]],
        "results": [result, corrected],
    }
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return {**state, "source_money_reads": reader.money_reads}


def read_phase(client, monkeypatch, headers, state, engine, authority):
    assert isinstance(sources.get_pooled_monetary_source_reader(), sources.UnavailablePooledMonetarySource)
    before = snapshot(engine, all_tables=True)
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        if connection.engine.url == engine.url:
            verb = statement.lstrip().split(None, 1)[0].upper()
            assert verb in {"SELECT", "SHOW"}, statement
            statements.append(verb)

    event.listen(Engine, "before_cursor_execute", observe)
    try:
        results = []
        for path, original in zip(state["paths"], state["results"], strict=True):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json() == original
            results.append(response.json())
        authority.portfolios = frozenset({"member-a"})
        scoped = client.get(state["paths"][0], headers=headers)
        assert scoped.status_code == 403, scoped.text
        authority.portfolios = frozenset({"member-a", "member-b"})
        _, foreign_mint = install_principal_deployment(
            monkeypatch, app, tenant="controlled-foreign", portfolios=["member-a", "member-b"]
        )
        foreign = client.get(
            state["paths"][0],
            headers={"X-Tenant-Id": "controlled-foreign", "Authorization": "Bearer " + foreign_mint()},
        )
        assert foreign.status_code == 404, foreign.text
        assert "observation" not in foreign.json()
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    after = snapshot(engine, all_tables=True)
    assert before == after
    assert statements
    with engine.connect() as connection:
        isolation = connection.exec_driver_sql("SHOW transaction_isolation").scalar_one()
        read_only = connection.exec_driver_sql("SHOW transaction_read_only").scalar_one()
    assert isolation == "repeatable read" and read_only == "on"
    return {
        "results": results,
        "unchanged_all_tables": True,
        "table_row_counts": {table: len(rows) for table, rows in before.items()},
        "before_digest": authority_digest(before),
        "after_digest": authority_digest(after),
        "read_only": read_only,
        "isolation": isolation,
        "isolation_scope": "Explicit test connection configuration; not a production default claim",
        "observed_statement_count": len(statements),
        "foreign_status": foreign.status_code,
        "member_scope_status": scoped.status_code,
        "source_adapter": "UNAVAILABLE",
    }


def retry_phase(client, headers, state, engine):
    assert isinstance(sources.get_pooled_monetary_source_reader(), sources.UnavailablePooledMonetarySource)
    before = snapshot(engine)
    results = []
    for request, path, original in zip(state["requests"], state["paths"], state["results"], strict=True):
        response = client.post(PATH, json=request, headers=headers)
        assert response.status_code == 202, response.text
        retained = client.get(path, headers=headers)
        assert retained.status_code == 200 and retained.json() == original, retained.text
        results.append(retained.json())
    assert before == snapshot(engine)
    return {"results": results, "unchanged_financial_rows": True, "source_adapter": "UNAVAILABLE"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--phase", choices=("write", "read", "retry"), required=True)
    args = parser.parse_args()
    url = get_settings().LINEAGE_METADATA_DATABASE_URL
    assert url.startswith("postgresql")
    engine = create_durable_database_engine(url)
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            authority, mint = install_principal_deployment(
                monkeypatch, app, tenant="controlled-tenant", portfolios=["member-a", "member-b"]
            )
            headers = {"X-Tenant-Id": "controlled-tenant", "Authorization": "Bearer " + mint()}
            with TestClient(app) as client:
                if args.phase == "write":
                    result = write_phase(client, monkeypatch, headers, args.state)
                else:
                    state = json.loads(args.state.read_text(encoding="utf-8"))
                    result = (
                        read_phase(client, monkeypatch, headers, state, engine, authority)
                        if args.phase == "read"
                        else retry_phase(client, headers, state, engine)
                    )
    finally:
        engine.dispose()
    print(json.dumps({"pid": os.getpid(), "phase": args.phase, "result": result}, sort_keys=True))


if __name__ == "__main__":
    main()
