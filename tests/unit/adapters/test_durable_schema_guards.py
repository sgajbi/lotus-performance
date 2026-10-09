from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event

from app.adapters.composite_model_fee_profile_schema import model_fee_profile_guard_statements
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.adapters.durable_schema.guards import require_managed_guards
from app.services.composite_metadata_store import composite_fact_guard_statements
from scripts.durable_schema_apply import apply_durable_schema


@pytest.fixture
def engine(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'guarded.db'}"
    assert apply_durable_schema(database_url=database_url).status == "passed"
    database = create_engine(database_url)
    try:
        yield database
    finally:
        database.dispose()


def test_current_guard_definitions_accept_with_read_only_catalog_queries(engine):
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _, __, sql, *args: statements.append(sql))
    with engine.connect() as connection:
        require_managed_guards(connection, composite_fact_guard_statements(connection.dialect))
    assert statements
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)


@pytest.mark.parametrize("weakened", [False, True])
def test_missing_or_same_named_weakened_guard_refuses_without_repair(engine, weakened):
    name = "trg_composite_member_return_facts_immutable_update"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP TRIGGER {name}")
        if weakened:
            connection.exec_driver_sql(
                f"CREATE TRIGGER {name} BEFORE UPDATE ON composite_member_return_facts BEGIN SELECT 1; END"
            )
        with pytest.raises(DurableSchemaMigrationRequiredError) as error:
            require_managed_guards(connection, composite_fact_guard_statements(connection.dialect))
        assert f"trigger:{name}" in error.value.issues
        sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
        ).scalar()
        assert (sql is not None and "SELECT 1" in sql) if weakened else sql is None


def test_absent_guard_contract_cannot_be_a_successful_verification(engine):
    with engine.connect() as connection:
        with pytest.raises(DurableSchemaMigrationRequiredError, match="empty_managed_guard_contract"):
            require_managed_guards(connection, ())


def test_sql_identity_preserves_literal_contents_and_boolean_grouping():
    from app.adapters.durable_schema.guards import sql_identity

    assert sql_identity("SELECT 'Ab  C'") != sql_identity("SELECT 'ab c'")
    assert sql_identity("a AND (b OR c)") != sql_identity("(a AND b) OR c")
    assert sql_identity(" SELECT\n1; ") == sql_identity("select 1")
    assert sql_identity("SELECT ab") != sql_identity("SELECT a b")


@pytest.fixture
def postgres_catalog():
    """Independent catalogue rows; only the verifier's two SELECTs are supported."""
    statements = (
        "CREATE OR REPLACE FUNCTION immutable_fact() RETURNS trigger LANGUAGE plpgsql "
        "AS $$ BEGIN RAISE EXCEPTION 'Immutable'; END; $$;",
        "CREATE TRIGGER immutable_update BEFORE UPDATE ON facts " "FOR EACH ROW EXECUTE FUNCTION immutable_fact();",
    )
    functions = [
        dict(
            proname="immutable_fact",
            arguments="",
            returns="trigger",
            lanname="plpgsql",
            provolatile="v",
            proparallel="u",
            prosrc="BEGIN RAISE EXCEPTION 'Immutable'; END;",
            prosecdef=False,
            proconfig=None,
            proisstrict=False,
            proleakproof=False,
            prokind="f",
        )
    ]
    triggers = [
        dict(
            tgname="immutable_update",
            relname="facts",
            tgtype=19,
            tgenabled="O",
            tgnargs=0,
            tgqual=None,
            tgdeferrable=False,
            tginitdeferred=False,
            proname="immutable_fact",
            local_function=True,
        )
    ]
    queries = []

    def execute(statement):
        sql = str(statement)
        queries.append(sql)
        assert sql.lstrip().startswith("SELECT ")
        if "FROM pg_trigger" in sql:
            assert "current_schema()" in sql and "NOT t.tgisinternal" in sql
            return SimpleNamespace(mappings=lambda: triggers)
        assert "FROM pg_proc" in sql and "current_schema()" in sql
        return SimpleNamespace(mappings=lambda: functions)

    connection = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), execute=execute)
    return SimpleNamespace(
        connection=connection, statements=statements, functions=functions, triggers=triggers, queries=queries
    )


def test_postgres_current_function_and_trigger_accept_catalogue_only(postgres_catalog):
    require_managed_guards(postgres_catalog.connection, postgres_catalog.statements)
    assert len(postgres_catalog.queries) == 2


