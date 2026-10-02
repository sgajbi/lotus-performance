from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.source_corrections import SourceCorrectionRequest
from app.observability import tenant_id_var
from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.source_correction_service import (
    cancel_source_correction,
    get_retained_calculation_result,
    get_source_correction,
    submit_source_correction,
)
from app.services.source_correction_store import (
    SourceCorrectionEventModel,
    SourceCorrectionRegistrationStatus,
    SourceCorrectionStore,
    _lock_source_correction_scope,
)
from core.errors import APIError


@pytest.fixture
def durable_stores(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'source-corrections.db'}"
    execution_store = ExecutionRegistry(database_url)
    compute_store = ComputeJobStore(database_url)
    correction_store = SourceCorrectionStore(database_url)
    execution_store.create_schema()
    compute_store.create_schema()
    correction_store.create_schema()
    monkeypatch.setattr("app.services.source_correction_service.execution_registry", execution_store)
    monkeypatch.setattr("app.services.source_correction_service.compute_job_store", compute_store)
    monkeypatch.setattr("app.services.source_correction_service.source_correction_store", correction_store)
    return execution_store, compute_store, correction_store


def _correction(**overrides) -> SourceCorrectionRequest:
    payload = {
        "correction_id": "core-correction-42",
        "source_product": "portfolio_timeseries",
        "source_revision": "core-restatement-2",
        "supersedes_source_revision": "core-restatement-1",
        "target_type": "portfolio",
        "target_id": "PORT-CORRECTED",
        "effective_start_date": "2026-01-02",
        "effective_end_date": "2026-01-02",
        "observed_at_utc": "2026-01-03T10:00:00Z",
        "correction_reason": "Corrected closing valuation after source control review.",
        "source_authorization": {"issuer": "lotus-core", "evidence_id": "core-event-42"},
    }
    payload.update(overrides)
    return SourceCorrectionRequest.model_validate(payload)


def _retain_original(execution_store: ExecutionRegistry, *, tenant_id: str = "bank-a"):
    calculation_id = uuid4()
    request_payload = {
        "calculation_id": str(calculation_id),
        "portfolio_id": "PORT-CORRECTED",
        "input_mode": "stateful",
        "performance_start_date": "2026-01-01",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
    }
    execution_store.create_execution(
        calculation_id=calculation_id,
        tenant_id=tenant_id,
        analytics_type="TWR",
        portfolio_id="PORT-CORRECTED",
        execution_mode="sync",
        requested_window={"start_date": "2026-01-01", "end_date": "2026-01-02"},
        input_fingerprint="sha256:original-input",
        calculation_hash="sha256:original-calculation",
        request_payload=request_payload,
    )
    execution_store.retain_response_payload(
        calculation_id,
        response_payload={"calculation_id": str(calculation_id), "cumulative_return": 0.10},
    )
    execution_store.mark_complete(calculation_id)
    return calculation_id


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"observed_at_utc": "2026-01-03T10:00:00"}, "must include a UTC offset"),
        ({"observed_at_utc": "2026-01-03T11:00:00+01:00"}, "must use UTC"),
        ({"correction_reason": "   "}, "at least 1 character"),
        ({"source_authorization": {"issuer": " ", "evidence_id": "event-1"}}, "at least 1 character"),
        ({"effective_start_date": "2026-01-03", "effective_end_date": "2026-01-02"}, "must be on or after"),
        ({"source_product": "benchmark_returns", "target_type": "portfolio"}, "require target_type=benchmark"),
    ],
)
def test_correction_contract_rejects_ambiguous_authority_and_time(overrides, expected_message):
    with pytest.raises(ValidationError) as exc_info:
        _correction(**overrides)

    assert expected_message in str(exc_info.value)


