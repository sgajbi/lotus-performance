from uuid import uuid4

from app.models.execution_polling import _compute_job_response, build_execution_response
from app.services.async_result_store import AsyncResultRecord, AsyncResultStatus
from app.services.compute_job_store import ComputeJobRecord, ComputeJobStatus
from app.services.execution_registry import (
    ExecutionRecord,
    ExecutionStageRecord,
    ExecutionStageStatus,
    ExecutionStatus,
    UpstreamSnapshotRecord,
)


def test_build_execution_response_includes_compute_job_and_async_result():
    calculation_id = uuid4()
    record = ExecutionRecord(
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
        stages=[
            ExecutionStageRecord(
                stage_name="submission",
                status=ExecutionStageStatus.COMPLETE,
                started_at_utc="2026-03-14T00:00:00Z",
                completed_at_utc="2026-03-14T00:00:00Z",
                details={"offload_reason": "large_input"},
                error_message=None,
            )
        ],
        upstream_snapshots=[
            UpstreamSnapshotRecord(
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
        ],
    )
    job = ComputeJobRecord(
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
    async_result = AsyncResultRecord(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        result_status=AsyncResultStatus.COMPLETE,
        response_payload={"calculation_id": str(calculation_id)},
        error_message=None,
        error_type=None,
        created_at_utc="2026-03-14T00:00:01Z",
        updated_at_utc="2026-03-14T00:00:02Z",
    )

    response = build_execution_response(record=record, job=job, async_result=async_result)

    assert response.calculation_id == calculation_id
    assert response.stages[0].stage_name == "submission"
    assert response.upstream_snapshots[0].upstream_endpoint == "portfolio_timeseries"
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
    record = ExecutionRecord(
        calculation_id=calculation_id,
        analytics_type="TWR",
        portfolio_id="PORT-2",
        execution_mode="sync",
        status=ExecutionStatus.COMPLETE,
        requested_window={},
        input_fingerprint=None,
        calculation_hash=None,
        error_message=None,
        created_at_utc="2026-03-14T00:00:00Z",
        started_at_utc=None,
        completed_at_utc=None,
        stages=[],
        upstream_snapshots=[],
    )

    response = build_execution_response(record=record, job=None, async_result=None)

    assert response.compute_job is None
    assert response.async_result is None
    assert response.upstream_snapshots == []
    assert _compute_job_response(None) is None
