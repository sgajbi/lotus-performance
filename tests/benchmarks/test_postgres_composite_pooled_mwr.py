"""Actual PostgreSQL custody guards and competing active-claim transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services.async_result_store import AsyncResultOriginalConflictError, AsyncResultStore
from app.services.compute_job_store import ComputeJobLeaseOwnershipError
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
from tests.integration.test_composite_pooled_mwr_api import (
    pooled_api_runtime as _api_runtime_fixture,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_audit_uses_verified_principal_and_ignores_header_grants as _assert_registered_audit,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_authority_refuses_before_financial_source_read as _assert_registered_authority,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_correction_preserves_both_originals as _assert_registered_correction,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_cors_preflight_precedes_principal as _assert_preflight,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_duplicate_authorization_refuses_before_source as _assert_duplicate_authorization,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_missing_terminal_records_operational_failure_only as _assert_registered_missing_terminal,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_original_worker_and_source_independent_replay as _assert_registered_original,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_retry_reuses_snapshot_after_transient_solver_failure as _assert_registered_retry,
)
from tests.integration.test_composite_pooled_mwr_api import (
    test_registered_pooled_streamed_size_limit_preserves_security_headers as _assert_streamed_size,
)
from tests.integration.test_composite_pooled_mwr_worker import (
    _bind,
)
from tests.integration.test_composite_pooled_mwr_worker import (
    custody as _custody_fixture,
)
from tests.integration.test_composite_pooled_mwr_worker import (
    test_custody_conflicting_request_cannot_replace_original as _assert_conflict,
)
from tests.integration.test_composite_pooled_mwr_worker import (
    test_custody_replays_original_after_reopening_store_and_is_tenant_scoped as _assert_replay,
)
from tests.integration.test_composite_pooled_mwr_worker import (
    test_custody_rolls_back_when_active_claim_transaction_fails as _assert_rollback,
)
from tests.integration.test_composite_pooled_mwr_worker import (
    test_retained_input_survives_interrupted_execution_cleanup as _assert_cleanup,
)
from tests.unit.services.test_async_result_store import (
    _publish_pooled,
)
from tests.unit.services.test_async_result_store import (
    test_pooled_original_cannot_repurpose_existing_ordinary_result as _assert_result_purpose,
)
from tests.unit.services.test_async_result_store import (
    test_pooled_original_conflicts_preserve_original as _assert_result_conflict,
)
from tests.unit.services.test_async_result_store import (
    test_pooled_original_retention_excludes_financial_original_but_prunes_ordinary as _assert_result_retention,
)
from tests.unit.services.test_async_result_store import (
    test_pooled_original_retry_replays_without_update as _assert_result_replay,
)
from tests.unit.services.test_async_result_store import (
    test_pooled_original_sql_guard_refuses_mutation as _assert_result_guard,
)
from tests.unit.services.test_async_result_store import (
    test_pooled_original_transaction_rollback_and_retry as _assert_result_rollback,
)
from tests.unit.services.test_async_result_store import (
    test_pooled_sql_cannot_repurpose_ordinary_result as _assert_sql_purpose,
)

custody = _custody_fixture
pooled_api_runtime = _api_runtime_fixture


@pytest.fixture
def pooled_api_database_url(custody_database_url):
    return custody_database_url


def test_postgres_registered_pooled_original_worker_and_replay(pooled_api_runtime):
    _assert_registered_original(pooled_api_runtime)


def test_postgres_registered_pooled_correction_preserves_both_originals(pooled_api_runtime):
    _assert_registered_correction(pooled_api_runtime)


@pytest.mark.parametrize("denial", ["missing", "wrong_audience", "capability", "scope", "tenant"])
def test_postgres_registered_pooled_authority_refuses_before_money_read(pooled_api_runtime, denial):
    _assert_registered_authority(pooled_api_runtime, denial)


def test_postgres_registered_pooled_missing_terminal_records_no_financial_original(pooled_api_runtime):
    _assert_registered_missing_terminal(pooled_api_runtime)


def test_postgres_registered_pooled_retry_reuses_snapshot(pooled_api_runtime, monkeypatch):
    _assert_registered_retry(pooled_api_runtime, monkeypatch)


@pytest.mark.parametrize("forged_tenant", [False, True])
def test_postgres_registered_pooled_audit_uses_verified_authority(
    pooled_api_runtime, monkeypatch, caplog, forged_tenant
):
    _assert_registered_audit(pooled_api_runtime, monkeypatch, caplog, forged_tenant)


def test_postgres_registered_pooled_duplicate_authorization_refuses(pooled_api_runtime):
    _assert_duplicate_authorization(pooled_api_runtime)


@pytest.mark.parametrize("length", [None, "1", "99999"])
def test_postgres_registered_pooled_streamed_body_bound(pooled_api_runtime, monkeypatch, length):
    _assert_streamed_size(pooled_api_runtime, monkeypatch, length)


@pytest.mark.parametrize("origin,expected", [("http://localhost:3000", 200), ("https://untrusted.test", 400)])
def test_postgres_registered_pooled_cors_preserved(pooled_api_runtime, origin, expected):
    _assert_preflight(pooled_api_runtime, origin, expected)


@pytest.fixture
def pooled_result_custody(custody):
    _, _, request, observation, _, engine, url = custody
    _bind(custody)
    results = AsyncResultStore(url)
    results.create_schema()
    payload = {
        "calculation_id": str(request.calculation_id),
        "input_manifest_digest": observation.input_manifest_digest,
        "controlled_result": "0.10",
    }
    try:
        yield results, engine, request, observation, payload
    finally:
        results._engine.dispose()


def test_postgres_pooled_result_replay_has_no_update(pooled_result_custody):
    _assert_result_replay(pooled_result_custody)


@pytest.mark.parametrize("change", ["payload", "tenant", "digest", "calculation"])
def test_postgres_pooled_result_conflicts_preserve_original(pooled_result_custody, change):
    _assert_result_conflict(pooled_result_custody, change)


def test_postgres_pooled_result_rollback_and_retry(pooled_result_custody):
    _assert_result_rollback(pooled_result_custody)


def test_postgres_pooled_result_cannot_repurpose_ordinary(pooled_result_custody):
    _assert_result_purpose(pooled_result_custody)


def test_postgres_pooled_sql_cannot_repurpose_ordinary(pooled_result_custody):
    _assert_sql_purpose(pooled_result_custody)


def test_postgres_pooled_result_retention_preserves_original(pooled_result_custody):
    _assert_result_retention(pooled_result_custody)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE analytics_async_result SET response_json='{}'",
        "UPDATE analytics_async_result SET analytics_type='TWR'",
        "UPDATE analytics_async_result SET tenant_id='foreign'",
        "DELETE FROM analytics_async_result",
        "TRUNCATE analytics_async_result",
        "TRUNCATE analytics_async_result CASCADE",
    ],
)
def test_postgres_pooled_result_guards_reject_mutation(pooled_result_custody, statement):
    _assert_result_guard(pooled_result_custody, statement)


@pytest.mark.parametrize("conflicting", [False, True])
def test_postgres_pooled_first_result_writers_converge_or_refuse(pooled_result_custody, conflicting):
    results, engine, request, observation, payload = pooled_result_custody
    start_writers = Barrier(2)

    def write(value):
        start_writers.wait(timeout=10)
        try:
            with engine.begin() as connection:
                _publish_pooled(results, connection, request, observation, {**payload, "controlled_result": value})
            return "published"
        except AsyncResultOriginalConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(write, "0.10")
        second = pool.submit(write, "0.20" if conflicting else "0.10")
        outcomes = sorted([first.result(timeout=15), second.result(timeout=15)])
    assert outcomes == (["conflict", "published"] if conflicting else ["published", "published"])
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM analytics_async_result")).scalar_one() == 1


def test_postgres_pooled_snapshot_result_binding_uses_same_current_claim(custody, pooled_result_custody):
    inputs, jobs, request, observation, claim, engine, _ = custody
    results, _, _, _, payload = pooled_result_custody

    def publish(connection):
        inputs.bind(connection, tenant_id=claim["tenant_id"], request=request, observation=observation)
        _publish_pooled(results, connection, request, observation, payload)

    with pytest.raises(ComputeJobLeaseOwnershipError):
        jobs.run_with_active_lease_transaction(**{**claim, "worker_id": "stale"}, operation=publish)
    assert results.get_result(request.calculation_id) is None

    def interrupted(connection):
        publish(connection)
        raise RuntimeError("interrupted before publication commit")

    with pytest.raises(RuntimeError, match="interrupted"):
        jobs.run_with_active_lease_transaction(**claim, operation=interrupted)
    assert results.get_result(request.calculation_id) is None
    jobs.run_with_active_lease_transaction(**claim, operation=publish)
    assert results.get_result(request.calculation_id).response_payload == payload
    assert inputs.get(request.calculation_id, tenant_id=claim["tenant_id"]).observation == observation


@pytest.fixture
def custody_database_url():
    from sqlalchemy import create_engine

    url = get_postgres_database_url()
    try:
        yield url
    finally:
        schema = make_url(url).query["options"].split("-csearch_path=")[-1].split()[0]
        assert schema.startswith("lotus_perf_bench_") and len(schema) == len("lotus_perf_bench_") + 32
        engine = create_engine(make_url(url).difference_update_query(["options"]))
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            engine.dispose()


def test_postgres_custody_original_replay_tenant_isolation_and_reopened_reader(custody):
    _assert_replay(custody)


def test_postgres_custody_conflicting_correction_preserves_original(custody):
    _assert_conflict(custody)


def test_postgres_custody_transaction_failure_rolls_back_before_retry(custody):
    _assert_rollback(custody)


def test_postgres_interrupted_job_cleanup_preserves_original(custody):
    _assert_cleanup(custody)


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE", "TRUNCATE_CASCADE"])
def test_postgres_custody_guards_refuse_mutation(custody, operation):
    inputs, _, request, observation, _, engine, _ = custody
    _bind(custody)
    statement = {
        "UPDATE": "UPDATE composite_pooled_mwr_inputs SET payload_json='{}'",
        "DELETE": "DELETE FROM composite_pooled_mwr_inputs",
        "TRUNCATE": "TRUNCATE composite_pooled_mwr_inputs",
        "TRUNCATE_CASCADE": "TRUNCATE composite_pooled_mwr_inputs CASCADE",
    }[operation]
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(text(statement))
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant").observation == observation
    inputs.verify_schema()
    inputs.create_schema()


@pytest.mark.parametrize("drift", ["missing", "disabled", "weakened_function"])
def test_postgres_custody_catalog_drift_refuses_readiness_and_bootstrap(custody, drift):
    inputs, _, _, _, _, engine, _ = custody
    with engine.begin() as connection:
        if drift == "missing":
            connection.exec_driver_sql("DROP TRIGGER composite_pooled_mwr_inputs_update ON composite_pooled_mwr_inputs")
        elif drift == "disabled":
            connection.exec_driver_sql(
                "ALTER TABLE composite_pooled_mwr_inputs DISABLE TRIGGER composite_pooled_mwr_inputs_update"
            )
        else:
            connection.exec_driver_sql(
                "CREATE OR REPLACE FUNCTION composite_pooled_mwr_inputs_immutable() RETURNS trigger "
                "LANGUAGE plpgsql AS $$BEGIN RETURN NEW; END;$$;"
            )
    with pytest.raises(DurableSchemaMigrationRequiredError):
        inputs.verify_schema()
    with pytest.raises(DurableSchemaMigrationRequiredError):
        inputs.create_schema()


def test_postgres_claim_replacement_waits_for_snapshot_transaction_then_rejects_old_attempt(custody):
    inputs, _, request, observation, claim, engine, _ = custody
    holding = Event()
    release = Event()
    replacing = Event()

    def held_bind(connection):
        snapshot = inputs.bind(connection, tenant_id=claim["tenant_id"], request=request, observation=observation)
        holding.set()
        assert release.wait(10), "test failed to release active-claim transaction"
        return snapshot

    def replace_claim():
        assert holding.wait(10)
        with engine.begin() as connection:
            # The real row lock, rather than a mocked lease lookup, prevents
            # replacement from passing a snapshot bound under an old claim.
            connection.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
            replacing.set()
            with pytest.raises(DBAPIError, match="lock timeout"):
                connection.execute(
                    text(
                        "UPDATE analytics_compute_job SET attempt_count=2, worker_id='replacement', lease_owner_id='replacement' WHERE calculation_id=:id"
                    ),
                    {"id": str(request.calculation_id)},
                )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            original = pool.submit(_bind, custody, operation=held_bind)
            replacement = pool.submit(replace_claim)
            assert replacing.wait(10)
            replacement.result(timeout=10)
            release.set()
            assert original.result(timeout=10).observation == observation
    finally:
        release.set()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE analytics_compute_job SET attempt_count=2, worker_id='replacement', lease_owner_id='replacement' WHERE calculation_id=:id"
            ),
            {"id": str(request.calculation_id)},
        )
    with pytest.raises(ComputeJobLeaseOwnershipError):
        _bind(custody)
    assert (
        _bind(custody, claim_change={"worker_id": "replacement", "expected_attempt_count": 2}).observation
        == observation
    )