@pytest.mark.parametrize("fault", [None, "missing_truncate", "row_truncate", "weakened_function"])
def test_model_fee_postgres_guard_contract_refuses_custody_drift(postgres_catalog, fault):
    from sqlalchemy.dialects import postgresql

    statements = model_fee_profile_guard_statements(postgresql.dialect())
    # Independently specified installed PostgreSQL catalogue, including the
    # statement-level TRUNCATE event. No DDL is allowed during verification.
    postgres_catalog.functions[0].update(
        proname="reject_model_fee_profile_mutation",
        prosrc="BEGIN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'model fee profile content is immutable'; END;",
    )
    template = postgres_catalog.triggers[0].copy()
    postgres_catalog.triggers[:] = [
        {
            **template,
            "tgname": f"trg_model_fee_profiles_immutable_{operation}",
            "relname": "composite_model_fee_profiles",
            "tgtype": event_type,
            "proname": "reject_model_fee_profile_mutation",
        }
        for operation, event_type in [("update", 19), ("delete", 11), ("truncate", 34)]
    ]
    if fault == "missing_truncate":
        postgres_catalog.triggers.pop()
    elif fault == "row_truncate":
        postgres_catalog.triggers[-1]["tgtype"] = 35
    elif fault == "weakened_function":
        postgres_catalog.functions[0]["prosrc"] = "BEGIN RETURN OLD; END;"
    if fault is None:
        require_managed_guards(postgres_catalog.connection, statements)
    else:
        with pytest.raises(DurableSchemaMigrationRequiredError):
            require_managed_guards(postgres_catalog.connection, statements)
    assert len(postgres_catalog.queries) == 2


@pytest.mark.parametrize("fault", [None, "row_level", "wrong_event", "disabled", "missing"])
def test_postgres_truncate_requires_exact_enabled_statement_guard(postgres_catalog, fault):
    statement = (
        "CREATE TRIGGER immutable_update BEFORE TRUNCATE ON facts "
        "FOR EACH STATEMENT EXECUTE FUNCTION immutable_fact();"
    )
    postgres_catalog.triggers[0]["tgtype"] = 34
    if fault == "row_level":
        postgres_catalog.triggers[0]["tgtype"] = 35
    elif fault == "wrong_event":
        postgres_catalog.triggers[0]["tgtype"] = 18
    elif fault == "disabled":
        postgres_catalog.triggers[0]["tgenabled"] = "D"
    elif fault == "missing":
        postgres_catalog.triggers.clear()
    statements = (postgres_catalog.statements[0], statement)
    if fault is None:
        require_managed_guards(postgres_catalog.connection, statements)
    else:
        with pytest.raises(DurableSchemaMigrationRequiredError, match="trigger:immutable_update"):
            require_managed_guards(postgres_catalog.connection, statements)


@pytest.mark.parametrize(
    "fault",
    [None, "missing_truncate", "row_truncate", "disabled", "missing_original", "foreign_tenant", "failed_result"],
)
def test_candidate_postgres_catalog_requires_original_custody_and_statement_truncate(postgres_catalog, fault):
    from sqlalchemy.dialects import postgresql

    from app.adapters.composite_result_candidate_schema import candidate_guard_statements

    # Installed catalog evidence is independent of the generated DDL. Runtime
    # admission must reject a weakened original-result predicate or mutation
    # event without installing or repairing any database objects.
    original_body = (
        "BEGIN IF NOT EXISTS (SELECT 1 FROM analytics_async_result r "
        "WHERE r.calculation_id = NEW.calculation_id AND r.tenant_id = NEW.tenant_id "
        "AND r.analytics_type = 'COMPOSITE_TWR_CANDIDATE' AND r.result_status = 'complete' "
        "AND r.response_json IS NOT NULL AND r.error_message IS NULL "
        "AND r.error_type IS NULL AND r.failure_json IS NULL) THEN "
        "RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite candidate original result is unavailable'; "
        "END IF; RETURN NEW; END;"
    )
    template_function = postgres_catalog.functions[0].copy()
    postgres_catalog.functions[:] = [
        dict(template_function, proname="require_composite_result_candidate_original", prosrc=original_body),
        dict(
            template_function,
            proname="reject_composite_result_candidate_mutation",
            prosrc="BEGIN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite result candidate is immutable'; END;",
        ),
    ]
    template_trigger = postgres_catalog.triggers[0].copy()
    postgres_catalog.triggers[:] = [
        dict(
            template_trigger,
            tgname="trg_composite_result_candidate_original",
            relname="composite_result_candidates",
            tgtype=7,
            proname="require_composite_result_candidate_original",
        ),
        *[
            dict(
                template_trigger,
                tgname=f"trg_composite_result_candidate_immutable_{operation}",
                relname="composite_result_candidates",
                tgtype=event_type,
                proname="reject_composite_result_candidate_mutation",
            )
            for operation, event_type in [("update", 19), ("delete", 11), ("truncate", 34)]
        ],
    ]
    if fault == "missing_truncate":
        postgres_catalog.triggers.pop()
    elif fault == "row_truncate":
        postgres_catalog.triggers[-1]["tgtype"] = 35
    elif fault == "disabled":
        postgres_catalog.triggers[-1]["tgenabled"] = "D"
    elif fault == "missing_original":
        postgres_catalog.triggers.pop(0)
    elif fault == "foreign_tenant":
        postgres_catalog.functions[0]["prosrc"] = original_body.replace("AND r.tenant_id = NEW.tenant_id ", "")
    elif fault == "failed_result":
        postgres_catalog.functions[0]["prosrc"] = original_body.replace("AND r.failure_json IS NULL", "")
    before = ([row.copy() for row in postgres_catalog.functions], [row.copy() for row in postgres_catalog.triggers])
    statements = candidate_guard_statements(postgresql.dialect())
    if fault is None:
        require_managed_guards(postgres_catalog.connection, statements)
    else:
        with pytest.raises(DurableSchemaMigrationRequiredError):
            require_managed_guards(postgres_catalog.connection, statements)
    assert (postgres_catalog.functions, postgres_catalog.triggers) == before
    assert len(postgres_catalog.queries) == 2