def test_correction_recalculates_once_and_preserves_original_result(durable_stores):
    execution_store, compute_store, _ = durable_stores
    original_id = _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        accepted = submit_source_correction(_correction())
        replay = submit_source_correction(_correction())

        assert accepted.state == "recalculation_pending"
        assert accepted.affected_calculation_count == 1
        assert replay.replayed is True
        assert replay.impacts[0].corrected_calculation_id == accepted.impacts[0].corrected_calculation_id
        assert len(compute_store.list_pending_jobs()) == 1
        retained = get_retained_calculation_result(original_id)
        assert retained.response["cumulative_return"] == 0.10

        corrected_id = accepted.impacts[0].corrected_calculation_id
        leased = compute_store.lease_pending_jobs(worker_id="correction-worker", limit=1, lease_seconds=30)
        assert [job.calculation_id for job in leased] == [corrected_id]
        compute_store.mark_running(corrected_id, worker_id="correction-worker")
        compute_store.mark_complete(
            corrected_id,
            response_payload={"calculation_id": str(corrected_id), "cumulative_return": 0.08},
            worker_id="correction-worker",
        )
        execution_store.retain_response_payload(
            corrected_id,
            response_payload={"calculation_id": str(corrected_id), "cumulative_return": 0.08},
        )
        execution_store.mark_complete(corrected_id)

        completed = get_source_correction("core-correction-42")
        assert completed.state == "complete"
        assert completed.impacts[0].output_changed is True
        assert completed.current_result_paths == [completed.impacts[0].corrected_result_path]
        assert get_retained_calculation_result(original_id).response["cumulative_return"] == 0.10
        assert get_retained_calculation_result(corrected_id).response["cumulative_return"] == 0.08
    finally:
        tenant_id_var.reset(tenant_token)


def test_correction_identity_conflict_and_tenant_isolation(durable_stores):
    execution_store, _, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        accepted = submit_source_correction(_correction())
        with pytest.raises(APIError) as conflict:
            submit_source_correction(_correction(source_revision="core-restatement-3"))
        assert conflict.value.status_code == 409
        assert conflict.value.error_code == "SOURCE_CORRECTION_ID_CONFLICT"
    finally:
        tenant_id_var.reset(tenant_token)

    tenant_token = tenant_id_var.set("bank-b")
    try:
        with pytest.raises(APIError) as hidden:
            get_source_correction(accepted.correction_id)
        assert hidden.value.status_code == 404
        with pytest.raises(APIError) as original_hidden:
            get_retained_calculation_result(accepted.impacts[0].original_calculation_id)
        assert original_hidden.value.status_code == 404
        with pytest.raises(APIError) as cancellation_hidden:
            cancel_source_correction(accepted.correction_id)
        assert cancellation_hidden.value.status_code == 404
    finally:
        tenant_id_var.reset(tenant_token)


def test_outside_window_and_out_of_order_corrections_do_not_schedule_work(durable_stores):
    execution_store, compute_store, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        outside = submit_source_correction(
            _correction(
                correction_id="outside-window",
                effective_start_date="2026-02-01",
                effective_end_date="2026-02-02",
                observed_at_utc="2026-02-03T10:00:00Z",
            )
        )
        assert outside.state == "no_effect"

        newest = submit_source_correction(
            _correction(
                correction_id="newest",
                source_revision="revision-9",
                supersedes_source_revision="core-restatement-2",
                observed_at_utc="2026-03-01T10:00:00Z",
            )
        )
        older = submit_source_correction(
            _correction(correction_id="older", source_revision="revision-8", observed_at_utc="2026-02-01T10:00:00Z")
        )
        assert newest.state == "recalculation_pending"
        assert older.state == "superseded"
        assert older.affected_calculation_count == 0
        assert len(compute_store.list_pending_jobs()) == 1
    finally:
        tenant_id_var.reset(tenant_token)


def test_newer_correction_must_extend_latest_admitted_revision(durable_stores):
    execution_store, _, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        submit_source_correction(_correction())
        with pytest.raises(APIError) as conflict:
            submit_source_correction(
                _correction(
                    correction_id="revision-gap",
                    source_revision="revision-3",
                    supersedes_source_revision="unknown-revision",
                    observed_at_utc="2026-01-04T10:00:00Z",
                )
            )
        assert conflict.value.error_code == "SOURCE_CORRECTION_REVISION_CONFLICT"

        with pytest.raises(APIError) as missing_predecessor:
            submit_source_correction(
                _correction(
                    correction_id="revision-without-predecessor",
                    source_revision="revision-4",
                    supersedes_source_revision=None,
                    observed_at_utc="2026-01-05T10:00:00Z",
                )
            )
        assert missing_predecessor.value.error_code == "SOURCE_CORRECTION_REVISION_CONFLICT"

    finally:
        tenant_id_var.reset(tenant_token)


