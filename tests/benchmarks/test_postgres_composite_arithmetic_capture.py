"""Real PostgreSQL custody proof for AW_TWR_DECIMAL_REPLAY.v1.

Collection is not execution evidence: the required runner rejects unavailable-DB
skips. Shared controls exercise the actual capsule path, including process death.
"""

import pytest
from sqlalchemy import text

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services.async_result_store import AsyncResultStore
from app.services.composite_metadata_store import CompositeMetadataStore
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url, owned_postgres_runtime_stores
from tests.integration import test_composite_result_candidate_api as candidate_api
from tests.unit.services.composite_arithmetic_capture import test_capture as capture_controls
from tests.unit.services.composite_arithmetic_capture import test_migration as migration_controls
from tests.unit.services.test_composite_result_candidates import _capture, build_candidate_inputs


@pytest.fixture
def postgres_precision_inputs(monkeypatch):
    inputs = build_candidate_inputs(get_postgres_database_url(), monkeypatch)
    try:
        yield inputs
    finally:
        inputs[0].close()
        inputs[1]._engine.dispose()


def test_postgres_registered_precision_candidate_retry_and_current_scope(monkeypatch, tmp_path, caplog):
    url = get_postgres_database_url()
    with owned_postgres_runtime_stores(url, monkeypatch):
        candidate_api.test_registered_candidate_original_retry_retention_audit_and_current_scope(
            monkeypatch, tmp_path, caplog, database_url=url, precision=True
        )


def test_postgres_precision_sticky_flags_and_allocations_converge(postgres_precision_inputs):
    capture_controls.test_sequential_sticky_flag_and_different_allocations_converge(postgres_precision_inputs)


def test_postgres_precision_preset_flags_and_source_order_custody(postgres_precision_inputs):
    capture_controls.test_preset_flags_converge_but_source_order_and_own_exit_flags_remain_evidence(
        postgres_precision_inputs
    )


def test_postgres_precision_competing_first_winner_has_no_orphan(postgres_precision_inputs):
    capture_controls.test_real_concurrent_different_id_winner_has_no_orphan(postgres_precision_inputs)


def test_postgres_precision_changed_numeric_context_conflicts(postgres_precision_inputs):
    capture_controls.test_changed_numeric_context_conflicts_even_when_reported_output_matches(postgres_precision_inputs)


@pytest.mark.parametrize("boundary", ["analytics_async_result", "composite_result_candidates"])
def test_postgres_precision_actual_write_failure_rolls_back(postgres_precision_inputs, boundary):
    capture_controls.test_precision_sidecar_atomic_write_failure(postgres_precision_inputs, boundary)


@pytest.mark.parametrize("boundary", ["analytics_async_result", "composite_result_candidates"])
def test_postgres_precision_abrupt_process_failure_rolls_back(postgres_precision_inputs, boundary):
    capture_controls.test_abrupt_precision_process_failure_leaves_no_half_capture(postgres_precision_inputs, boundary)


def _legacy_postgres_columns(store):
    """Recreate the populated pre-capsule catalog using PostgreSQL-native DDL."""
    with store._engine.begin() as connection:
        assert connection.dialect.name == "postgresql"
        connection.exec_driver_sql("DROP TRIGGER trg_composite_candidate_capture_pair ON composite_result_candidates")
        connection.exec_driver_sql("DROP FUNCTION require_composite_candidate_capture_pair()")
        for name in ("arithmetic_capture_json", "arithmetic_capture_digest"):
            connection.exec_driver_sql(f"ALTER TABLE composite_result_candidates DROP COLUMN {name}")


def _financial_bytes(store):
    with store._engine.connect() as connection:
        original_json = connection.scalar(text("SELECT response_json FROM analytics_async_result"))
        assert isinstance(original_json, str)
        return original_json.encode("utf-8")


def test_postgres_populated_legacy_upgrade_and_restart_preserve_exact_bytes(postgres_precision_inputs):
    store, old_results, _, _, principal = postgres_precision_inputs
    original = _capture(postgres_precision_inputs)
    before = _financial_bytes(store)
    assert before is not None and "arithmetic_capture" not in original
    _legacy_postgres_columns(store)
    store.create_schema()
    store.verify_schema()
    assert _financial_bytes(store) == before
    url = store._engine.url.render_as_string(hide_password=False)
    store.close()
    old_results._engine.dispose()
    reopened, results = CompositeMetadataStore(url), AsyncResultStore(url)
    try:
        reopened.create_schema()
        reopened.verify_schema()
        assert (
            reopened.get_result_candidate(
                candidate_id=original["candidate_id"],
                tenant_id=principal.tenant_id,
                result_store=results,
                principal=principal,
            )
            == original
        )
        assert _financial_bytes(reopened) == before
        with reopened._engine.connect() as connection:
            assert connection.execute(
                text("SELECT arithmetic_capture_json, arithmetic_capture_digest FROM composite_result_candidates")
            ).one() == (None, None)
        assert capture_controls.counts(reopened) == (1, 1)
    finally:
        reopened.close()
        results._engine.dispose()


@pytest.mark.parametrize(
    "column,sql_type", [("arithmetic_capture_json", "TEXT"), ("arithmetic_capture_digest", "VARCHAR(71)")]
)
def test_postgres_half_upgrade_refuses(postgres_precision_inputs, column, sql_type):
    store = postgres_precision_inputs[0]
    _capture(postgres_precision_inputs)
    before = _financial_bytes(store)
    _legacy_postgres_columns(store)
    with store._engine.begin() as connection:
        connection.exec_driver_sql(f"ALTER TABLE composite_result_candidates ADD COLUMN {column} {sql_type} NULL")
    with pytest.raises(DurableSchemaMigrationRequiredError, match="half_upgrade"):
        store.create_schema()
    assert _financial_bytes(store) == before
    assert capture_controls.counts(store) == (1, 1)


@pytest.mark.parametrize("raw,digest", [(None, "sha256:" + "a" * 64), ("{}", None), ("{}", "bad")])
def test_postgres_direct_sql_invalid_capture_pair_refuses(postgres_precision_inputs, raw, digest):
    migration_controls.test_database_pair_guard_rolls_back_new_original(postgres_precision_inputs, raw, digest)
