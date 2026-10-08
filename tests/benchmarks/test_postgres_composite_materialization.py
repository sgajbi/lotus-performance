"""Real database proof; controlled source ports do not certify live upstream authority."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from app.adapters.composite_materialization_records import CompositeMaterializationModel
from app.adapters.composite_materialization_repository import (
    CompositeMaterializationStore,
    _store_cache,
    get_composite_materialization_store,
)
from app.adapters.composite_materialization_schema import CompositeMaterializationMigrationRequiredError
from app.adapters.composite_schema_policy import CANONICAL_REPORTING_CURRENCY_CHECK_SQL
from app.api.dependencies.composite_annual_dispersion import get_annual_dispersion_receipt_reader
from app.core.config import get_settings
from app.services.composite_materialization.application import run_materialization_attempt
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from core.errors import APIError, APINotFoundError
from engine.composites import calculate_asset_weighted_composite_twr
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url, owned_postgres_runtime_stores
from tests.composite_materialization_helpers import (
    INVALID_MATERIALIZATION_DATABASE_WRITES,
    MembershipSource,
    MemberSource,
    admitted,
    command_for,
    facts_for,
    running_job,
)
from tests.unit.adapters.test_composite_annual_dispersion_adapter import persist_records_in_stores
from tests.unit.services.test_composite_annual_comparison_service import candidate_records, pair_request
from tests.unit.services.test_composite_annual_dispersion_service import annual_request, year_records

CALLER_HEADERS = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}

ANNUAL_PATH = "/performance/composites/analytics"
COMPARISON_PATH = ANNUAL_PATH + "/comparison"


def _independent_annual_output(returns, *, population=False):
    values = [Fraction(value, 100) for value in returns]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) if population else len(values) - 1)
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        return (Decimal(variance.numerator) / Decimal(variance.denominator)).sqrt().quantize(Decimal("1e-12"))


def _retained_snapshot(engine):
    tables = (
        "composite_materializations",
        "composite_member_return_facts",
        "composite_member_return_fact_publications",
    )
    with engine.connect() as connection:
        return {
            table: sorted((tuple(row) for row in connection.execute(text(f"SELECT * FROM {table}"))), key=repr)
            for table in tables
        }


@contextmanager
def _default_annual_pg_client(url, monkeypatch):
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert get_annual_dispersion_receipt_reader not in app.dependency_overrides
    store = get_composite_materialization_store()
    assert store._engine.dialect.name == "postgresql"
    assert store._engine.url == make_url(url)
    with store._engine.connect() as connection:
        assert len(inspect(connection).get_table_names()) == 13
    before = _retained_snapshot(store._engine)
    reads = []

    def require_read_only(connection, cursor, statement, parameters, context, executemany):
        if connection.engine.url == make_url(url):
            assert statement.lstrip().split(None, 1)[0].upper() in {"SELECT", "SHOW"}, statement
            reads.append(statement)

    event.listen(Engine, "before_cursor_execute", require_read_only)
    try:
        with TestClient(app, headers=CALLER_HEADERS) as client:
            yield client, store
        assert any("composite_materializations" in statement for statement in reads)
        assert _retained_snapshot(store._engine) == before
    finally:
        event.remove(Engine, "before_cursor_execute", require_read_only)
        if _store_cache.get(url) is store:
            _store_cache.pop(url)
        store.close()


@pytest.mark.parametrize("method", ["EQUAL_WEIGHT_SAMPLE_STDDEV", "YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV"])
def test_postgres_default_annual_http_oracles_population_reversal_and_read_only(
    postgres_materialization_stores, monkeypatch, method
):
    url, ledger, facts, _ = postgres_materialization_stores
    baseline, candidate = year_records(), candidate_records(count=7, excluded=("6",))
    persist_records_in_stores(baseline + candidate, ledger=ledger, facts=facts)
    payload = pair_request(baseline, candidate).model_dump(mode="json")
    payload["baseline"]["method"] = payload["candidate"]["method"] = method
    population = method == "YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV"
    expected_baseline = _independent_annual_output([1, 2, 3, 4, 5, 6], population=population)
    expected_candidate = _independent_annual_output([1, 2, 3, 4, 5, 7], population=population)
    with _default_annual_pg_client(url, monkeypatch) as (client, _):
        annual = client.post(ANNUAL_PATH, json=payload["baseline"])
        response = client.post(COMPARISON_PATH, json=payload)
        assert annual.status_code == response.status_code == 200, response.text
        result = response.json()
        assert result["baseline"] == annual.json()
        assert Decimal(result["baseline"]["value"]) == expected_baseline
        assert Decimal(result["candidate"]["value"]) == expected_candidate
        assert Decimal(result["value"]) == expected_candidate - expected_baseline
        assert result["full_year_members_added"] == ["7"] and result["full_year_members_removed"] == ["6"]
        assert {item["materialization_id"] for item in result["baseline"]["months"]} == set(
            payload["baseline"]["materialization_ids"]
        )
        assert result["candidate"]["full_year_member_count"] == result["candidate"]["year_end_member_count"] == 6
        reverse = client.post(
            COMPARISON_PATH, json={"baseline": payload["candidate"], "candidate": payload["baseline"]}
        )
        assert reverse.status_code == 200
        assert Decimal(reverse.json()["value"]) == expected_baseline - expected_candidate
        assert reverse.json()["full_year_members_added"] == ["6"]
        reordered = {
            side: {**request, "materialization_ids": request["materialization_ids"][::-1]}
            for side, request in payload.items()
        }
        assert client.post(COMPARISON_PATH, json=reordered).json() == result


@pytest.mark.parametrize("shape", ["partial-year", "unavailable", "zero"])
def test_postgres_default_annual_http_population_null_and_zero(postgres_materialization_stores, monkeypatch, shape):
    url, ledger, facts, _ = postgres_materialization_stores
    baseline = year_records()
    if shape == "partial-year":
        candidate = candidate_records()
        candidate[5] = candidate_records(excluded=("6",))[5]
    elif shape == "unavailable":
        candidate = candidate_records(count=1)
    else:
        candidate = candidate_records(corrected=True, count=7, excluded=("2", "3", "4", "5", "6"))
    persist_records_in_stores(baseline + candidate, ledger=ledger, facts=facts)
    with _default_annual_pg_client(url, monkeypatch) as (client, _):
        response = client.post(COMPARISON_PATH, json=pair_request(baseline, candidate).model_dump(mode="json"))
        assert response.status_code == 200, response.text
        result = response.json()
        if shape == "partial-year":
            assert result["candidate"]["full_year_member_count"] == 5
            assert result["candidate"]["year_end_member_count"] == 6
            assert Decimal(result["candidate"]["value"]) == _independent_annual_output([1, 2, 3, 4, 5])
            assert result["full_year_members_removed"] == ["6"]
        elif shape == "unavailable":
            assert result["candidate"]["value"] is result["value"] is None
            assert result["status"] == "UNAVAILABLE"
            assert result["reason_codes"] == ["CANDIDATE_ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS"]
        else:
            assert result["candidate"]["full_year_member_count"] == 2
            assert Decimal(result["candidate"]["value"]) == 0
            assert result["status"] == "AVAILABLE" and result["reason_codes"] == []
            assert Decimal(result["value"]) == -_independent_annual_output([1, 2, 3, 4, 5, 6])


def test_postgres_default_annual_http_close_reopen_pins_original_and_changed_evidence(
    postgres_materialization_stores, monkeypatch
):
    url, ledger, facts, _ = postgres_materialization_stores
    original, corrected = year_records(), year_records(corrected=True)
    persist_records_in_stores(original, ledger=ledger, facts=facts)
    request = annual_request(original).model_dump(mode="json")
    with _default_annual_pg_client(url, monkeypatch) as (client, first_store):
        old = client.post(ANNUAL_PATH, json=request)
        assert old.status_code == 200
        old_result = old.json()
    persist_records_in_stores(corrected, ledger=ledger, facts=facts)
    pair = pair_request(original, corrected).model_dump(mode="json")
    with _default_annual_pg_client(url, monkeypatch) as (client, reopened_store):
        assert reopened_store is not first_store and reopened_store._engine is not first_store._engine
        assert client.post(ANNUAL_PATH, json=request).json() == old_result
        updated = client.post(COMPARISON_PATH, json=pair)
        assert updated.status_code == 200
        comparison = updated.json()
        assert comparison["baseline"] == old_result
        assert Decimal(comparison["value"]) == 0
        assert comparison["baseline"]["result_fingerprint"] != comparison["candidate"]["result_fingerprint"]
        assert comparison["baseline"]["members"][0]["annual_return"] == "0.01"
        assert comparison["candidate"]["members"][0]["annual_return"] == "0.07"
    with _default_annual_pg_client(url, monkeypatch) as (client, _):
        assert client.post(COMPARISON_PATH, json=pair).json() == comparison


def test_postgres_default_annual_http_two_tenant_authority(postgres_materialization_stores, monkeypatch):
    url, ledger, facts, _ = postgres_materialization_stores
    tenants = {"tenant-a": year_records(), "tenant-b": year_records(count=5, tenant="tenant-b")}
    for tenant, records in tenants.items():
        persist_records_in_stores(records, ledger=ledger, facts=facts, tenant_id=tenant)
    with _default_annual_pg_client(url, monkeypatch) as (client, _):
        results = []
        for tenant, records in tenants.items():
            own = client.post(
                COMPARISON_PATH,
                json=pair_request(records, records).model_dump(mode="json"),
                headers={"X-Tenant-Id": tenant},
            )
            assert own.status_code == 200, own.text
            results.append(own.json())
            foreign = tenants["tenant-b" if tenant == "tenant-a" else "tenant-a"]
            refused = client.post(
                COMPARISON_PATH,
                json=pair_request(foreign, foreign).model_dump(mode="json"),
                headers={"X-Tenant-Id": tenant},
            )
            assert refused.status_code == 404
            assert "baseline" not in refused.json() and "candidate" not in refused.json()
        assert results[0]["result_fingerprint"] != results[1]["result_fingerprint"]
        assert results[0]["baseline"]["full_year_member_count"] == 6
        assert results[1]["baseline"]["full_year_member_count"] == 5


@pytest.mark.parametrize("fault", ["incomplete", "corrupt", "policy"])
def test_postgres_default_annual_http_refuses_retained_fault_without_partial_pair(
    postgres_materialization_stores, monkeypatch, fault
):
    url, ledger, facts, _ = postgres_materialization_stores
    baseline = year_records()
    candidate = candidate_records(count=5, **({"policy_version": "policy.v2"} if fault == "policy" else {}))
    persist_records_in_stores(baseline + candidate, ledger=ledger, facts=facts)
    payload = pair_request(baseline, candidate).model_dump(mode="json")
    with _default_annual_pg_client(url, monkeypatch) as (client, _):
        control = client.post(COMPARISON_PATH, json=pair_request(baseline, baseline).model_dump(mode="json"))
        assert control.status_code == 200
    if fault != "policy":
        with ledger._engine.begin() as connection:
            connection.execute(
                update(CompositeMaterializationModel)
                .where(
                    CompositeMaterializationModel.tenant_id == "tenant-a",
                    CompositeMaterializationModel.materialization_id == str(candidate[0].command.materialization_id),
                )
                .values(**({"state": "WAITING"} if fault == "incomplete" else {"source_json": "{}"}))
            )
    expected = {
        "incomplete": (409, "ANNUAL_DISPERSION_MONTH_NOT_COMPLETE"),
        "corrupt": (503, "COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED"),
        "policy": (422, "ANNUAL_COMPARISON_POLICY_BASIS_MISMATCH"),
    }
    with _default_annual_pg_client(url, monkeypatch) as (client, _):
        refused = client.post(COMPARISON_PATH, json=payload)
        status, code = expected[fault]
        assert refused.status_code == status, refused.text
        assert refused.json()["error_code"] == code
        assert "baseline" not in refused.json() and "candidate" not in refused.json()
        assert (
            client.post(COMPARISON_PATH, json=pair_request(baseline, baseline).model_dump(mode="json")).json()
            == control.json()
        )


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
def postgres_materialization_stores(monkeypatch):
    url = get_postgres_database_url()
    assert apply_durable_schema(database_url=url).status == "passed"
    with owned_postgres_runtime_stores(url, monkeypatch):
        ledger, facts, jobs = CompositeMaterializationStore(url), CompositeMetadataStore(url), ComputeJobStore(url)
        try:
            yield url, ledger, facts, jobs
        finally:
            ledger.close()
            facts.close()
            jobs._engine.dispose()


@pytest.mark.parametrize("eod_flow", ["0", "10"], ids=["no-flow", "economic-date-flow"])
def test_postgres_registered_fx_normalization_money_replay_and_rederivation(
    postgres_materialization_stores, monkeypatch, eod_flow
):
    from tests.integration.test_composite_materialization_api import (
        test_registered_materialization_refuses_translated_return_without_converted_source_money as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    # Reuse the exact registered HTTP/worker/oracle control against an owned real
    # database. Source ports remain synthetic; this is an in-process store reopen.
    registered_control(monkeypatch=monkeypatch, normalize=True, eod_flow=eod_flow)


@pytest.mark.parametrize(
    "fault, code",
    [
        ("missing-member", "COMPOSITE_FX_SOURCE_SCOPE_MISMATCH"),
        ("zero-rate", "COMPOSITE_FX_SOURCE_WIRE_REFUSED"),
        ("reversed-direction", "COMPOSITE_FX_SOURCE_WIRE_REFUSED"),
    ],
)
def test_postgres_registered_fx_normalization_population_refusals(
    postgres_materialization_stores, monkeypatch, fault, code
):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_source_refusal_retains_admitted_eligible_population as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch, fault, code)


@pytest.mark.parametrize("rounding", [6, 12])
def test_postgres_registered_fx_normalization_float_projection(postgres_materialization_stores, monkeypatch, rounding):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_preserves_float_return_projection_and_exact_money as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch, rounding)


def test_postgres_registered_fx_normalization_actual_fee_views(postgres_materialization_stores, monkeypatch):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_converts_actual_fee_without_changing_money_between_views as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch)


def test_postgres_registered_fx_normalization_temporary_source_recovery(postgres_materialization_stores, monkeypatch):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_recovers_exact_pending_source_after_temporary_outage as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch)


@pytest.mark.parametrize("mismatch", ["fx-method", "policy", "native-regime"])
def test_postgres_registered_fx_normalization_incompatible_admitted_windows(
    postgres_materialization_stores, monkeypatch, mismatch
):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_refuses_independently_admitted_incompatible_windows as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch, mismatch)


@pytest.mark.parametrize("native_currency", ["EUR", "GBP"])
def test_postgres_registered_fx_normalization_different_native_currency(
    postgres_materialization_stores, monkeypatch, native_currency
):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_reports_independently_admitted_native_composite_in_usd as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch, native_currency)


def test_postgres_registered_fx_normalization_wrong_native_refusal(postgres_materialization_stores, monkeypatch):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_refuses_wrong_native_source_without_losing_manage_population as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch)


def test_postgres_registered_fx_normalization_native_currency_adjacent_periods(
    postgres_materialization_stores, monkeypatch
):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_links_native_eur_windows_in_usd_without_resetting_history as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch)


def test_postgres_registered_fx_normalization_adjacent_periods(postgres_materialization_stores, monkeypatch):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_links_adjacent_periods_without_resetting_inception as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch)


def test_postgres_registered_fx_normalization_positive_two_tenants(postgres_materialization_stores, monkeypatch):
    from tests.integration.test_composite_materialization_api import (
        test_registered_fx_normalization_keeps_positive_tenant_populations_separate as registered_control,
    )

    url, ledger, _, _ = postgres_materialization_stores
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    registered_control(monkeypatch)


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


def _authority_migration_snapshot(engine):
    with engine.connect() as connection:
        inspector = inspect(connection)
        table = "composite_member_return_facts"
        return {
            "rows": [dict(row) for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()],
            "columns": [{**column, "type": str(column["type"])} for column in inspector.get_columns(table)],
            "indexes": inspector.get_indexes(table),
            "foreign_keys": inspector.get_foreign_keys(table),
            "checks": inspector.get_check_constraints(table),
        }


def _prepare_internal_authority_migration(url):
    from app.services.composite_materialization.source_contract import ManageCompositeDefinition
    from tests.composite_materialization_helpers import source_products

    assert apply_durable_schema(database_url=url).status == "passed"
    store = CompositeMetadataStore(url)
    products = source_products(composite_id="MIGRATION_STORAGE_FIXTURE")
    command = command_for(products)
    # Representative retained v1 storage fixture, not evidence of a live calculation.
    fact = (
        MemberSource()
        .read_member(
            command,
            command.member_calculations[0],
            tenant_id="tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
        )
        .fact
    )
    store.upsert_definition(
        ManageCompositeDefinition.model_validate(products[0]).performance_definition(), tenant_id="tenant-a"
    )
    store.upsert_member_return_fact(fact, tenant_id="tenant-a")
    with store._engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE composite_member_return_facts DROP CONSTRAINT ck_composite_fact_internal_evidence"
        )
        connection.exec_driver_sql(
            "ALTER TABLE composite_member_return_facts DROP COLUMN source_authority_identity_json"
        )
        connection.exec_driver_sql(
            "ALTER TABLE composite_member_return_facts ALTER COLUMN ending_market_value SET NOT NULL"
        )
        connection.exec_driver_sql("ALTER TABLE composite_member_return_facts ALTER COLUMN calculation_id SET NOT NULL")
    return store


def _insert_authority_storage_mutant(connection, **changes):
    from app.services.composite_metadata_store import CompositeMemberReturnFactModel

    row = dict(connection.execute(text("SELECT * FROM composite_member_return_facts LIMIT 1")).mappings().one())
    row.update(
        fact_key=row["fact_key"] + ".invalid",
        restatement_sequence=row["restatement_sequence"] + 1,
        restatement_version="invalid.storage.fixture",
        **changes,
    )
    connection.execute(CompositeMemberReturnFactModel.__table__.insert().values(**row))


def test_postgres_authority_fact_owner_upgrade_preserves_populated_internal_rows_and_constraints():
    url = get_postgres_database_url()
    store = _prepare_internal_authority_migration(url)
    try:
        before = _authority_migration_snapshot(store._engine)
        assert apply_durable_schema(database_url=url).status == "passed"
        after = _authority_migration_snapshot(store._engine)
        assert [
            {k: v for k, v in row.items() if k != "source_authority_identity_json"} for row in after["rows"]
        ] == before["rows"]
        assert after["rows"][0]["source_authority_identity_json"] is None
        assert after["indexes"] == before["indexes"] and after["foreign_keys"] == before["foreign_keys"]
        assert {c["name"] for c in before["checks"]} <= {c["name"] for c in after["checks"]}
        assert all(c["nullable"] for c in after["columns"] if c["name"] in {"ending_market_value", "calculation_id"})
        for changes, constraint in (
            ({"calculation_id": None}, "ck_composite_fact_internal_evidence"),
            ({"composite_id": "FOREIGN_DEFINITION"}, "fk_composite_member_return_facts_tenant_definition"),
        ):
            with pytest.raises(DBAPIError) as refused:
                with store._engine.begin() as connection:
                    _insert_authority_storage_mutant(connection, **changes)
            assert refused.value.orig.diag.constraint_name == constraint
        assert apply_durable_schema(database_url=url).status == "passed"
        assert _authority_migration_snapshot(store._engine) == after
    finally:
        store.close()


@pytest.mark.parametrize("fault", ["weakened", "invalid_partial"])
def test_postgres_authority_fact_owner_refusal_rolls_back_schema_and_rows(fault):
    url = get_postgres_database_url()
    store = _prepare_internal_authority_migration(url)
    try:
        with store._engine.begin() as connection:
            if fault == "weakened":
                connection.exec_driver_sql(
                    "ALTER TABLE composite_member_return_facts ADD CONSTRAINT ck_composite_fact_internal_evidence CHECK (1=1)"
                )
            else:
                connection.exec_driver_sql(
                    "ALTER TABLE composite_member_return_facts ALTER COLUMN ending_market_value DROP NOT NULL"
                )
                connection.exec_driver_sql(
                    "ALTER TABLE composite_member_return_facts ALTER COLUMN calculation_id DROP NOT NULL"
                )
                _insert_authority_storage_mutant(connection, calculation_id=None, ending_market_value=None)
        before = _authority_migration_snapshot(store._engine)
        if fault == "weakened":
            refused = apply_durable_schema(database_url=url)
            assert refused.status == "failed" and refused.bootstrap_error
        else:
            assert any(row["ending_market_value"] is None and row["calculation_id"] is None for row in before["rows"])
            with pytest.raises(DBAPIError) as refused:
                apply_durable_schema(database_url=url)
            assert refused.value.orig.diag.constraint_name == "ck_composite_fact_internal_evidence"
        assert _authority_migration_snapshot(store._engine) == before
    finally:
        store.close()


def _provider_process_phase(
    state_path, database_url, phase, evidence_dir, *, module="tests.benchmarks.composite_provider_process_controls"
):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    environment = {
        **os.environ,
        "LINEAGE_METADATA_DATABASE_URL": database_url,
        "LOTUS_POSTGRES_PLAN_DATABASE_URL": database_url,
        "MANAGE_BASE_URL": "http://manage-process-control",
        "LINEAGE_STORAGE_PATH": str(evidence_dir / "lineage"),
    }
    if phase == "waiting":
        environment["COMPUTE_EXECUTOR_MAX_ATTEMPTS"] = "1"
    command = [
        sys.executable,
        "-m",
        module,
        "--state",
        str(state_path),
        "--phase",
        phase,
    ]
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    (evidence_dir / f"{phase}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (evidence_dir / f"{phase}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.splitlines()[-1])


@pytest.mark.parametrize("eod_flow", ["0", "10"], ids=["no-flow", "economic-date-flow"])
def test_postgres_registered_fx_normalization_fresh_process_receipts(
    postgres_materialization_stores, tmp_path, eod_flow
):
    import json

    url, _, _, _ = postgres_materialization_stores
    state_path = tmp_path / "fx-state.json"
    state_path.write_text(json.dumps({"eod_flow": eod_flow}), encoding="utf-8")
    module = "tests.benchmarks.composite_fx_process_controls"
    write = _provider_process_phase(state_path, url, "write", tmp_path, module=module)
    read = _provider_process_phase(state_path, url, "read", tmp_path, module=module)
    assert write["pid"] != read["pid"]
    for version in ("original", "corrected"):
        assert write["result"][version]["receipt"] == read["result"][version]["receipt"]
        assert write["result"][version]["periods"] == read["result"][version]["periods"]
        assert read["result"][version]["default_verifier_status"] == 503
    proof = {
        "write": write,
        "read": read,
        "database_schema": make_url(url).query["options"],
        "qualification": "CONTROLLED_SYNTHETIC_ONLY",
    }
    (tmp_path / "fx-process-proof.json").write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")


def test_postgres_registered_external_oracles_pinned_vector_and_snapshot(tmp_path):
    import json

    url = get_postgres_database_url()
    assert apply_durable_schema(database_url=url).status == "passed"
    state_path = tmp_path / "oracle-state.json"
    state_path.write_text("{}", encoding="utf-8")
    module = "tests.benchmarks.composite_oracle_process_controls"
    write = _provider_process_phase(state_path, url, "write", tmp_path, module=module)
    read = _provider_process_phase(state_path, url, "read", tmp_path, module=module)
    assert write["pid"] != read["pid"]
    assert write["result"]["oracles"] == read["result"]["oracles"]
    assert read["result"]["snapshot"]["isolation"] == "REPEATABLE READ"
    assert read["result"]["snapshot"]["before"] == read["result"]["snapshot"]["after"] == 2
    assert read["result"]["snapshot"]["outside"] == 3
    proof = {
        "write": write,
        "read": read,
        "database_schema": make_url(url).query["options"],
        "qualification": "CONTROLLED_SYNTHETIC_ONLY",
    }
    (tmp_path / "oracle-process-proof.json").write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("shape", ["frozen", "explicit_observations"])
def test_postgres_registered_provider_default_worker_fresh_process_replay_and_recovery(shape, tmp_path):
    import json
    from uuid import uuid4

    from tests.benchmarks.composite_provider_process_controls import packets_for
    from tests.composite_authority_helpers import command_for_packet

    url = get_postgres_database_url()
    assert apply_durable_schema(database_url=url).status == "passed"
    original, corrected = packets_for(shape)[0]
    commands = {
        "original": command_for_packet(original),
        "corrected": command_for_packet(corrected, restatement_sequence=2),
        "waiting": command_for_packet(corrected, restatement_sequence=3),
    }
    commands["recover"] = commands["waiting"].model_copy(update={"calculation_id": uuid4()})
    state_path = tmp_path / "commands.json"
    state_path.write_text(
        json.dumps(
            {"shape": shape, "commands": {key: command.model_dump(mode="json") for key, command in commands.items()}},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    outputs = {}
    for phase in ("original", "corrected", "read", "waiting", "recover"):
        outputs[phase] = _provider_process_phase(state_path, url, phase, tmp_path)
    assert len({output["pid"] for output in outputs.values()}) == len(outputs)
    assert outputs["read"]["result"]["original"] == outputs["original"]["result"]
    assert outputs["read"]["result"]["corrected"] == outputs["corrected"]["result"]
    assert outputs["recover"]["result"]["weighted_return"] == outputs["corrected"]["result"]["weighted_return"]
    assert commands["waiting"].materialization_id == commands["recover"].materialization_id
    assert commands["waiting"].calculation_id != commands["recover"].calculation_id
    summary = {
        "shape": shape,
        "database_schema": make_url(url).query["options"],
        "phases": outputs,
        "qualification": "CONTROLLED_SYNTHETIC_ONLY",
    }
    (tmp_path / "process-proof.json").write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "fresh_process_proof": str(tmp_path / "process-proof.json"),
                "phase_pids": {key: output["pid"] for key, output in outputs.items()},
            },
            sort_keys=True,
        )
    )
