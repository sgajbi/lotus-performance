"""Real database proof; controlled source ports do not certify live upstream authority."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import DBAPIError

from app.adapters.composite_materialization_repository import (
    CompositeMaterializationStore,
    get_composite_materialization_store,
)
from app.adapters.composite_materialization_schema import CompositeMaterializationMigrationRequiredError
from app.adapters.composite_schema_policy import CANONICAL_REPORTING_CURRENCY_CHECK_SQL
from app.core.config import get_settings
from app.services.composite_materialization.application import run_materialization_attempt
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from core.errors import APIError, APINotFoundError
from engine.composites import calculate_asset_weighted_composite_twr
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
from tests.composite_materialization_helpers import (
    INVALID_MATERIALIZATION_DATABASE_WRITES,
    MembershipSource,
    MemberSource,
    admitted,
    command_for,
    facts_for,
    running_job,
)

CALLER_HEADERS = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}


@pytest.mark.parametrize("shape", ["partial", "weakened-check", "global-key", "nullable-actor", "locale-currency"])
def test_postgres_materialization_schema_refuses_incompatible_restore_without_repair(
    postgres_materialization_stores, shape
):
    _, ledger, facts, _ = postgres_materialization_stores
    ledger.create_schema()
    facts.create_schema()  # Current populated bootstrap remains repeatable.
    statements = {
        "partial": ["ALTER TABLE composite_materializations DROP COLUMN actor_id"],
        "weakened-check": [
            "ALTER TABLE composite_materializations DROP CONSTRAINT ck_composite_materialization_revision",
            "ALTER TABLE composite_materializations ADD CONSTRAINT ck_composite_materialization_revision CHECK (revision >= -100)",
        ],
        "global-key": [
            "ALTER TABLE composite_materializations DROP CONSTRAINT composite_materializations_pkey",
            "ALTER TABLE composite_materializations ADD PRIMARY KEY (materialization_id)",
        ],
        "nullable-actor": ["ALTER TABLE composite_materializations ALTER COLUMN actor_id DROP NOT NULL"],
        "locale-currency": [
            "ALTER TABLE composite_materializations DROP CONSTRAINT ck_composite_materialization_currency",
            "ALTER TABLE composite_materializations ADD CONSTRAINT ck_composite_materialization_currency CHECK ("
            + CANONICAL_REPORTING_CURRENCY_CHECK_SQL
            + ")",
        ],
    }
    with ledger._engine.begin() as connection:
        for statement in statements[shape]:
            connection.exec_driver_sql(statement)
        original = inspect(connection).get_check_constraints("composite_materializations")
    for store in (ledger, facts):
        with pytest.raises(CompositeMaterializationMigrationRequiredError):
            store.create_schema()
    with ledger._engine.connect() as connection:
        assert inspect(connection).get_check_constraints("composite_materializations") == original


@pytest.mark.parametrize("field,value", INVALID_MATERIALIZATION_DATABASE_WRITES)
def test_postgres_materialization_database_refuses_malformed_scope_and_progress(
    postgres_materialization_stores, field, value
):
    _, ledger, _, _ = postgres_materialization_stores
    command = command_for()
    original = ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    with pytest.raises(DBAPIError), ledger._engine.begin() as connection:
        connection.execute(
            text(f"UPDATE composite_materializations SET {field}=:value WHERE materialization_id=:identity"),
            {"value": value, "identity": str(command.materialization_id)},
        )
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == original


def test_postgres_http_admission_rolls_back_after_queue_write_and_retries(monkeypatch, postgres_materialization_stores):
    url, ledger, _, jobs = postgres_materialization_stores
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    command = command_for()
    original = ComputeJobStore.register_job

    def fail_after_write(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError("Controlled PostgreSQL admission fault after queue write")

    with TestClient(app, headers=CALLER_HEADERS, raise_server_exceptions=False) as client:
        with monkeypatch.context() as fault:
            fault.setattr(ComputeJobStore, "register_job", fail_after_write)
            response = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert response.status_code == 500, response.text
        with pytest.raises(APINotFoundError):
            ledger.get(command.materialization_id, tenant_id="tenant-a")
        executions = ExecutionRegistry(url)
        try:
            assert executions.get_execution(command.calculation_id) is None
            assert jobs.get_job(command.calculation_id) is None
            accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
            assert accepted.status_code == 202, accepted.text
            assert executions.get_execution(command.calculation_id).tenant_id == "tenant-a"
            assert jobs.get_job(command.calculation_id).tenant_id == "tenant-a"
            assert ledger.get(command.materialization_id, tenant_id="tenant-a").state == "WAITING"
        finally:
            executions._engine.dispose()


def test_postgres_http_admission_contention_never_exposes_partial_rows(monkeypatch, postgres_materialization_stores):
    url, ledger, _, _ = postgres_materialization_stores
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    owner = get_composite_materialization_store(database_url=url)
    command = command_for()
    held, contender_started, release = Event(), Event(), Event()
    backend_pids = []

    def hold_queue_insert(connection, cursor, statement, parameters, context, executemany):
        if "INSERT INTO analytics_compute_job" in statement and not held.is_set():
            held.set()
            assert release.wait(15), "Holding submission was not released"

    def observe_contender(connection, cursor, statement, parameters, context, executemany):
        if held.is_set() and "pg_advisory_xact_lock(" in statement:
            backend_pids.append(connection.scalar(text("SELECT pg_backend_pid()")))
            contender_started.set()

    event.listen(owner._engine, "after_cursor_execute", hold_queue_insert)
    event.listen(owner._engine, "before_cursor_execute", observe_contender)
    try:
        with TestClient(app, headers=CALLER_HEADERS) as client, ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                client.post, "/performance/composites/materializations", json=command.model_dump(mode="json")
            )
            try:
                assert held.wait(10)
                with ledger._engine.connect() as independent_reader:
                    for table in ("composite_materializations", "analytics_execution", "analytics_compute_job"):
                        assert independent_reader.scalar(text(f"SELECT count(*) FROM {table}")) == 0
                second = executor.submit(
                    client.post, "/performance/composites/materializations", json=command.model_dump(mode="json")
                )
                assert contender_started.wait(10)
                _observe_waiting_lock(ledger._engine, backend_pids[0])
            finally:
                release.set()
            for response in (first.result(timeout=10), second.result(timeout=10)):
                assert response.status_code == 202, response.text
            with ledger._engine.connect() as independent_reader:
                for table in ("composite_materializations", "analytics_execution", "analytics_compute_job"):
                    assert independent_reader.scalar(text(f"SELECT count(*) FROM {table}")) == 1
    finally:
        release.set()
        event.remove(owner._engine, "after_cursor_execute", hold_queue_insert)
        event.remove(owner._engine, "before_cursor_execute", observe_contender)


@pytest.fixture
def postgres_materialization_stores():
    url = get_postgres_database_url()
    assert apply_durable_schema(database_url=url).status == "passed"
    ledger, facts, jobs = CompositeMaterializationStore(url), CompositeMetadataStore(url), ComputeJobStore(url)
    try:
        yield url, ledger, facts, jobs
    finally:
        ledger.close()
        facts.close()
        jobs._engine.dispose()


def _observe_waiting_lock(engine, backend_pid):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        with engine.connect() as connection:
            waiting = connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted)"),
                {"pid": backend_pid},
            )
        if waiting:
            return
        sleep(0.05)
    pytest.fail("Contender never waited on the actual PostgreSQL advisory lock")


def test_postgres_materialization_chronology_serializes_observed_contention(postgres_materialization_stores):
    url, ledger, _, _ = postgres_materialization_stores
    contender = CompositeMaterializationStore(url)
    high, low = command_for(restatement_sequence=2), command_for(restatement_sequence=1)
    held, contender_started, release = Event(), Event(), Event()
    backend_pids = []

    def hold_reserved_scope(connection, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock(" in statement and not held.is_set():
            held.set()
            assert release.wait(15), "Holding writer was not released"

    def record_contender(connection, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock(" in statement:
            backend_pids.append(connection.scalar(text("SELECT pg_backend_pid()")))
            contender_started.set()

    event.listen(ledger._engine, "after_cursor_execute", hold_reserved_scope)
    event.listen(contender._engine, "before_cursor_execute", record_contender)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(ledger.register, high, tenant_id="tenant-a", actor_id="operator")
            try:
                assert held.wait(10)
                second = executor.submit(contender.register, low, tenant_id="tenant-a", actor_id="operator")
                assert contender_started.wait(10)
                _observe_waiting_lock(ledger._engine, backend_pids[0])
            finally:
                release.set()
            assert first.result(timeout=10).command.restatement_sequence == 2
            with pytest.raises(APIError) as refusal:
                second.result(timeout=10)
            assert refusal.value.error_code == "COMPOSITE_MATERIALIZATION_SCOPE_CONFLICT"
        with pytest.raises(APINotFoundError):
            ledger.get(low.materialization_id, tenant_id="tenant-a")
        assert contender.register(low, tenant_id="tenant-b", actor_id="other-operator").actor_id == "other-operator"
    finally:
        release.set()
        event.remove(ledger._engine, "after_cursor_execute", hold_reserved_scope)
        event.remove(contender._engine, "before_cursor_execute", record_contender)
        contender.close()


def test_postgres_materialization_restart_recovers_missing_member_without_partial_release(
    postgres_materialization_stores,
):
    url, ledger, facts, jobs = postgres_materialization_stores
    command = command_for()
    job = running_job(jobs, command)
    source, members = MembershipSource(admitted(command)), MemberSource(missing="C")
    with pytest.raises(APIError) as waiting:
        run_materialization_attempt(
            job, job_store=jobs, ledger=ledger, facts=facts, membership_source=source, member_source=members
        )
    assert waiting.value.retryable
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0
    ledger.close()
    restarted = CompositeMaterializationStore(url)
    try:
        retained = restarted.get(command.materialization_id, tenant_id="tenant-a")
        assert [item.state.value for item in retained.outcomes] == ["READY", "READY", "WAITING"]
        members.missing = None
        completed = run_materialization_attempt(
            job, job_store=jobs, ledger=restarted, facts=facts, membership_source=source, member_source=members
        )
        assert completed.state == "COMPLETE" and source.reads == 1
        assert members.reads == ["A", "B", "C", "C"]
        result = calculate_asset_weighted_composite_twr(composite_id="COMPOSITE", member_return_facts=facts_for(facts))
        assert result.period_results[0].return_value == (Decimal(14) / Decimal(600)).quantize(Decimal("0.000000000001"))
        assert facts.count_records(tenant_id="tenant-a").member_return_facts == 3
        with pytest.raises(APINotFoundError):
            restarted.get(command.materialization_id, tenant_id="tenant-b")
    finally:
        restarted.close()
