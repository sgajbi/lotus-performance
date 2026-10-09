"""Atomicity, original identity and replay custody; no new financial calculator."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_candidate_storage import CAPTURE_CAPABILITY
from app.core.config import get_settings
from app.models.composites import CompositeTWRRequest, CompositeTWRResponse
from app.observability import tenant_id_var
from app.services.async_result_store import AsyncResultStore
from app.services.composite_metadata_store import CompositeMetadataStore
from core.errors import APIConflictError, APIError


@pytest.fixture
def candidate_inputs(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'candidate.db'}"
    inputs = build_candidate_inputs(database_url, monkeypatch)
    yield inputs
    inputs[0].close()
    inputs[1]._engine.dispose()


def build_candidate_inputs(database_url, monkeypatch):
    results = AsyncResultStore(database_url)
    results.create_schema()
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    monkeypatch.setattr(get_settings(), "APP_GIT_COMMIT_SHA", "c100c885752c86b8d950d7970c99a8d223e6376a")
    response = CompositeTWRResponse.model_validate_json(
        (Path(__file__).resolve().parents[2] / "fixtures" / "composite_candidate_original.json").read_text()
    )
    request = CompositeTWRRequest(
        calculation_id=response.calculation_id,
        composite_id=response.composite_id,
        period_start=response.period_start,
        period_end=response.period_end,
        return_view=response.periods[0].return_view,
        reporting_currency=response.periods[0].reporting_currency,
        materialization_ids=[window.materialization_id for window in response.selection_manifest.windows],
    )
    portfolios = frozenset(member.portfolio_id for period in response.periods for member in period.member_contributions)
    principal = VerifiedCompositePrincipal(
        "user", "verified-maker", "tenant-a", frozenset({CAPTURE_CAPABILITY}), portfolios, "test-credential"
    )
    return store, results, request, response, principal


def _capture(inputs, candidate_id=None):
    store, results, request, response, principal = inputs
    return store.capture_result_candidate(
        candidate_id=candidate_id or uuid4(),
        request=request,
        response=response,
        principal=principal,
        result_store=results,
    )


def _counts(store):
    with store._engine.connect() as connection:
        return tuple(
            connection.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("analytics_async_result", "composite_result_candidates")
        )


def test_original_response_and_identity_survive_retry_gc_and_restart(candidate_inputs):
    store, results, request, response, principal = candidate_inputs
    first = _capture(candidate_inputs)
    assert first["response"] == response.model_dump(mode="json")
    assert first["response"]["calculation_id"] == str(request.calculation_id)
    retry_request, retry_response = request.model_copy(deep=True), response.model_copy(deep=True)
    retry_request.calculation_id = retry_response.calculation_id = uuid4()
    retry_response.selection_manifest.calculation_fingerprint = "different-retry-telemetry"
    assert _capture((store, results, retry_request, retry_response, principal)) == first
    assert _counts(store) == (1, 1)
    assert results.prune_results_older_than(datetime.now(UTC) + timedelta(days=1)) == 0
    reopened = CompositeMetadataStore(str(store._engine.url))
    token = tenant_id_var.set("tenant-a")
    try:
        reopened.verify_schema()
        assert (
            reopened.get_result_candidate(
                candidate_id=first["candidate_id"], tenant_id="tenant-a", result_store=results
            )
            == first
        )
    finally:
        tenant_id_var.reset(token)
        reopened.close()


@pytest.mark.parametrize("boundary", ["analytics_async_result", "composite_result_candidates"])
def test_every_write_boundary_rolls_back_original_and_descriptor(candidate_inputs, boundary):
    store, *_ = candidate_inputs

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {boundary}"):
            raise RuntimeError("injected write boundary failure")

    event.listen(store._engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="write boundary"):
            _capture(candidate_inputs)
    finally:
        event.remove(store._engine, "after_cursor_execute", fail)
    assert _counts(store) == (0, 0)
    assert _capture(candidate_inputs)["response"]["cumulative_return"] == "0.030200000000"


@pytest.mark.parametrize("boundary", ["analytics_async_result", "composite_result_candidates"])
def test_abrupt_process_crash_at_each_write_preserves_atomicity(candidate_inputs, boundary):
    store, *_ = candidate_inputs
    env = {**os.environ, "LINEAGE_METADATA_DATABASE_URL": store._engine.url.render_as_string(hide_password=False)}
    result = subprocess.run(
        [sys.executable, "-m", "tests.benchmarks.composite_candidate_crash_controls", boundary],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 73, result.stdout + result.stderr
    assert "reached_actual_write_boundary=" + boundary in result.stdout
    assert _counts(store) == (0, 0)
    assert _capture(candidate_inputs)["response"]["cumulative_return"] == "0.030200000000"


def test_single_concurrent_winner_has_no_losing_original(candidate_inputs):
    store, results, request, response, principal = candidate_inputs
    barrier = Barrier(2)

    def capture():
        retry_request, retry_response = request.model_copy(deep=True), response.model_copy(deep=True)
        retry_request.calculation_id = retry_response.calculation_id = uuid4()
        barrier.wait(timeout=10)
        return _capture((store, results, retry_request, retry_response, principal))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(capture) for _ in range(2)]
        first, second = [future.result(timeout=20) for future in futures]
    assert first == second
    assert _counts(store) == (1, 1)


def test_changed_content_and_unrelated_calculation_collision_refuse(candidate_inputs):
    store, results, request, response, principal = candidate_inputs
    original = _capture(candidate_inputs)
    response.cumulative_return += 1
    with pytest.raises(APIConflictError):
        _capture(candidate_inputs, original["candidate_id"])
    assert _counts(store) == (1, 1)
    new_request = request.model_copy(update={"calculation_id": uuid4()})
    new_response = response.model_copy(update={"calculation_id": new_request.calculation_id})
    results.record_success(
        calculation_id=new_request.calculation_id,
        analytics_type="TWR",
        tenant_id="tenant-a",
        response_payload={"unrelated": True},
    )
    new_request.materialization_ids = [uuid4(), uuid4()]
    for window, materialization_id in zip(new_response.selection_manifest.windows, new_request.materialization_ids):
        window.materialization_id = materialization_id
    with pytest.raises(APIConflictError):
        _capture((store, results, new_request, new_response, principal))
    assert _counts(store) == (2, 1)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE composite_result_candidates SET captured_by = 'forged'",
        "DELETE FROM composite_result_candidates",
        "UPDATE analytics_async_result SET response_json = '{}'",
    ],
)
def test_candidate_and_original_refuse_mutation(candidate_inputs, mutation):
    store, *_ = candidate_inputs
    original = _capture(candidate_inputs)
    with pytest.raises(IntegrityError, match="immutable"):
        with store._engine.begin() as connection:
            connection.execute(text(mutation))
    assert _capture(candidate_inputs) == original


def test_different_installed_database_refuses_without_writes(candidate_inputs, tmp_path):
    store, _, request, response, principal = candidate_inputs
    unrelated = AsyncResultStore(f"sqlite:///{tmp_path / 'other.db'}")
    unrelated.create_schema()
    try:
        with pytest.raises(APIError, match="same installed"):
            _capture((store, unrelated, request, response, principal))
    finally:
        unrelated._engine.dispose()
    assert _counts(store) == (0, 0)


def test_in_memory_result_authority_refuses_capture(candidate_inputs):
    store, _, request, response, principal = candidate_inputs
    unrelated = AsyncResultStore("sqlite:///:memory:")
    unrelated.create_schema()
    try:
        with pytest.raises(APIError, match="in-memory"):
            _capture((store, unrelated, request, response, principal))
    finally:
        unrelated._engine.dispose()
    assert _counts(store) == (0, 0)


@pytest.mark.parametrize("corruption", ["missing", "payload", "tenant", "purpose", "vector"])
def test_original_custody_corruption_refuses_without_recalculation(candidate_inputs, corruption):
    store, results, _, _, _ = candidate_inputs
    original = _capture(candidate_inputs)
    with store._engine.begin() as connection:
        if corruption == "missing":
            connection.exec_driver_sql("DROP TRIGGER trg_composite_result_custody_delete")
            connection.exec_driver_sql("DELETE FROM analytics_async_result")
        elif corruption == "vector":
            connection.exec_driver_sql("DROP TRIGGER trg_composite_result_candidate_immutable_update")
            connection.exec_driver_sql("UPDATE composite_result_candidates SET materialization_vector_json = '[]'")
        else:
            connection.exec_driver_sql("DROP TRIGGER trg_composite_result_custody_update")
            mutation = {
                "payload": "response_json = '{}'",
                "tenant": "tenant_id = 'other-tenant'",
                "purpose": "analytics_type = 'TWR'",
            }[corruption]
            connection.exec_driver_sql("UPDATE analytics_async_result SET " + mutation)
    # This repairs catalog guards only, never missing original content. Runtime
    # must still refuse the inconsistent retained original after owner repair.
    results.create_schema()
    store.create_schema()
    token = tenant_id_var.set("tenant-a")
    try:
        with pytest.raises(APIError, match="custody|provenance"):
            store.get_result_candidate(
                candidate_id=original["candidate_id"], tenant_id="tenant-a", result_store=results
            )
    finally:
        tenant_id_var.reset(token)


def test_candidate_cross_tenant_absence_does_not_read_original(candidate_inputs):
    store, results, _, _, _ = candidate_inputs
    original = _capture(candidate_inputs)
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store._engine, "before_cursor_execute", observe)
    token = tenant_id_var.set("tenant-b")
    try:
        assert (
            store.get_result_candidate(
                candidate_id=original["candidate_id"], tenant_id="tenant-b", result_store=results
            )
            is None
        )
        assert not any("FROM ANALYTICS_ASYNC_RESULT" in statement.upper() for statement in statements)
    finally:
        tenant_id_var.reset(token)
        event.remove(store._engine, "before_cursor_execute", observe)


def test_gc_during_atomic_capture_cannot_delete_born_original(candidate_inputs):
    store, results, _, _, _ = candidate_inputs
    inserted, release, gc_requested = Event(), Event(), Event()

    def pause(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO analytics_async_result"):
            inserted.set()
            assert release.wait(10), "Capture controller did not release the real transaction"

    def observe_gc(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM analytics_async_result"):
            gc_requested.set()

    event.listen(store._engine, "after_cursor_execute", pause)
    event.listen(results._engine, "before_cursor_execute", observe_gc)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            capture = pool.submit(_capture, candidate_inputs)
            assert inserted.wait(10)
            prune = pool.submit(results.prune_results_older_than, datetime.now(UTC) + timedelta(days=1))
            try:
                assert gc_requested.wait(10)
                if store._engine.dialect.name == "postgresql":
                    assert prune.result(timeout=10) == 0
                else:
                    assert not prune.done(), "SQLite GC must wait for the actual capture writer"
            finally:
                release.set()
            original = capture.result(timeout=10)
            assert prune.result(timeout=10) == 0
    finally:
        release.set()
        event.remove(store._engine, "after_cursor_execute", pause)
        event.remove(results._engine, "before_cursor_execute", observe_gc)
    assert original["response"]["cumulative_return"] == "0.030200000000"
    assert _counts(store) == (1, 1)
    assert results.prune_results_older_than(datetime.now(UTC) + timedelta(days=1)) == 0


@pytest.mark.parametrize("bad", ["no_vector", "blocked", "no_manifest", "no_scope", "no_capability", "unknown_build"])
def test_candidate_default_and_incomplete_admission_refuse_without_writes(candidate_inputs, bad, monkeypatch):
    store, results, request, response, principal = candidate_inputs
    if bad == "no_vector":
        request.materialization_ids = None
    elif bad == "blocked":
        response.status = "BLOCKED"
    elif bad == "no_manifest":
        response.selection_manifest = None
    elif bad == "unknown_build":
        monkeypatch.setattr(get_settings(), "APP_GIT_COMMIT_SHA", "local")
    elif bad == "no_capability":
        principal = VerifiedCompositePrincipal(
            "user", "maker", "tenant-a", frozenset(), principal.portfolio_scope, "credential"
        )
    else:
        principal = VerifiedCompositePrincipal(
            "user", "maker", "tenant-a", principal.capabilities, frozenset(), "credential"
        )
    with pytest.raises(APIError):
        _capture((store, results, request, response, principal))
    assert _counts(store) == (0, 0)