def test_equal_timestamp_correction_must_extend_revision_chain(durable_stores):
    execution_store, _, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        submit_source_correction(_correction())
        linked = submit_source_correction(
            _correction(
                correction_id="equal-timestamp-linked",
                source_revision="core-restatement-3",
                supersedes_source_revision="core-restatement-2",
            )
        )
        assert linked.state == "recalculation_pending"

        with pytest.raises(APIError) as equal_timestamp_gap:
            submit_source_correction(
                _correction(
                    correction_id="equal-timestamp-gap",
                    source_revision="core-restatement-4",
                    supersedes_source_revision=None,
                )
            )
        assert equal_timestamp_gap.value.error_code == "SOURCE_CORRECTION_REVISION_CONFLICT"
    finally:
        tenant_id_var.reset(tenant_token)


def test_pending_correction_can_be_cancelled_without_publication(durable_stores):
    execution_store, compute_store, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        accepted = submit_source_correction(_correction())
        cancelled = cancel_source_correction(accepted.correction_id)
        job = compute_store.get_job_for_tenant(
            accepted.impacts[0].corrected_calculation_id,
            tenant_id="bank-a",
        )

        assert cancelled.state == "cancelled"
        assert cancelled.impacts[0].failure_code == "SOURCE_CORRECTION_CANCELLED"
        assert job is not None
        assert job.error_type == "SourceCorrectionCancelled"
        assert get_source_correction(accepted.correction_id).state == "cancelled"
        assert cancel_source_correction(accepted.correction_id).replayed is True
    finally:
        tenant_id_var.reset(tenant_token)


def test_running_recalculation_refuses_cancellation_and_publishes_typed_failure(durable_stores):
    execution_store, compute_store, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        accepted = submit_source_correction(_correction())
        corrected_id = accepted.impacts[0].corrected_calculation_id
        leased = compute_store.lease_pending_jobs(worker_id="correction-worker", limit=1, lease_seconds=30)
        assert [job.calculation_id for job in leased] == [corrected_id]
        assert get_source_correction(accepted.correction_id).impacts[0].state == "running"

        with pytest.raises(APIError) as conflict:
            cancel_source_correction(accepted.correction_id)
        assert conflict.value.error_code == "SOURCE_CORRECTION_CANCELLATION_CONFLICT"

        compute_store.mark_running(corrected_id, worker_id="correction-worker")
        compute_store.mark_failed(
            corrected_id,
            error_message="Corrected source remained unavailable.",
            error_type="SOURCE_REVISION_UNAVAILABLE",
            worker_id="correction-worker",
        )
        execution_store.mark_failed(corrected_id, "Corrected source remained unavailable.")
        failed = get_source_correction(accepted.correction_id)
        assert failed.state == "partial_failure"
        assert failed.impacts[0].failure_code == "SOURCE_REVISION_UNAVAILABLE"
        assert cancel_source_correction(accepted.correction_id).replayed is True
    finally:
        tenant_id_var.reset(tenant_token)


def test_missing_durable_recalculation_is_not_reported_complete(durable_stores):
    execution_store, compute_store, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        accepted = submit_source_correction(_correction())
        compute_store.clear_all_records()

        failed = get_source_correction(accepted.correction_id)
        assert failed.state == "partial_failure"
        assert failed.impacts[0].failure_code == "DURABLE_RECALCULATION_MISSING"
    finally:
        tenant_id_var.reset(tenant_token)


