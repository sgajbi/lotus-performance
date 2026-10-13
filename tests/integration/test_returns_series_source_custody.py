"""Production resolver, stores, workers and retained reads with isolated source fixtures."""

import asyncio
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.models.returns_series import ReturnsSeriesRequest
from app.observability import tenant_id_var
from app.services.analytics_workflow_commands import ReturnsSeriesWorkflowCommand
from app.services.compute_job_store import compute_job_store
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.lineage_artifact_service import resolve_lineage_artifact_file, resolve_lineage_response
from app.services.lineage_metadata_store import LineagePayloadLeaseOwnershipError, lineage_metadata_store
from app.services.lineage_service import LineageService
from app.services.returns_series_calculation_workflow_service import calculate_returns_series_workflow
from app.services.returns_series_source.archive import SourceArchiveError
from app.services.returns_series_source.capture import json_bytes
from app.services.returns_series_source.materialization import materialize_retained_source, verify_source_manifest
from app.services.returns_series_source.replay import replay_retained_portfolio_source
from app.services.runtime_retention_legal_hold import RuntimeRetentionLegalHold, RuntimeRetentionLegalHoldIndex
from app.services.runtime_retention_service import (
    RuntimeRetentionCleanupFailed,
    _collect_prunable_items,
    run_runtime_retention_cleanup,
)
from app.workers.compute_executor_worker import process_pending_jobs as compute_jobs
from app.workers.lineage_worker import process_pending_jobs as lineage_jobs
from core.errors import APINotFoundError, APIServiceUnavailableError


@pytest.fixture
def source_runtime(tmp_path, monkeypatch):
    # These Windows-capable fixtures simulate publication barriers. Native Linux
    # filesystem/volume crash durability is a separate deployment acceptance gate.
    monkeypatch.setattr("app.services.returns_series_source.capture.sync_directory", lambda path: None, raising=False)
    monkeypatch.setattr(
        "app.services.returns_series_source.materialization.sync_directory", lambda path: None, raising=False
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "LINEAGE_METADATA_DATABASE_URL", f"sqlite:///{tmp_path / 'metadata.db'}")
    monkeypatch.setattr(settings, "LINEAGE_STORAGE_PATH", tmp_path / "lineage")
    settings.LINEAGE_STORAGE_PATH.mkdir()
    bootstrap_durable_metadata_stores()
    token = tenant_id_var.set("tenant-source")
    calls = []

    async def post(**kwargs):
        request = kwargs["json_body"]
        calls.append(request)
        number = 0 if request["page"]["page_token"] is None else 1
        assert request["page"]["page_token"] in (None, "opaque-page-two")
        payload = {
            "portfolio_open_date": "2026-02-23",
            "portfolio_currency": "USD",
            "reporting_currency": "USD",
            "observations": [
                {
                    "valuation_date": f"2026-02-{23 + number}",
                    "beginning_market_value": "1000.00000000000000000000",
                    "ending_market_value": "1090.00000000000000000000",
                    "cash_flows": [{"amount": "-10.00000000000000000000", "timing": "eod", "cash_flow_type": "fee"}],
                }
            ],
            "page": {"returned_row_count": 1, "next_page_token": "opaque-page-two" if number == 0 else None},
        }
        response = httpx.Response(200, content=json.dumps(payload, indent=1).encode())
        from app.services.http_resilience import response_payload

        return 200, kwargs.get("response_decoder", response_payload)(response)

    monkeypatch.setattr("app.services.core_integration_service.post_with_retry", post)
    yield settings, calls
    tenant_id_var.reset(token)


def source_request(basis="NET"):
    return ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "fixture-portfolio",
            "as_of_date": "2026-02-24",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
            "frequency": "DAILY",
            "metric_basis": basis,
            "reporting_currency": "USD",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )


