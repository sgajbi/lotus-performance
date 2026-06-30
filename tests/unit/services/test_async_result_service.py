import json
import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from app.services import async_result_service
from app.services.async_result_service import (
    ASYNC_RESULT_ANALYTICS_TYPE_MISMATCH_REASON,
    ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL,
    ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON,
    _is_active_async_job_status,
    _require_compute_job,
    _resolve_compute_job_result,
    resolve_async_result,
)
from app.services.async_result_store import AsyncResultRecord, AsyncResultStatus
from app.services.compute_job_store import ComputeJobRecord, ComputeJobStatus


class _AsyncResponse(BaseModel):
    calculation_id: UUID
    status: str


class _ResultStore:
    def __init__(self, result: AsyncResultRecord | None = None) -> None:
        self._result = result

    def get_result(self, calculation_id: UUID) -> AsyncResultRecord | None:
        del calculation_id
        return self._result


class _JobStore:
    def __init__(self, job: ComputeJobRecord) -> None:
        self._job = job

    def get_job(self, calculation_id: UUID) -> ComputeJobRecord:
        del calculation_id
        return self._job


def _job_record(
    calculation_id: UUID,
    *,
    job_status: ComputeJobStatus,
    analytics_type: str = "ReturnsSeries",
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> ComputeJobRecord:
    return ComputeJobRecord(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        job_status=job_status,
        request_payload={"calculation_id": str(calculation_id)},
        response_payload=response_payload,
        error_message=error_message,
        error_type=None,
        attempt_count=0,
        max_attempts=1,
        worker_id=None,
        leased_at_utc=None,
        lease_expires_at_utc=None,
        last_error_at_utc=None,
        created_at_utc="2026-06-13T00:00:00Z",
        started_at_utc=None,
        completed_at_utc=None,
    )


def _async_result_record(
    calculation_id: UUID,
    *,
    result_status: AsyncResultStatus,
    analytics_type: str = "ReturnsSeries",
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> AsyncResultRecord:
    return AsyncResultRecord(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        result_status=result_status,
        response_payload=response_payload,
        error_message=error_message,
        error_type=None,
        created_at_utc="2026-06-13T00:00:00Z",
        updated_at_utc="2026-06-13T00:00:01Z",
    )


def _accepted_response(calculation_id: UUID) -> _AsyncResponse:
    return _AsyncResponse(calculation_id=calculation_id, status="accepted")


def test_active_async_job_status_policy_covers_in_flight_statuses():
    assert _is_active_async_job_status(ComputeJobStatus.PENDING)
    assert _is_active_async_job_status(ComputeJobStatus.LEASED)
    assert _is_active_async_job_status(ComputeJobStatus.RUNNING)
    assert not _is_active_async_job_status(ComputeJobStatus.COMPLETE)
    assert not _is_active_async_job_status(ComputeJobStatus.FAILED)


def test_resolve_compute_job_result_raises_not_found_for_missing_job():
    with pytest.raises(HTTPException) as exc_info:
        _resolve_compute_job_result(
            calculation_id=uuid4(),
            job=None,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            accepted_response_factory=_accepted_response,
            not_found_detail="not found",
            failed_detail="failed",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"


def test_require_compute_job_returns_existing_job():
    calculation_id = uuid4()
    job = _job_record(calculation_id, job_status=ComputeJobStatus.COMPLETE)

    assert _require_compute_job(job, not_found_detail="not found") is job


def test_require_compute_job_raises_not_found_for_missing_job():
    with pytest.raises(HTTPException) as exc_info:
        _require_compute_job(None, not_found_detail="not found")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"


def test_resolve_compute_job_result_raises_conflict_for_failed_job():
    calculation_id = uuid4()
    job = _job_record(calculation_id, job_status=ComputeJobStatus.FAILED, error_message="worker failed")

    with pytest.raises(HTTPException) as exc_info:
        _resolve_compute_job_result(
            calculation_id=calculation_id,
            job=job,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            accepted_response_factory=_accepted_response,
            not_found_detail="not found",
            failed_detail="failed",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "worker failed"


def test_resolve_async_result_returns_accepted_for_active_compute_job(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(async_result_service, "async_result_store", _ResultStore())
    monkeypatch.setattr(
        async_result_service,
        "compute_job_store",
        _JobStore(_job_record(calculation_id, job_status=ComputeJobStatus.RUNNING)),
    )

    response = resolve_async_result(
        calculation_id=calculation_id,
        expected_analytics_type="ReturnsSeries",
        response_model=_AsyncResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="not found",
        failed_detail="failed",
    )

    assert response.status_code == 202
    assert json.loads(response.body) == {
        "calculation_id": str(calculation_id),
        "status": "accepted",
    }


def test_resolve_async_result_validates_stored_async_result_payload(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(
        async_result_service,
        "async_result_store",
        _ResultStore(
            _async_result_record(
                calculation_id,
                result_status=AsyncResultStatus.COMPLETE,
                response_payload={"calculation_id": str(calculation_id), "status": "complete"},
            )
        ),
    )

    response = resolve_async_result(
        calculation_id=calculation_id,
        expected_analytics_type="ReturnsSeries",
        response_model=_AsyncResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="not found",
        failed_detail="failed",
    )

    assert response == _AsyncResponse(calculation_id=calculation_id, status="complete")


def test_resolve_async_result_hides_wrong_type_stored_payload_from_endpoint(monkeypatch, caplog):
    calculation_id = uuid4()
    monkeypatch.setattr(
        async_result_service,
        "async_result_store",
        _ResultStore(
            _async_result_record(
                calculation_id,
                analytics_type="BENCHMARK",
                result_status=AsyncResultStatus.COMPLETE,
                response_payload={"secret_payload": "not logged"},
            )
        ),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.async_result_service"):
        with pytest.raises(HTTPException) as exc_info:
            resolve_async_result(
                calculation_id=calculation_id,
                expected_analytics_type="ReturnsSeries",
                response_model=_AsyncResponse,
                accepted_response_factory=_accepted_response,
                not_found_detail="not found",
                failed_detail="failed",
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"
    assert "Async result analytics type did not match endpoint." in caplog.text
    assert caplog.records[0].calculation_id == str(calculation_id)
    assert caplog.records[0].source == "async_result_store"
    assert caplog.records[0].expected_analytics_type == "ReturnsSeries"
    assert caplog.records[0].actual_analytics_type == "BENCHMARK"
    assert caplog.records[0].reason == ASYNC_RESULT_ANALYTICS_TYPE_MISMATCH_REASON
    assert "secret_payload" not in caplog.text


def test_resolve_async_result_maps_schema_invalid_stored_payload_to_conflict(monkeypatch, caplog):
    calculation_id = uuid4()
    monkeypatch.setattr(
        async_result_service,
        "async_result_store",
        _ResultStore(
            _async_result_record(
                calculation_id,
                result_status=AsyncResultStatus.COMPLETE,
                response_payload={"unexpected": "shape"},
            )
        ),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.async_result_service"):
        with pytest.raises(HTTPException) as exc_info:
            resolve_async_result(
                calculation_id=calculation_id,
                expected_analytics_type="ReturnsSeries",
                response_model=_AsyncResponse,
                accepted_response_factory=_accepted_response,
                not_found_detail="not found",
                failed_detail="failed",
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL
    assert "Async result response payload failed schema validation." in caplog.text
    assert caplog.records[0].calculation_id == str(calculation_id)
    assert caplog.records[0].source == "async_result_store"
    assert caplog.records[0].response_model == "_AsyncResponse"
    assert caplog.records[0].reason == ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON
    assert caplog.records[0].validation_error_count >= 1
    assert "unexpected" not in caplog.text


def test_resolve_async_result_raises_conflict_for_failed_stored_async_result(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(
        async_result_service,
        "async_result_store",
        _ResultStore(
            _async_result_record(
                calculation_id,
                result_status=AsyncResultStatus.FAILED,
                error_message="worker failed",
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            accepted_response_factory=_accepted_response,
            not_found_detail="not found",
            failed_detail="failed",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "worker failed"


def test_resolve_async_result_validates_completed_compute_job_payload(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(async_result_service, "async_result_store", _ResultStore())
    monkeypatch.setattr(
        async_result_service,
        "compute_job_store",
        _JobStore(
            _job_record(
                calculation_id,
                job_status=ComputeJobStatus.COMPLETE,
                response_payload={"calculation_id": str(calculation_id), "status": "complete"},
            )
        ),
    )

    response = resolve_async_result(
        calculation_id=calculation_id,
        expected_analytics_type="ReturnsSeries",
        response_model=_AsyncResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="not found",
        failed_detail="failed",
    )

    assert response == _AsyncResponse(calculation_id=calculation_id, status="complete")


def test_resolve_async_result_hides_wrong_type_compute_job_from_endpoint(monkeypatch, caplog):
    calculation_id = uuid4()
    monkeypatch.setattr(async_result_service, "async_result_store", _ResultStore())
    monkeypatch.setattr(
        async_result_service,
        "compute_job_store",
        _JobStore(
            _job_record(
                calculation_id,
                analytics_type="BENCHMARK",
                job_status=ComputeJobStatus.COMPLETE,
                response_payload={"secret_payload": "not logged"},
            )
        ),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.async_result_service"):
        with pytest.raises(HTTPException) as exc_info:
            resolve_async_result(
                calculation_id=calculation_id,
                expected_analytics_type="ReturnsSeries",
                response_model=_AsyncResponse,
                accepted_response_factory=_accepted_response,
                not_found_detail="not found",
                failed_detail="failed",
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"
    assert caplog.records[0].source == "compute_job_store"
    assert caplog.records[0].expected_analytics_type == "ReturnsSeries"
    assert caplog.records[0].actual_analytics_type == "BENCHMARK"
    assert caplog.records[0].reason == ASYNC_RESULT_ANALYTICS_TYPE_MISMATCH_REASON
    assert "secret_payload" not in caplog.text


def test_resolve_async_result_maps_schema_invalid_compute_job_payload_to_conflict(monkeypatch, caplog):
    calculation_id = uuid4()
    monkeypatch.setattr(async_result_service, "async_result_store", _ResultStore())
    monkeypatch.setattr(
        async_result_service,
        "compute_job_store",
        _JobStore(
            _job_record(
                calculation_id,
                job_status=ComputeJobStatus.COMPLETE,
                response_payload={"unexpected": "shape"},
            )
        ),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.async_result_service"):
        with pytest.raises(HTTPException) as exc_info:
            resolve_async_result(
                calculation_id=calculation_id,
                expected_analytics_type="ReturnsSeries",
                response_model=_AsyncResponse,
                accepted_response_factory=_accepted_response,
                not_found_detail="not found",
                failed_detail="failed",
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL
    assert caplog.records[0].source == "compute_job_store"
    assert caplog.records[0].reason == ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON
    assert "unexpected" not in caplog.text