def test_benchmark_and_fx_corrections_match_explicit_nested_source_identity(durable_stores):
    execution_store, compute_store, _ = durable_stores
    benchmark_id = _retain_original(execution_store)
    benchmark_record = execution_store.get_execution(benchmark_id)
    assert benchmark_record is not None and benchmark_record.request_payload is not None
    benchmark_payload = dict(benchmark_record.request_payload)
    benchmark_payload["benchmark"] = {"benchmark_id": "BM-USD"}
    execution_store.delete_execution(benchmark_id)
    execution_store.create_execution(
        calculation_id=benchmark_id,
        tenant_id="bank-a",
        analytics_type="BENCHMARK",
        portfolio_id="PORT-CORRECTED",
        execution_mode="sync",
        requested_window={"start_date": "2026-01-01", "end_date": "2026-01-02"},
        request_payload=benchmark_payload,
    )
    execution_store.retain_response_payload(benchmark_id, response_payload={"active_return": 0.01})
    execution_store.mark_complete(benchmark_id)

    fx_id = _retain_original(execution_store)
    fx_record = execution_store.get_execution(fx_id)
    assert fx_record is not None and fx_record.request_payload is not None
    fx_payload = dict(fx_record.request_payload)
    fx_payload.update(report_ccy="USD", positions=[{"currency": "EUR"}])
    execution_store.delete_execution(fx_id)
    execution_store.create_execution(
        calculation_id=fx_id,
        tenant_id="bank-a",
        analytics_type="TWR",
        portfolio_id="PORT-CORRECTED",
        execution_mode="sync",
        requested_window={"start_date": "not-a-date", "as_of_date": "2026-01-02"},
        request_payload=fx_payload,
    )
    execution_store.retain_response_payload(fx_id, response_payload={"cumulative_return": 0.02})
    execution_store.mark_complete(fx_id)

    tenant_token = tenant_id_var.set("bank-a")
    try:
        benchmark = submit_source_correction(
            _correction(
                correction_id="benchmark-correction",
                source_product="benchmark_returns",
                target_type="benchmark",
                target_id="BM-USD",
            )
        )
        fx = submit_source_correction(
            _correction(
                correction_id="fx-correction",
                source_product="fx_rates",
                source_revision="fx-revision-2",
                supersedes_source_revision=None,
                target_id="EUR/USD",
                observed_at_utc="2026-01-04T10:00:00Z",
            )
        )

        assert [impact.original_calculation_id for impact in benchmark.impacts] == [benchmark_id]
        assert [impact.original_calculation_id for impact in fx.impacts] == [fx_id]
        assert len(compute_store.list_pending_jobs()) == 2
    finally:
        tenant_id_var.reset(tenant_token)


def test_benchmark_correction_uses_resolved_identity_and_actual_window(durable_stores):
    execution_store, compute_store, _ = durable_stores
    calculation_id = _retain_original(execution_store)
    original = execution_store.get_execution(calculation_id)
    assert original is not None and original.request_payload is not None
    execution_store.delete_execution(calculation_id)
    execution_store.create_execution(
        calculation_id=calculation_id,
        tenant_id="bank-a",
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-CORRECTED",
        execution_mode="sync",
        requested_window={
            "benchmark_id": "BM-RESOLVED",
            "benchmark_start_date": "2026-01-02",
            "report_end_date": "2026-01-03",
        },
        request_payload=original.request_payload,
    )
    execution_store.retain_response_payload(calculation_id, response_payload={"cumulative_return": 0.02})
    execution_store.mark_complete(calculation_id)

    tenant_token = tenant_id_var.set("bank-a")
    try:
        before_window = submit_source_correction(
            _correction(
                correction_id="benchmark-before-window",
                source_product="benchmark_returns",
                source_revision="benchmark-revision-1",
                supersedes_source_revision=None,
                target_type="benchmark",
                target_id="BM-RESOLVED",
                effective_start_date="2026-01-01",
                effective_end_date="2026-01-01",
            )
        )
        overlapping = submit_source_correction(
            _correction(
                correction_id="benchmark-overlap",
                source_product="benchmark_returns",
                source_revision="benchmark-revision-2",
                supersedes_source_revision="benchmark-revision-1",
                target_type="benchmark",
                target_id="BM-RESOLVED",
                effective_start_date="2026-01-02",
                effective_end_date="2026-01-02",
                observed_at_utc="2026-01-04T10:00:00Z",
            )
        )

        assert before_window.state == "no_effect"
        assert [impact.original_calculation_id for impact in overlapping.impacts] == [calculation_id]
        assert len(compute_store.list_pending_jobs()) == 1
    finally:
        tenant_id_var.reset(tenant_token)