@pytest.mark.parametrize("path", ["inline", "async", "promotion"])
@pytest.mark.parametrize("basis,expected", [("NET", "0.09"), ("GROSS", "0.10")])
def test_all_execution_paths_retain_fee_once_source_and_survive_queue_retirement(
    source_runtime, monkeypatch, path, basis, expected
):
    settings, calls = source_runtime
    monkeypatch.setattr(settings, "RETURNS_SERIES_EXECUTOR_WINDOW_DAYS", 1 if path == "async" else 180)
    monkeypatch.setattr(settings, "RETURNS_SERIES_EXECUTOR_INPUT_COUNT", 2 if path == "promotion" else 250)
    request = source_request(basis)
    asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    if path != "inline":
        assert compute_jobs(limit=1) == 1
    execution = execution_registry.get_execution(request.calculation_id)
    assert execution.status.value == "complete", execution.error_message
    assert all(
        Decimal(point["return_value"]) == Decimal(expected)
        for point in execution.response_payload["series"]["portfolio_returns"]
    )
    record = lineage_metadata_store.get_record(request.calculation_id)
    assert record.source_custody_state == "pending_materialization", record
    assert record.source_root_digest and record.source_manifest_digest is None
    assert len(calls) == 2
    assert lineage_jobs(limit=1) == 1
    assert lineage_metadata_store.get_payload(request.calculation_id) is None
    response = resolve_lineage_response(calculation_id=request.calculation_id, artifact_url_factory=lambda name: name)
    assert response.source_custody_state == "complete"
    archive = next(name for name in response.artifacts if name.endswith(".bin"))
    reference = resolve_lineage_artifact_file(calculation_id=request.calculation_id, artifact_name=archive)
    with open(reference.path, "rb") as retained:
        assert retained.read().count(b"1000.00000000000000000000") == 2

    def source_off(**kwargs):
        raise AssertionError("Source-off replay must not retrieve upstream data")

    monkeypatch.setattr("app.services.core_integration_service.post_with_retry", source_off)
    proof = replay_retained_portfolio_source(
        database_url=settings.LINEAGE_METADATA_DATABASE_URL,
        storage_path=settings.LINEAGE_STORAGE_PATH,
        calculation_id=request.calculation_id,
        tenant_id="tenant-source",
    )
    assert proof["matched"] and proof["replayed_portfolio_points"] == 2
    if path == "inline" and basis == "NET":
        native = subprocess.run(
            [
                sys.executable,
                "scripts/replay_returns_series_source.py",
                "--database-url",
                settings.LINEAGE_METADATA_DATABASE_URL,
                "--storage-path",
                str(settings.LINEAGE_STORAGE_PATH),
                "--calculation-id",
                str(request.calculation_id),
                "--tenant-id",
                "tenant-source",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(native.stdout)["matched"] is True
    assert len(calls) == 2


def completed_source():
    request = source_request()
    asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    assert lineage_jobs(limit=1) == 1
    return request, lineage_metadata_store.get_record(request.calculation_id)


@pytest.mark.parametrize("barrier", ["parent", "root", "request", "response", "manifest"])
def test_directory_barrier_failure_never_selects_source_authority(source_runtime, monkeypatch, barrier):
    settings, _ = source_runtime
    request = source_request()
    observed = []

    def barrier_control(path):
        if path == settings.LINEAGE_STORAGE_PATH:
            phase = "parent"
        elif list(path.glob("*.manifest.json")):
            phase = "manifest"
        elif list(path.glob("*.response.json")):
            phase = "response"
        elif list(path.glob("*.request.json")):
            phase = "request"
        else:
            phase = "root"
        observed.append(phase)
        record = lineage_metadata_store.get_record(request.calculation_id)
        assert record.source_manifest_digest is None
        if phase in {"parent", "root"}:
            assert record.source_root_digest is None or phase == "parent"
        if phase == barrier:
            raise OSError("injected directory durability failure")

    monkeypatch.setattr("app.services.returns_series_source.capture.sync_directory", barrier_control, raising=False)
    monkeypatch.setattr(
        "app.services.returns_series_source.materialization.sync_directory", barrier_control, raising=False
    )
    response = asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    assert response.series.portfolio_returns[0].return_value == Decimal("0.09")
    if barrier in {"parent", "root"}:
        record = lineage_metadata_store.get_record(request.calculation_id)
        assert record.source_custody_state == "failed" and record.source_root_digest is None
    else:
        assert lineage_jobs(limit=1) == 0
        record = lineage_metadata_store.get_record(request.calculation_id)
        assert record.source_custody_state == "pending_materialization" and record.source_manifest_digest is None
        # Durable files may exist after a failed barrier; idempotent retry must
        # execute the barrier again before complete authority can be selected.
        monkeypatch.setattr(
            "app.services.returns_series_source.materialization.sync_directory", lambda path: observed.append("retry")
        )
        assert lineage_jobs(limit=1) == 1
        assert lineage_metadata_store.get_record(request.calculation_id).source_custody_state == "complete"
        assert "retry" in observed
    assert barrier in observed


@pytest.mark.parametrize("mutation", ["authority", "root", "names", "digests"])
def test_hash_valid_manifest_still_requires_consistent_selected_identity(source_runtime, mutation):
    settings, _ = source_runtime
    request, record = completed_source()
    directory = settings.LINEAGE_STORAGE_PATH / str(request.calculation_id)
    manifest = json.loads((directory / f"source-{record.source_manifest_digest}.manifest.json").read_bytes())
    if mutation == "authority":
        record = replace(record, source_manifest_digest=None)
    else:
        if mutation == "root":
            manifest["source_root_digest"] = "f" * 64
        elif mutation == "names":
            manifest["artifact_names"] = []
        else:
            manifest["artifact_sha256"] = {}
        content = json_bytes(manifest)
        digest = hashlib.sha256(content).hexdigest()
        (directory / f"source-{digest}.manifest.json").write_bytes(content)
        record = replace(record, source_manifest_digest=digest)
    with pytest.raises(SourceArchiveError):
        verify_source_manifest(directory, record=record)


@pytest.mark.parametrize("mutation", ["authority", "request"])
def test_materializer_refuses_missing_authority_or_changed_request(source_runtime, mutation):
    settings, _ = source_runtime
    request, record = completed_source()
    if mutation == "authority":
        record = replace(record, source_root_digest=None)
    with pytest.raises(SourceArchiveError):
        materialize_retained_source(
            record=record,
            store=lineage_metadata_store,
            storage_path=settings.LINEAGE_STORAGE_PATH,
            request_json="{}",
            response_json="{}",
            worker_id="stale",
            expected_attempt_count=1,
        )


@pytest.mark.parametrize("mutation", ["foreign", "pending", "normalization", "points", "opening"])
def test_source_off_replay_refuses_missing_authority_and_normalization_drift(source_runtime, monkeypatch, mutation):
    from app.services.returns_series_source import replay

    settings, _ = source_runtime
    request, record = completed_source()
    if mutation == "pending":
        monkeypatch.setattr(
            replay,
            "_load_replay_records",
            lambda *args: (
                execution_registry.get_execution(request.calculation_id),
                replace(record, source_custody_state="pending_materialization"),
            ),
        )
    elif mutation == "normalization":
        monkeypatch.setattr(replay, "_source_inputs_from_archive", lambda *args: ([], "2026-02-23"))
    elif mutation == "points":
        monkeypatch.setattr(replay, "points_from_df", lambda *args: [])
    elif mutation == "opening":
        original = replay._record_portfolio_chunk_payload

        def without_opening(*, accumulator, payload):
            original(accumulator=accumulator, payload=payload)
            accumulator.portfolio_open_date = None

        monkeypatch.setattr(replay, "_record_portfolio_chunk_payload", without_opening)
    with pytest.raises(SourceArchiveError):
        replay_retained_portfolio_source(
            database_url=settings.LINEAGE_METADATA_DATABASE_URL,
            storage_path=settings.LINEAGE_STORAGE_PATH,
            calculation_id=request.calculation_id,
            tenant_id="foreign" if mutation == "foreign" else "tenant-source",
        )


def test_completed_source_cannot_be_reset_by_generic_failure(source_runtime):
    request, record = completed_source()
    assert not lineage_metadata_store.mark_failed_if_present(request.calculation_id, "late legacy failure")
    assert lineage_metadata_store.get_record(request.calculation_id) == record


def test_frozen_resolution_refuses_changed_admitted_request(source_runtime):
    from app.services.returns_series_source.custody import SourceCustodyClaim, SourceCustodyConflict
    from app.services.returns_series_source.workflow import _load_frozen_resolution

    settings, _ = source_runtime
    request, record = completed_source()
    changed = request.model_copy(update={"portfolio_id": "different-portfolio"})
    claim = SourceCustodyClaim(request.calculation_id, "tenant-source", "reader", 0)
    with pytest.raises(SourceCustodyConflict, match="admitted request"):
        _load_frozen_resolution(
            settings.LINEAGE_STORAGE_PATH / str(request.calculation_id),
            root=record.source_root_digest,
            claim=claim,
            request=changed,
        )


def test_failed_capture_retry_keeps_arithmetic_available_without_resetting_custody(source_runtime, monkeypatch):
    from app.services.returns_series_service import resolve_stateful_returns_series_request
    from app.services.returns_series_source.custody import SourceCustodyConflict
    from app.services.returns_series_source.workflow import active_compute_source_claim

    request = source_request()
    execution_registry.register_execution(
        calculation_id=request.calculation_id,
        analytics_type="ReturnsSeries",
        tenant_id="tenant-source",
        portfolio_id=request.portfolio_id,
        execution_mode="sync",
        requested_window={},
        input_fingerprint="fixture",
        calculation_hash="fixture",
    )
    with monkeypatch.context() as fault:

        def failed_freeze(*args, **kwargs):
            raise OSError("storage failed")

        fault.setattr("app.services.returns_series_source.capture.PortfolioSourceCapture.freeze", failed_freeze)
        original = asyncio.run(resolve_stateful_returns_series_request(request))
    before = lineage_metadata_store.get_record(request.calculation_id)
    assert before.source_custody_state == "failed" and before.source_root_digest is None
    with pytest.raises(SourceCustodyConflict, match="inline attempt"):
        asyncio.run(resolve_stateful_returns_series_request(request))
    token = active_compute_source_claim.set((execution_registry, original.source_custody_claim))
    try:
        resolved = asyncio.run(resolve_stateful_returns_series_request(request))
    finally:
        active_compute_source_claim.reset(token)
    assert resolved.request.stateless_input.portfolio_returns
    assert lineage_metadata_store.get_record(request.calculation_id) == before


@pytest.mark.parametrize(
    "target", [".bin", ".jsonl", ".bundle.json", ".manifest.json", ".response.json", "normalized", "directory"]
)
def test_retained_reads_refuse_corrupted_selected_content(source_runtime, target, monkeypatch):
    settings, _ = source_runtime
    request, record = completed_source()
    directory = settings.LINEAGE_STORAGE_PATH / str(request.calculation_id)
    if target == "directory":
        from pathlib import Path

        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == directory or original(path))
        with pytest.raises(APIServiceUnavailableError):
            resolve_lineage_response(calculation_id=request.calculation_id, artifact_url_factory=lambda name: name)
        return
    if target == ".manifest.json":
        name = f"source-{record.source_manifest_digest}.manifest.json"
    elif target == "normalized":
        name = next(
            name
            for name in record.artifact_names
            if name.endswith(".json") and not name.endswith((".bundle.json", ".request.json", ".response.json"))
        )
    else:
        name = next(name for name in record.artifact_names if name.endswith(target))
    path = directory / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(APIServiceUnavailableError):
        resolve_lineage_response(calculation_id=request.calculation_id, artifact_url_factory=lambda name: name)


@pytest.mark.parametrize("authority", ["foreign", "missing"])
def test_raw_source_denied_without_matching_retained_execution(source_runtime, authority):
    request, record = completed_source()
    if authority == "foreign":
        token = tenant_id_var.set("other-tenant")
    else:
        execution_registry.delete_execution(request.calculation_id)
        token = None
    try:
        with pytest.raises(APINotFoundError):
            resolve_lineage_artifact_file(calculation_id=request.calculation_id, artifact_name=record.artifact_names[0])
    finally:
        if token is not None:
            tenant_id_var.reset(token)


@pytest.mark.parametrize(
    "failure", ["storage", "enqueue", "directory", "spool", "failure_persist", "unsupported_native"]
)
def test_custody_failure_is_visible_without_changing_arithmetic(source_runtime, monkeypatch, failure, caplog):
    if failure == "unsupported_native":
        from app.services.returns_series_source.durability import sync_directory

        if sys.platform == "linux":
            pytest.skip("Native unsupported-platform control applies outside the supported Linux deployment.")
        # Replace the fixture's simulated barrier with the real native guard.
        # Do not mock platform detection, os.open/fsync, or the error type.
        monkeypatch.setattr("app.services.returns_series_source.capture.sync_directory", sync_directory)
    elif failure in {"storage", "directory", "spool"}:

        def unavailable(*args, **kwargs):
            raise OSError("fixture storage failure")

        target = {
            "storage": "capture.PortfolioSourceCapture.freeze",
            "directory": "workflow.source_directory",
            "spool": "workflow.PortfolioSourceCapture",
        }[failure]
        monkeypatch.setattr("app.services.returns_series_source." + target, unavailable)
    else:
        original = ExecutionRegistry.select_returns_series_source_root

        def unavailable(self, **kwargs):
            if kwargs.get("materialization") is not None or failure == "failure_persist" and kwargs.get("failure"):
                raise OSError("fixture enqueue failure")
            return original(self, **kwargs)

        monkeypatch.setattr(ExecutionRegistry, "select_returns_series_source_root", unavailable)
    request = source_request()
    response = asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    assert response.series.portfolio_returns[0].return_value == Decimal("0.09")
    record = lineage_metadata_store.get_record(request.calculation_id)
    expected_state = "frozen" if failure == "failure_persist" else "failed"
    assert record.source_custody_state == expected_state
    assert execution_registry.get_execution(request.calculation_id).status.value == "complete"
    if failure == "unsupported_native":
        assert record.source_root_digest is None and record.source_manifest_digest is None
    assert lineage_metadata_store.get_payload(request.calculation_id) is None
    assert (
        resolve_lineage_response(
            calculation_id=request.calculation_id, artifact_url_factory=lambda name: name
        ).source_custody_state
        == expected_state
    )
    if failure == "failure_persist":
        arithmetic = execution_registry.get_execution(request.calculation_id)
        root = record.source_root_digest
        with monkeypatch.context() as unavailable_metadata:

            def unavailable_reconciliation(*args, **kwargs):
                raise OSError("fixture metadata maintenance outage")

            unavailable_metadata.setattr(
                "app.services.lineage_metadata_store.LineageMetadataStore.reconcile_stranded_source_custody",
                unavailable_reconciliation,
            )
            assert lineage_jobs(worker_id="outage-lineage-worker") == 0
        warnings = [record for record in caplog.records if "Source custody reconciliation failed" in record.message]
        assert len(warnings) == 1
        assert warnings[0].extra_fields["failure_classification"] == "source_custody_reconciliation_failed"
        assert warnings[0].extra_fields["retryable"] is True
        assert lineage_metadata_store.get_record(request.calculation_id) == record
        assert lineage_jobs(worker_id="restarted-lineage-worker") == 0
        terminal = lineage_metadata_store.get_record(request.calculation_id)
        assert terminal.source_custody_state == "failed"
        assert terminal.source_root_digest == root
        assert terminal.source_manifest_digest is None
        assert terminal.error_message == "Source materialization was not queued before arithmetic became terminal."
        assert execution_registry.get_execution(request.calculation_id) == arithmetic
        assert lineage_metadata_store.reconcile_stranded_source_custody(limit=10) == 0
        assert lineage_metadata_store.get_record(request.calculation_id) == terminal


def test_stale_materializer_attempt_cannot_select_manifest_then_restart_finishes(source_runtime):
    settings, _ = source_runtime
    request = source_request()
    asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    payload = lineage_metadata_store.lease_pending_payload(
        calculation_id=request.calculation_id,
        worker_id="same-worker",
        lease_seconds=120,
    )
    with lineage_metadata_store._engine.begin() as connection:
        connection.execute(text("UPDATE lineage_payloads SET attempt_count = attempt_count + 1"))
    service = LineageService(storage_path=str(settings.LINEAGE_STORAGE_PATH))
    arguments = dict(
        calculation_id=payload.calculation_id,
        calculation_type=payload.calculation_type,
        request_json=payload.request_json,
        response_json=payload.response_json,
        calculation_details=payload.details,
        worker_id=payload.worker_id,
    )
    with pytest.raises(LineagePayloadLeaseOwnershipError):
        service.materialize_payload(**arguments, expected_attempt_count=payload.attempt_count)
    assert lineage_metadata_store.get_record(request.calculation_id).source_manifest_digest is None
    assert service.materialize_payload(**arguments, expected_attempt_count=payload.attempt_count + 1)
    selected = lineage_metadata_store.get_record(request.calculation_id).source_manifest_digest
    with pytest.raises(LineagePayloadLeaseOwnershipError):
        service.materialize_payload(**arguments, expected_attempt_count=payload.attempt_count)
    assert lineage_metadata_store.get_record(request.calculation_id).source_manifest_digest == selected


@pytest.mark.parametrize("exhaust", [False, True])
def test_lineage_retry_and_exhaustion_preserve_arithmetic_and_source_identity(source_runtime, monkeypatch, exhaust):
    request = source_request()
    asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    before = lineage_metadata_store.get_record(request.calculation_id)
    execution_before = execution_registry.get_execution(request.calculation_id)
    with monkeypatch.context() as fault:

        def fail(**kwargs):
            raise OSError("interrupted materialization")

        fault.setattr("app.services.returns_series_source.materialization.materialize_retained_source", fail)
        assert lineage_jobs(limit=1, max_attempts=1 if exhaust else 3) == 0
    failed = lineage_metadata_store.get_record(request.calculation_id)
    assert failed.source_root_digest == before.source_root_digest
    assert (
        execution_registry.get_execution(request.calculation_id).response_payload == execution_before.response_payload
    )
    assert execution_registry.get_execution(request.calculation_id).status.value == "complete"
    if exhaust:
        assert failed.source_custody_state == "failed" and failed.status.value == "failed"
        assert lineage_jobs(limit=1) == 0
    else:
        assert failed.source_custody_state == "pending_materialization"
        assert lineage_jobs(limit=1) == 1


@pytest.mark.parametrize("publication_unavailable", [False, True])
def test_compute_retry_reuses_frozen_source_after_provider_is_unavailable(
    source_runtime, monkeypatch, publication_unavailable
):
    import app.services.returns_series_service as calculator

    settings, calls = source_runtime
    monkeypatch.setattr(settings, "RETURNS_SERIES_EXECUTOR_WINDOW_DAYS", 1)
    request = source_request()
    asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    with monkeypatch.context() as fault:

        def interrupted(**kwargs):
            raise RuntimeError("interruption after source freeze")

        fault.setattr(calculator, "_build_returns_series_execution_result", interrupted)
        assert compute_jobs(limit=1) == 1
    frozen = lineage_metadata_store.get_record(request.calculation_id)
    assert frozen.source_custody_state == "frozen" and frozen.source_root_digest

    def source_off(**kwargs):
        raise AssertionError("Frozen retry cannot call Core")

    monkeypatch.setattr("app.services.core_integration_service.post_with_retry", source_off)
    if publication_unavailable:

        def refuse_new_publication(path):
            raise OSError("publication unavailable during frozen retry")

        monkeypatch.setattr("app.services.returns_series_source.capture.sync_directory", refuse_new_publication)
    assert compute_jobs(limit=1) == 1
    current = lineage_metadata_store.get_record(request.calculation_id)
    assert current.source_root_digest == frozen.source_root_digest
    assert current.source_attempt_id == frozen.source_attempt_id
    assert current.source_custody_state == ("failed" if publication_unavailable else "pending_materialization")
    assert execution_registry.get_execution(request.calculation_id).status.value == "complete"
    assert lineage_jobs(limit=1) == (0 if publication_unavailable else 1) and len(calls) == 2


@pytest.mark.parametrize("stranded", [False, True])
def test_retention_protects_pending_authority_and_hold_then_retires_whole_eligible_group(
    source_runtime, monkeypatch, stranded
):
    if stranded:
        original = ExecutionRegistry.select_returns_series_source_root

        def missing_producer_write(self, **kwargs):
            if kwargs.get("materialization") is not None or kwargs.get("failure"):
                raise OSError("fixture dual producer write outage")
            return original(self, **kwargs)

        monkeypatch.setattr(ExecutionRegistry, "select_returns_series_source_root", missing_producer_write)
    request = source_request()
    asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    identifier = str(request.calculation_id)
    cutoff = datetime.now(timezone.utc) + timedelta(days=1)
    pending = _collect_prunable_items(cutoff=cutoff)
    assert identifier in pending.protected_execution_ids
    assert identifier not in pending.execution_ids
    assert lineage_jobs(limit=1) == (0 if stranded else 1)
    record = lineage_metadata_store.get_record(request.calculation_id)
    assert record.source_custody_state == ("failed" if stranded else "complete")
    recent = _collect_prunable_items(cutoff=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert identifier not in recent.execution_ids and identifier not in recent.lineage_ids
    eligible = _collect_prunable_items(cutoff=cutoff)
    assert identifier in eligible.execution_ids and identifier in eligible.lineage_ids
    hold = RuntimeRetentionLegalHold(identifier, "fixture_hold")
    monkeypatch.setattr(
        "app.services.runtime_retention_service.load_runtime_retention_legal_hold_index",
        lambda: RuntimeRetentionLegalHoldIndex({identifier: hold}),
    )
    held = _collect_prunable_items(cutoff=cutoff)
    assert identifier in held.protected_execution_ids and identifier in held.protected_lineage_ids
    assert identifier not in held.execution_ids and identifier not in held.lineage_ids
    monkeypatch.setattr(
        "app.services.runtime_retention_service.load_runtime_retention_legal_hold_index",
        lambda: RuntimeRetentionLegalHoldIndex({}),
    )
    # Exercise interrupted retirement only against this test's owned SQLite/files.
    with monkeypatch.context() as interruption:

        def interrupted_delete(*args, **kwargs):
            raise OSError("fixture interruption at execution retirement")

        interruption.setattr(ExecutionRegistry, "delete_executions", interrupted_delete)
        with pytest.raises(RuntimeRetentionCleanupFailed):
            run_runtime_retention_cleanup(retention_days=30, now=cutoff + timedelta(days=30))
    assert lineage_metadata_store.get_record(request.calculation_id) is None
    assert execution_registry.get_execution(request.calculation_id) is not None
    run_runtime_retention_cleanup(retention_days=30, now=cutoff + timedelta(days=30))
    assert execution_registry.get_execution(request.calculation_id) is None


def test_complete_year_workload_retains_every_planned_chunk_and_page(source_runtime, monkeypatch):
    settings, _ = source_runtime
    calls = []

    async def paged_source(**kwargs):
        request = kwargs["json_body"]
        start = date.fromisoformat(request["window"]["start_date"])
        end = date.fromisoformat(request["window"]["end_date"])
        offset = 0 if request["page"]["page_token"] is None else 50
        rows = [
            {
                "valuation_date": (start + timedelta(days=index)).isoformat(),
                "beginning_market_value": "1000.00000000000000000000",
                "ending_market_value": "1010.00000000000000000000",
                "cash_flows": [],
            }
            for index in range((end - start).days + 1)
        ]
        selected = rows[offset : offset + 50]
        payload = {
            "portfolio_open_date": "2025-02-24",
            "portfolio_currency": "USD",
            "reporting_currency": "USD",
            "observations": selected,
            "page": {
                "returned_row_count": len(selected),
                "next_page_token": "second" if len(rows) > offset + 50 else None,
            },
        }
        calls.append(request)
        return 200, kwargs["response_decoder"](httpx.Response(200, content=json.dumps(payload).encode()))

    monkeypatch.setattr("app.services.core_integration_service.post_with_retry", paged_source)
    request = source_request().model_copy(
        update={
            "window": source_request().window.model_copy(update={"from_date": date(2025, 2, 24)}),
        }
    )
    asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
    assert compute_jobs(limit=1) == 1
    assert execution_registry.get_execution(request.calculation_id).status.value == "complete"
    assert lineage_jobs(limit=1) == 1
    record = lineage_metadata_store.get_record(request.calculation_id)
    directory = settings.LINEAGE_STORAGE_PATH / str(request.calculation_id)
    descriptor = json.loads((directory / f"source-{record.source_root_digest}.bundle.json").read_bytes())
    assert descriptor["scope"]["chunk_count"] == 5
    assert descriptor["archive_digest"]["observation_count"] == 366
    assert descriptor["archive_digest"]["page_count"] == len(calls) == 9
    proof = replay_retained_portfolio_source(
        database_url=settings.LINEAGE_METADATA_DATABASE_URL,
        storage_path=settings.LINEAGE_STORAGE_PATH,
        calculation_id=request.calculation_id,
        tenant_id="tenant-source",
    )
    assert proof["matched"] and proof["replayed_portfolio_points"] == 366


@pytest.mark.parametrize("mode", ["inline", "async", "cancel_promotion"])
def test_terminal_arithmetic_or_cancellation_releases_unfinished_custody(source_runtime, monkeypatch, mode):
    import app.services.returns_series_service as calculator

    settings, _ = source_runtime
    monkeypatch.setattr(settings, "RETURNS_SERIES_EXECUTOR_WINDOW_DAYS", 1 if mode == "async" else 180)
    monkeypatch.setattr(settings, "RETURNS_SERIES_EXECUTOR_INPUT_COUNT", 2 if mode == "cancel_promotion" else 250)
    request = source_request()
    if mode == "cancel_promotion":
        asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
        assert compute_job_store.cancel_pending_job(
            request.calculation_id, tenant_id="tenant-source", reason="fixture cancellation"
        )
        assert compute_jobs(limit=1) == 0
    else:

        def terminal(**kwargs):
            raise ValueError("fixture terminal arithmetic failure")

        monkeypatch.setattr(calculator, "_build_returns_series_execution_result", terminal)
        if mode == "inline":
            with pytest.raises(ValueError, match="fixture terminal"):
                asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
        else:
            asyncio.run(calculate_returns_series_workflow(ReturnsSeriesWorkflowCommand(request)))
            assert compute_jobs(limit=1) == 1
    record = lineage_metadata_store.get_record(request.calculation_id)
    assert record.source_root_digest and record.source_custody_state == "failed"
    assert record.status.value == "failed"
