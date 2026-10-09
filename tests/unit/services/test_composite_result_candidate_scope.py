"""Retained identity admission projects no financial payload and refuses corruption."""

import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event

from app.adapters.composite_materialization_records import CompositeMaterializationModel, MaterializationBase
from app.adapters.composite_result_candidate_scope import require_candidate_member_scope
from core.errors import APIConflictError, APIError


@pytest.fixture
def scope_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retained-scope.db'}")
    MaterializationBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _insert_window(engine, identity, source, state="COMPLETE"):
    with engine.begin() as connection:
        connection.execute(
            CompositeMaterializationModel.__table__.insert().values(
                tenant_id="tenant-a",
                materialization_id=str(identity),
                composite_id="composite-a",
                return_view="GROSS",
                reporting_currency="USD",
                restatement_sequence=1,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                command_json="{}",
                actor_id="controlled-source",
                source_json=source,
                state=state,
            )
        )


def _admit(engine, identity):
    require_candidate_member_scope(
        SimpleNamespace(_engine=engine),
        request=SimpleNamespace(materialization_ids=[identity]),
        principal=SimpleNamespace(tenant_id="tenant-a", portfolio_scope=frozenset({"member-a"})),
    )


@pytest.mark.parametrize("scope", [None, [], {}, [1], [""], ["member-a", "member-a"]])
def test_malformed_retained_member_population_refuses_before_financial_reads(scope_database, scope):
    identity = uuid4()
    _insert_window(scope_database, identity, json.dumps({"attestation": {"expected_portfolio_ids": scope}}))
    with pytest.raises(APIError, match="Retained member scope"):
        _admit(scope_database, identity)


def test_invalid_retained_json_database_error_is_a_typed_custody_refusal(scope_database):
    identity = uuid4()
    _insert_window(scope_database, identity, "{")
    with pytest.raises(APIError, match="Retained member scope") as refused:
        _admit(scope_database, identity)
    assert refused.value.status_code == 503


@pytest.mark.parametrize("state", [None, "WAITING", "BLOCKED"])
def test_absent_or_incomplete_window_refuses_without_numerical_access(scope_database, state):
    identity = uuid4()
    if state is not None:
        _insert_window(scope_database, identity, "{}", state)
    with pytest.raises(APIConflictError, match="complete retained window"):
        _admit(scope_database, identity)


def test_only_member_identity_projection_crosses_the_application_boundary(scope_database):
    identity = uuid4()
    source = {"attestation": {"expected_portfolio_ids": ["member-a"]}, "financial_payload": "UNREAD_SENTINEL"}
    _insert_window(scope_database, identity, json.dumps(source))
    statements = []
    projected_columns = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        projected_columns.extend(column[0] for column in cursor.description)

    event.listen(scope_database, "after_cursor_execute", observe)
    try:
        _admit(scope_database, identity)
    finally:
        event.remove(scope_database, "after_cursor_execute", observe)
    assert len(statements) == 1
    assert "json_extract" in statements[0] and "composite_materializations.tenant_id" in statements[0]
    assert projected_columns == ["state", "member_scope"]
    assert "analytics_async_result" not in statements[0] and "composite_member_return_facts" not in statements[0]
