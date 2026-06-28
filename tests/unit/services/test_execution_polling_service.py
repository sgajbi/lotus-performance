from uuid import uuid4

from app.services.async_result_store import AsyncResultRecord, AsyncResultStatus
from app.services.compute_job_store import ComputeJobRecord, ComputeJobStatus
from app.services.execution_polling_service import (
    EXECUTION_POLLING_NOT_FOUND_DETAIL,
    _compute_job_response,
    build_execution_response,
    get_execution_polling_response,
)
from app.services.execution_registry import (
    ExecutionRecord,
    ExecutionStageRecord,
    ExecutionStageStatus,
    ExecutionStatus,
    UpstreamSnapshotRecord,
)


class _ExecutionStoreStub:
    def __init__(self, record: ExecutionRecord | None) -> None:
        self.record = record
        self.requested_calculation_id = None

    def get_execution(self, calculation_id):
        self.requested_calculation_id = calculation_id
        return self.record


class _ComputeJobStoreStub:
    def __init__(self, job: ComputeJobRecord | None) -> None:
        self.job = job
        self.requested_calculation_id = None

    def get_job(self, calculation_id):
        self.requested_calculation_id = calculation_id
        return self.job


class _AsyncResultStoreStub:
    def __init__(self, async_result: AsyncResultRecord | None) -> None:
        self.async_result = async_result
        self.requested_calculation_id = None

    def get_result(self, calculation_id):
        self.requested_calculation_id = calculation_id
        return self.async_result


def test_build_execution_response_includes_compute_job_and_async_result():
    calculation_id = uuid4()
    record = _execution_record(calculation_id)
    job = _compute_job_record(calculation_id)
    async_result = _async_result_record(calculation_id)

    response = build_execution_response(record=record, job=job, async_result=async_result)

    assert response.calculation_id == calculation_id
    assert response.stages[0].stage_name == "submission"
    assert response.stages[0].details == {"offload_reason": "large_input"}
    assert response.upstream_snapshots[0].upstream_endpoint == "portfolio_timeseries"
    assert response.upstream_snapshots[0].paging_metadata == {"page": 1}
    assert response.compute_job is not None
    assert response.compute_job.job_status == "complete"
    assert response.async_result is not None
    assert response.async_result.result_status == "complete"

    compute_job_response = _compute_job_response(job)

    assert compute_job_response is not None
    assert compute_job_response.job_status == "complete"
    assert compute_job_response.attempt_count == 1


def test_build_execution_response_handles_missing_optional_async_metadata():
    calculation_id = uuid4()
    record = _execution_record(calculation_id, stages=[], upstream_snapshots=[])

    response = build_execution_response(record=record, job=None, async_result=None)

    assert response.compute_job is None
    assert response.async_result is None
    assert response.upstream_snapshots == []
    assert _compute_job_response(None) is None


def test_get_execution_polling_response_reads_durable_metadata_once(monkeypatch):
    import app.services.execution_polling_service as service

    calculation_id = uuid4()
    record = _execution_record(calculation_id)
    job = _compute_job_record(calculation_id)
    async_result = _async_result_record(calculation_id)
    execution_store = _ExecutionStoreStub(record)
    compute_store = _ComputeJobStoreStub(job)
    result_store = _AsyncResultStoreStub(async_result)

    monkeypatch.setattr(service, "execution_registry", execution_store)
    monkeypatch.setattr(service, "compute_job_store", compute_store)
    monkeypatch.setattr(service, "async_result_store", result_store)

    response = get_execution_polling_response(calculation_id)

    assert response is not None
    assert response.calculation_id == calculation_id
    assert response.compute_job is not None
    assert response.async_result is not None
    assert execution_store.requested_calculation_id == calculation_id
    assert compute_store.requested_calculation_id == calculation_id
    assert result_store.requested_calculation_id == calculation_id


def test_get_execution_polling_response_skips_async_stores_when_execution_missing(monkeypatch):
    import app.services.execution_polling_service as service

    calculation_id = uuid4()
    execution_store = _ExecutionStoreStub(None)
    compute_store = _ComputeJobStoreStub(None)
    result_store = _AsyncResultStoreStub(None)

    monkeypatch.setattr(service, "execution_registry", execution_store)
    monkeypatch.setattr(service, "compute_job_store", compute_store)
    monkeypatch.setattr(service, "async_result_store", result_store)

    assert get_execution_polling_response(calculation_id) is None
    assert execution_store.requested_calculation_id == calculation_id
    assert compute_store.requested_calculation_id is None
    assert result_store.requested_calculation_id is None


def test_execution_polling_not_found_detail_is_legacy_error_contract():
    assert EXECUTION_POLLING_NOT_FOUND_DETAIL == "Execution data not found for the given calculation_id."


def _execution_record(
    calculation_id,
    *,
    stages: list[ExecutionStageRecord] | None = None,
    upstream_snapshots: list[UpstreamSnapshotRecord] | None = None,
) -> ExecutionRecord:
    return ExecutionRecord(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        portfolio_id="PORT-1",
        execution_mode="async",
        status=ExecutionStatus.COMPLETE,
        requested_window={"report_end_date": "2025-01-01"},
        input_fingerprint="sha256:input",
        calculation_hash="sha256:calc",
        error_message=None,
        created_at_utc="2026-03-14T00:00:00Z",
        started_at_utc="2026-03-14T00:00:01Z",
        completed_at_utc="2026-03-14T00:00:02Z",
        stages=stages if stages is not None else [_execution_stage()],
        upstream_snapshots=upstream_snapshots if upstream_snapshots is not None else [_upstream_snapshot()],
    )


def _execution_stage() -> ExecutionStageRecord:
    return ExecutionStageRecord(
        stage_name="submission",
        status=ExecutionStageStatus.COMPLETE,
        started_at_utc="2026-03-14T00:00:00Z",
        completed_at_utc="2026-03-14T00:00:00Z",
        details={"offload_reason": "large_input"},
        error_message=None,
    )


def _upstream_snapshot() -> UpstreamSnapshotRecord:
    return UpstreamSnapshotRecord(
        snapshot_id="snap-1",
        upstream_endpoint="portfolio_timeseries",
        source_identifier="PORT-1",
        as_of_date="2026-03-14",
        request_fingerprint="req",
        response_fingerprint="resp",
        retrieval_status="200",
        paging_metadata={"page": 1},
        created_at_utc="2026-03-14T00:00:00Z",
    )


def _compute_job_record(calculation_id) -> ComputeJobRecord:
    return ComputeJobRecord(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        job_status=ComputeJobStatus.COMPLETE,
        request_payload={"calculation_id": str(calculation_id)},
        response_payload={"calculation_id": str(calculation_id)},
        error_message=None,
        error_type=None,
        attempt_count=1,
        max_attempts=3,
        worker_id="worker-1",
        leased_at_utc=None,
        lease_expires_at_utc=None,
        last_error_at_utc=None,
        created_at_utc="2026-03-14T00:00:00Z",
        started_at_utc="2026-03-14T00:00:01Z",
        completed_at_utc="2026-03-14T00:00:02Z",
    )


def _async_result_record(calculation_id) -> AsyncResultRecord:
    return AsyncResultRecord(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        result_status=AsyncResultStatus.COMPLETE,
        response_payload={"calculation_id": str(calculation_id)},
        error_message=None,
        error_type=None,
        created_at_utc="2026-03-14T00:00:01Z",
        updated_at_utc="2026-03-14T00:00:02Z",
    )
