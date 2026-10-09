"""Actual PostgreSQL custody guards and competing active-claim transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services.compute_job_store import ComputeJobLeaseOwnershipError
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
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

custody = _custody_fixture


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