@pytest.mark.parametrize(
    "collection, field, value",
    [
        ("functions", "arguments", "tenant text"),
        ("functions", "returns", "boolean"),
        ("functions", "lanname", "sql"),
        ("functions", "provolatile", "i"),
        ("functions", "proparallel", "s"),
        ("functions", "prosrc", "BEGIN RETURN NEW; END;"),
        ("functions", "prosecdef", True),
        ("functions", "proconfig", ["search_path=public"]),
        ("functions", "proisstrict", True),
        ("functions", "proleakproof", True),
        ("functions", "prokind", "p"),
        ("triggers", "relname", "other_facts"),
        ("triggers", "tgtype", 17),
        ("triggers", "tgenabled", "D"),
        ("triggers", "tgnargs", 1),
        ("triggers", "tgqual", "tenant_id = 'allowed'"),
        ("triggers", "tgdeferrable", True),
        ("triggers", "tginitdeferred", True),
        ("triggers", "proname", "other_function"),
        ("triggers", "local_function", False),
    ],
)
def test_postgres_weakened_function_or_trigger_refuses_without_mutation(postgres_catalog, collection, field, value):
    rows = getattr(postgres_catalog, collection)
    rows[0][field] = value
    before = dict(rows[0])
    with pytest.raises(DurableSchemaMigrationRequiredError) as error:
        require_managed_guards(postgres_catalog.connection, postgres_catalog.statements)
    expected = "function:immutable_fact" if collection == "functions" else "trigger:immutable_update"
    assert error.value.issues == (expected,)
    assert rows[0] == before


@pytest.mark.parametrize("shape", ["missing_function", "overloaded_function", "missing_trigger", "unsupported_trigger"])
def test_postgres_ambiguous_or_missing_managed_identity_refuses(postgres_catalog, shape):
    if shape == "missing_function":
        postgres_catalog.functions.clear()
    elif shape == "overloaded_function":
        postgres_catalog.functions.append(dict(postgres_catalog.functions[0], arguments="value integer"))
    elif shape == "missing_trigger":
        postgres_catalog.triggers.clear()
    else:
        postgres_catalog.statements = (postgres_catalog.statements[0], "CREATE TRIGGER immutable_update AFTER UPDATE")
    with pytest.raises(DurableSchemaMigrationRequiredError):
        require_managed_guards(postgres_catalog.connection, postgres_catalog.statements)


@pytest.mark.parametrize("attributes", ["IMMUTABLE PARALLEL SAFE", "SECURITY DEFINER", "invalid syntax"])
def test_postgres_source_function_attributes_have_explicit_contract(postgres_catalog, attributes):
    function = postgres_catalog.statements[0].replace("LANGUAGE plpgsql", f"LANGUAGE plpgsql {attributes}")
    if attributes == "IMMUTABLE PARALLEL SAFE":
        postgres_catalog.functions[0].update(provolatile="i", proparallel="s")
        require_managed_guards(postgres_catalog.connection, (function, postgres_catalog.statements[1]))
    else:
        with pytest.raises(DurableSchemaMigrationRequiredError, match="function_contract"):
            require_managed_guards(postgres_catalog.connection, (function, postgres_catalog.statements[1]))


def test_postgres_unparseable_source_function_refuses(postgres_catalog):
    with pytest.raises(DurableSchemaMigrationRequiredError, match="unsupported_managed_function_contract"):
        require_managed_guards(
            postgres_catalog.connection, ("CREATE OR REPLACE FUNCTION invalid", postgres_catalog.statements[1])
        )


def test_unsupported_guard_dialect_refuses_before_catalogue_access():
    connection = SimpleNamespace(dialect=SimpleNamespace(name="unknown"))
    with pytest.raises(DurableSchemaMigrationRequiredError, match="unsupported_durable_dialect"):
        require_managed_guards(connection, ("CREATE TRIGGER managed",))