def test_source_correction_store_preserves_referenced_results_for_retention(durable_stores):
    _, _, correction_store = durable_stores
    original_id = uuid4()
    corrected_id = uuid4()
    payload = _correction().model_dump(mode="json")
    payload.update(
        coalesced_effective_start_date="2026-01-02",
        coalesced_effective_end_date="2026-01-02",
    )
    registration = correction_store.register(
        tenant_id="bank-a",
        correction_id="retention-correction",
        request_fingerprint="sha256:retention",
        request_payload=payload,
    )
    assert registration.status == "created"

    correction_store.update(
        tenant_id="bank-a",
        correction_id="retention-correction",
        state="complete",
        impacts=[
            {
                "original_calculation_id": str(original_id),
                "corrected_calculation_id": str(corrected_id),
            }
        ],
    )
    assert correction_store.referenced_calculation_ids() == {str(original_id), str(corrected_id)}

    with pytest.raises(KeyError):
        correction_store.update(tenant_id="bank-a", correction_id="missing", state="complete", impacts=[])
    correction_store.clear_all_records()
    assert correction_store.get(tenant_id="bank-a", correction_id="retention-correction") is None


def test_overlapping_pending_corrections_coalesce_without_duplicate_version(durable_stores):
    execution_store, compute_store, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        first = submit_source_correction(_correction())
        second = submit_source_correction(
            _correction(
                correction_id="core-correction-43",
                source_revision="core-restatement-3",
                supersedes_source_revision="core-restatement-2",
                effective_start_date="2026-01-01",
                observed_at_utc="2026-01-04T10:00:00Z",
            )
        )

        assert len(compute_store.list_pending_jobs()) == 1
        assert second.impacts[0].corrected_calculation_id == first.impacts[0].corrected_calculation_id
        assert str(second.coalesced_effective_start_date) == "2026-01-01"
        assert str(second.coalesced_effective_end_date) == "2026-01-02"
        assert (
            submit_source_correction(
                _correction(
                    correction_id="core-correction-43",
                    source_revision="core-restatement-3",
                    supersedes_source_revision="core-restatement-2",
                    effective_start_date="2026-01-01",
                    observed_at_utc="2026-01-04T10:00:00Z",
                )
            ).replayed
            is True
        )

        cancelled = cancel_source_correction(second.correction_id)
        assert cancelled.state == "cancelled"
        assert get_source_correction(first.correction_id).state == "cancelled"
        assert get_source_correction(first.correction_id).impacts[0].failure_code == "SOURCE_CORRECTION_CANCELLED"
    finally:
        tenant_id_var.reset(tenant_token)


def test_replay_identity_remains_stable_after_later_correction(durable_stores):
    execution_store, compute_store, _ = durable_stores
    _retain_original(execution_store)
    tenant_token = tenant_id_var.set("bank-a")
    try:
        first_request = _correction()
        first = submit_source_correction(first_request)
        submit_source_correction(
            _correction(
                correction_id="core-correction-43",
                source_revision="core-restatement-3",
                supersedes_source_revision="core-restatement-2",
                effective_start_date="2026-01-01",
                observed_at_utc="2026-01-04T10:00:00Z",
            )
        )

        replay = submit_source_correction(first_request)

        assert replay.replayed is True
        assert replay.impacts[0].corrected_calculation_id == first.impacts[0].corrected_calculation_id
        assert len(compute_store.list_pending_jobs()) == 1
    finally:
        tenant_id_var.reset(tenant_token)


def test_terminal_no_effect_replay_does_not_discover_later_executions(durable_stores):
    execution_store, compute_store, _ = durable_stores
    tenant_token = tenant_id_var.set("bank-a")
    request = _correction(effective_start_date="2026-02-01", effective_end_date="2026-02-02")
    try:
        first = submit_source_correction(request)
        assert first.state == "no_effect"

        calculation_id = uuid4()
        execution_store.create_execution(
            calculation_id=calculation_id,
            tenant_id="bank-a",
            analytics_type="TWR",
            portfolio_id="PORT-CORRECTED",
            execution_mode="sync",
            requested_window={"start_date": "2026-02-01", "end_date": "2026-02-02"},
            request_payload={
                "calculation_id": str(calculation_id),
                "portfolio_id": "PORT-CORRECTED",
                "input_mode": "stateful",
                "performance_start_date": "2026-02-01",
                "report_end_date": "2026-02-02",
            },
        )
        execution_store.mark_complete(calculation_id)

        replay = submit_source_correction(request)

        assert replay.replayed is True
        assert replay.state == "no_effect"
        assert replay.affected_calculation_count == 0
        assert compute_store.list_pending_jobs() == []
    finally:
        tenant_id_var.reset(tenant_token)


