from uuid import uuid4

from app.services.async_result_store import AsyncResultRecord, AsyncResultStatus
from app.services.compute_job_store import ComputeJobRecord, ComputeJobStatus
from app.services.durable_failure_classification import GENERIC_ASYNC_FAILURE_MESSAGE, DurableFailureClassification
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
        self.requested_tenant_id = None

    def get_job(self, calculation_id, *, tenant_id):
        self.requested_calculation_id = calculation_id
        self.requested_tenant_id = tenant_id
        return self.job


class _AsyncResultStoreStub:
    def __init__(self, async_result: AsyncResultRecord | None) -> None:
        self.async_result = async_result
        self.requested_calculation_id = None
        self.requested_tenant_id = None

    def get_result(self, calculation_id, *, tenant_id):
        self.requested_calculation_id = calculation_id
        self.requested_tenant_id = tenant_id
        return self.async_result


class _ExecutionPollingStoreStub:
    def __init__(
        self,
        *,
        record: ExecutionRecord | None,
        job: ComputeJobRecord | None = None,
        async_result: AsyncResultRecord | None = None,
    ) -> None:
        self.execution_store = _ExecutionStoreStub(record)
        self.compute_store = _ComputeJobStoreStub(job)
        self.result_store = _AsyncResultStoreStub(async_result)

    def get_execution(self, calculation_id):
        return self.execution_store.get_execution(calculation_id)

    def get_job(self, calculation_id, *, tenant_id):
        return self.compute_store.get_job(calculation_id, tenant_id=tenant_id)

    def get_result(self, calculation_id, *, tenant_id):
        return self.result_store.get_result(calculation_id, tenant_id=tenant_id)


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


def test_build_execution_response_exposes_versioned_failure_classification():
    calculation_id = uuid4()
    failure = DurableFailureClassification(
        contract_version="v1",
        status_code=422,
        error_code="PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE",
        message="History window exceeds the governed maximum.",
        retryable=False,
    )
    record = _execution_record(calculation_id)
    record = ExecutionRecord(**{**record.__dict__, "failure": failure, "status": ExecutionStatus.FAILED})
    job = _compute_job_record(calculation_id)
    job = ComputeJobRecord(**{**job.__dict__, "failure": failure, "job_status": ComputeJobStatus.FAILED})

    response = build_execution_response(record=record, job=job, async_result=None)

    assert response.failure is not None
    assert response.failure.error_code == "PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE"
    assert response.compute_job is not None
    assert response.compute_job.failure == response.failure


def test_build_execution_response_sanitizes_legacy_failure_messages():
    calculation_id = uuid4()
    failed_stage = ExecutionStageRecord(
        stage_name="calculation",
        status=ExecutionStageStatus.FAILED,
        started_at_utc="2026-03-14T00:00:00Z",
        completed_at_utc="2026-03-14T00:00:01Z",
        details=None,
        error_message="database password leaked",
    )
    record = _execution_record(calculation_id, stages=[failed_stage])
    record = ExecutionRecord(
        **{
            **record.__dict__,
            "status": ExecutionStatus.FAILED,
            "error_message": "database password leaked",
        }
    )
    job = _compute_job_record(calculation_id)
    job = ComputeJobRecord(
        **{
            **job.__dict__,
            "job_status": ComputeJobStatus.FAILED,
            "error_message": "database password leaked",
        }
    )
    async_result = _async_result_record(calculation_id)
    async_result = AsyncResultRecord(
        **{
            **async_result.__dict__,
            "result_status": AsyncResultStatus.FAILED,
            "error_message": "database password leaked",
        }
    )

    response = build_execution_response(record=record, job=job, async_result=async_result)

    assert response.error_message == GENERIC_ASYNC_FAILURE_MESSAGE
    assert response.stages[0].error_message == GENERIC_ASYNC_FAILURE_MESSAGE
    assert response.compute_job is not None
    assert response.compute_job.error_message == GENERIC_ASYNC_FAILURE_MESSAGE
    assert response.async_result is not None
    assert response.async_result.error_message == GENERIC_ASYNC_FAILURE_MESSAGE


def test_get_execution_polling_response_reads_durable_metadata_once():
    calculation_id = uuid4()
    record = _execution_record(calculation_id)
    job = _compute_job_record(calculation_id)
    async_result = _async_result_record(calculation_id)
    store = _ExecutionPollingStoreStub(record=record, job=job, async_result=async_result)

    response = get_execution_polling_response(
        calculation_id,
        store=store,
        request_headers={"X-Tenant-Id": "tenant-private-bank"},
    )

    assert response is not None
    assert response.calculation_id == calculation_id
    assert response.compute_job is not None
    assert response.async_result is not None
    assert store.execution_store.requested_calculation_id == calculation_id
    assert store.compute_store.requested_calculation_id == calculation_id
    assert store.compute_store.requested_tenant_id == "tenant-private-bank"
    assert store.result_store.requested_calculation_id == calculation_id
    assert store.result_store.requested_tenant_id == "tenant-private-bank"


def test_get_execution_polling_response_skips_async_stores_when_execution_missing():
    calculation_id = uuid4()
    store = _ExecutionPollingStoreStub(record=None)

    assert get_execution_polling_response(calculation_id, store=store) is None
    assert store.execution_store.requested_calculation_id == calculation_id
    assert store.compute_store.requested_calculation_id is None
    assert store.result_store.requested_calculation_id is None


def test_get_execution_polling_response_uses_persisted_empty_tenant_for_stateless_metadata():
    calculation_id = uuid4()
    record = _execution_record(calculation_id, tenant_id="")
    store = _ExecutionPollingStoreStub(record=record)

    response = get_execution_polling_response(
        calculation_id,
        store=store,
        request_headers={"X-Tenant-Id": "tenant-private-bank"},
    )

    assert response is not None
    assert store.compute_store.requested_tenant_id == ""
    assert store.result_store.requested_tenant_id == ""


def test_execution_polling_not_found_detail_is_legacy_error_contract():
    assert EXECUTION_POLLING_NOT_FOUND_DETAIL == "Execution data not found for the given calculation_id."


def _execution_record(
    calculation_id,
    *,
    stages: list[ExecutionStageRecord] | None = None,
    upstream_snapshots: list[UpstreamSnapshotRecord] | None = None,
    tenant_id: str | None = "tenant-private-bank",
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
        tenant_id=tenant_id,
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
        tenant_id="tenant-test",
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