def test_revision_chain_admission_is_atomic_under_same_scope_contention(durable_stores):
    _, _, correction_store = durable_stores
    initial = _correction().model_dump(mode="json")
    initial["coalesced_effective_start_date"] = "2026-01-02"
    initial["coalesced_effective_end_date"] = "2026-01-02"
    assert (
        correction_store.register(
            tenant_id="bank-a",
            correction_id="core-correction-42",
            request_fingerprint="sha256:initial",
            request_payload=initial,
        ).status
        == SourceCorrectionRegistrationStatus.CREATED
    )

    def register_successor(correction_id: str, source_revision: str):
        payload = _correction(
            correction_id=correction_id,
            source_revision=source_revision,
            supersedes_source_revision="core-restatement-2",
            observed_at_utc="2026-01-04T10:00:00Z",
        ).model_dump(mode="json")
        payload["coalesced_effective_start_date"] = "2026-01-02"
        payload["coalesced_effective_end_date"] = "2026-01-02"
        return correction_store.register(
            tenant_id="bank-a",
            correction_id=correction_id,
            request_fingerprint=f"sha256:{correction_id}",
            request_payload=payload,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda values: register_successor(*values),
                [("successor-a", "revision-a"), ("successor-b", "revision-b")],
            )
        )

    assert {result.status for result in results} == {
        SourceCorrectionRegistrationStatus.CREATED,
        SourceCorrectionRegistrationStatus.REVISION_CONFLICT,
    }

    postgres_session = MagicMock()
    postgres_session.bind.dialect.name = "postgresql"
    _lock_source_correction_scope(
        postgres_session,
        tenant_id="bank-a",
        source_product="portfolio_timeseries",
        target_type="portfolio",
        target_id="PORT-CORRECTED",
    )
    first_lock = postgres_session.execute.call_args.args[0].compile().params
    _lock_source_correction_scope(
        postgres_session,
        tenant_id="bank-b",
        source_product="portfolio_timeseries",
        target_type="portfolio",
        target_id="PORT-CORRECTED",
    )
    second_lock = postgres_session.execute.call_args.args[0].compile().params
    assert "pg_advisory_xact_lock" in str(postgres_session.execute.call_args.args[0])
    assert first_lock != second_lock

    unlocked_session = MagicMock()
    unlocked_session.bind = None
    _lock_source_correction_scope(
        unlocked_session,
        tenant_id="bank-a",
        source_product="portfolio_timeseries",
        target_type="portfolio",
        target_id="PORT-CORRECTED",
    )
    unlocked_session.execute.assert_not_called()

    now = datetime.now(timezone.utc)
    existing_row = SourceCorrectionEventModel(
        tenant_id="bank-a",
        correction_id="integrity-fallback",
        request_fingerprint="sha256:fallback",
        source_product="portfolio_timeseries",
        source_revision="revision-fallback",
        target_type="portfolio",
        target_id="PORT-FALLBACK",
        observed_at_utc=now,
        request_json=json.dumps(initial, sort_keys=True),
        state="recalculation_pending",
        impacts_json="[]",
        created_at_utc=now,
        updated_at_utc=now,
    )
    fallback_session = MagicMock()
    fallback_session.bind.dialect.name = "other"
    fallback_session.get.side_effect = [None, existing_row]
    fallback_session.execute.return_value.scalar_one_or_none.return_value = None
    fallback_session.commit.side_effect = IntegrityError("insert", {}, RuntimeError("duplicate"))
    correction_store._session_factory = MagicMock(return_value=fallback_session)
    fallback_payload = dict(initial)
    fallback_payload["correction_id"] = "integrity-fallback"
    fallback_payload["source_revision"] = "revision-fallback"
    fallback_payload["target_id"] = "PORT-FALLBACK"
    fallback = correction_store.register(
        tenant_id="bank-a",
        correction_id="integrity-fallback",
        request_fingerprint="sha256:fallback",
        request_payload=fallback_payload,
    )
    assert fallback.status == SourceCorrectionRegistrationStatus.REPLAY
    fallback_session.rollback.assert_called_once()
