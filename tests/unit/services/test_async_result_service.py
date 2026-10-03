import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.services import async_result_service
from app.services.async_result_service import (
    ASYNC_RESULT_ANALYTICS_TYPE_MISMATCH_REASON,
    ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL,
    ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON,
    _is_active_async_job_status,
    _require_compute_job,
    _resolve_compute_job_result,
    _resolve_retained_execution_result,
    resolve_async_result,
)
from app.services.async_result_store import AsyncResultRecord, AsyncResultStatus
from app.services.compute_job_store import ComputeJobRecord, ComputeJobStatus
from app.services.durable_failure_classification import (
    DURABLE_FAILURE_CONTRACT_VERSION,
    GENERIC_ASYNC_FAILURE_CODE,
    GENERIC_ASYNC_FAILURE_MESSAGE,
    DurableFailureClassification,
    classify_durable_failure,
    load_durable_failure,
)
from app.services.execution_registry import ExecutionRecord, ExecutionStatus
from core.errors import APIError, APIUnprocessableEntityError


def test_durable_failure_classification_preserves_safe_governed_domain_error():
    failure = classify_durable_failure(
        APIUnprocessableEntityError(
            "History window exceeds the governed maximum.",
            error_code="PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE",
        )
    )

    assert failure.contract_version == DURABLE_FAILURE_CONTRACT_VERSION
    assert failure.status_code == 422
    assert failure.error_code == "PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE"
    assert failure.message == "History window exceeds the governed maximum."
    assert failure.retryable is False
    assert load_durable_failure(failure.to_json(), identity="calc-1") == failure


def test_durable_failure_classification_sanitizes_unknown_exception():
    failure = classify_durable_failure(RuntimeError("secret=bank-account-123"))

    assert failure.status_code == 409
    assert failure.error_code == GENERIC_ASYNC_FAILURE_CODE
    assert failure.message == GENERIC_ASYNC_FAILURE_MESSAGE
    assert failure.retryable is False
    assert "secret" not in failure.to_json()


def test_durable_failure_classification_rejects_future_contract(caplog):
    assert load_durable_failure(None, identity="calc-legacy") is None
    with caplog.at_level(logging.WARNING):
        failure = load_durable_failure(
            '{"contract_version":"v2","status_code":422,"error_code":"X","message":"safe","retryable":false}',
            identity="calc-legacy",
        )

    assert failure is None
    assert "legacy generic handling" in caplog.text


def test_durable_failure_classification_sanitizes_server_error_and_preserves_metadata():
    failure = classify_durable_failure(
        APIError(
            status_code=503,
            detail="secret upstream credential",
            error_code="SOURCE_UNAVAILABLE",
            retryable=True,
            remediation_hint=" Retry after source recovery. ",
        )
    )

    restored = failure.to_api_error()
    assert failure.message == GENERIC_ASYNC_FAILURE_MESSAGE
    assert failure.retryable is True
    assert failure.remediation_hint == "Retry after source recovery."
    assert restored.status_code == 503
    assert restored.error_code == "SOURCE_UNAVAILABLE"
    assert restored.remediation_hint == "Retry after source recovery."
    assert "secret upstream credential" not in failure.to_json()


def test_durable_failure_classification_derives_uncoded_service_unavailable_contract():
    failure = classify_durable_failure(APIError(status_code=503, detail="upstream unavailable"))

    assert failure.status_code == 503
    assert failure.error_code == "SOURCE_UNAVAILABLE"
    assert failure.retryable is True
    assert failure.message == GENERIC_ASYNC_FAILURE_MESSAGE


def test_durable_failure_classification_bounds_controlled_fields_and_extracts_dict_message():
    failure = classify_durable_failure(
        APIError(
            status_code=422,
            detail={"message": " Governed refusal. "},
            error_code="X" * 200,
            remediation_hint="R" * 600,
        )
    )

    assert failure.message == "Governed refusal."
    assert len(failure.error_code) == 128
    assert len(failure.remediation_hint or "") == 512


@pytest.mark.parametrize(
    "raw_value",
    [
        "not-json",
        "[]",
        '{"contract_version":"v1"}',
        '{"contract_version":"v1","status_code":399,"error_code":"X","message":"safe","retryable":false}',
        '{"contract_version":"v1","status_code":418,"error_code":"X","message":"safe","retryable":false}',
        '{"contract_version":"v1","status_code":422,"error_code":"X","message":"safe","retryable":"false"}',
        '{"contract_version":"v1","status_code":422.9,"error_code":"X","message":"safe","retryable":false}',
        '{"contract_version":"v1","status_code":true,"error_code":"X","message":"safe","retryable":false}',
        '{"contract_version":"v1","status_code":422,"error_code":{"code":"X"},"message":"safe","retryable":false}',
        '{"contract_version":"v1","status_code":422,"error_code":"X","message":{"secret":"value"},"retryable":false}',
        '{"contract_version":"v1","status_code":422,"error_code":"X","message":"safe","retryable":false,"remediation_hint":42}',
        '{"contract_version":"v1","status_code":422,"error_code":"","message":"safe","retryable":false}',
        '{"contract_version":"v1","status_code":422,"error_code":"X","message":"","retryable":false}',
    ],
)
def test_durable_failure_classification_rejects_malformed_or_untrusted_stored_values(raw_value):
    assert load_durable_failure(raw_value, identity="calc-invalid") is None


def test_durable_failure_classification_uses_safe_fallback_for_non_message_detail():
    failure = classify_durable_failure(
        APIError(status_code=422, detail={"unexpected": "value"}, error_code="DOMAIN_REFUSAL")
    )

    assert failure.message == "The asynchronous calculation was refused."


def test_durable_failure_classification_constrains_unknown_http_status_to_documented_generic_contract():
    failure = classify_durable_failure(APIError(status_code=418, detail="unexpected status"))

    assert failure.status_code == 409
    assert failure.error_code == GENERIC_ASYNC_FAILURE_CODE


class _AsyncResponse(BaseModel):
    calculation_id: UUID
    status: str


class _ResultStore:
    def __init__(self, result: AsyncResultRecord | None = None) -> None:
        self._result = result
        self.requested_tenants: list[str] = []

    def get_result(self, calculation_id: UUID) -> AsyncResultRecord | None:
        del calculation_id
        return self._result

    def get_result_for_tenant(self, calculation_id: UUID, *, tenant_id: str) -> AsyncResultRecord | None:
        del calculation_id
        self.requested_tenants.append(tenant_id)
        return self._result


class _JobStore:
    def __init__(self, job: ComputeJobRecord | None) -> None:
        self._job = job
        self.requested_tenants: list[str] = []

    def get_job(self, calculation_id: UUID) -> ComputeJobRecord | None:
        del calculation_id
        return self._job

    def get_job_for_tenant(self, calculation_id: UUID, *, tenant_id: str) -> ComputeJobRecord | None:
        del calculation_id
        self.requested_tenants.append(tenant_id)
        return self._job


class _ExecutionStore:
    def __init__(self, execution: ExecutionRecord | None = None) -> None:
        self._execution = execution

    def get_execution(self, calculation_id: UUID) -> ExecutionRecord | None:
        del calculation_id
        return self._execution

    def get_execution_for_tenant(self, calculation_id: UUID, *, tenant_id: str) -> ExecutionRecord | None:
        del calculation_id
        if self._execution is None or self._execution.tenant_id != tenant_id:
            return None
        return self._execution


def _job_record(
    calculation_id: UUID,
    *,
    job_status: ComputeJobStatus,
    analytics_type: str = "ReturnsSeries",
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    failure: DurableFailureClassification | None = None,
) -> ComputeJobRecord:
    return ComputeJobRecord(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        tenant_id="tenant-test",
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
        failure=failure,
    )


def _async_result_record(
    calculation_id: UUID,
    *,
    result_status: AsyncResultStatus,
    analytics_type: str = "ReturnsSeries",
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    failure: DurableFailureClassification | None = None,
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
        failure=failure,
    )


def _accepted_response(calculation_id: UUID) -> _AsyncResponse:
    return _AsyncResponse(calculation_id=calculation_id, status="accepted")


def _execution_record(
    calculation_id: UUID,
    *,
    portfolio_id: str | None = "PORT-1",
    tenant_id: str | None = "tenant-private-bank",
    status: ExecutionStatus = ExecutionStatus.COMPLETE,
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    failure: DurableFailureClassification | None = None,
) -> ExecutionRecord:
    return ExecutionRecord(
        calculation_id=calculation_id,
        tenant_id=tenant_id,
        analytics_type="ReturnsSeries",
        portfolio_id=portfolio_id,
        execution_mode="async",
        status=status,
        requested_window={},
        input_fingerprint=None,
        calculation_hash=None,
        error_message=error_message,
        created_at_utc="2026-06-13T00:00:00Z",
        started_at_utc=None,
        completed_at_utc=None,
        stages=[],
        upstream_snapshots=[],
        response_payload=response_payload,
        failure=failure,
    )


def _identity_headers(**extra_headers: str) -> dict[str, str]:
    return {
        "X-Actor-Id": "advisor-1",
        "X-Tenant-Id": "tenant-private-bank",
        "X-Role": "advisor",
        "X-Correlation-Id": "corr-1",
        "X-Service-Identity": "lotus-gateway",
        **extra_headers,
    }


def test_active_async_job_status_policy_covers_in_flight_statuses():
    assert _is_active_async_job_status(ComputeJobStatus.PENDING)
    assert _is_active_async_job_status(ComputeJobStatus.LEASED)
    assert _is_active_async_job_status(ComputeJobStatus.RUNNING)
    assert not _is_active_async_job_status(ComputeJobStatus.COMPLETE)
    assert not _is_active_async_job_status(ComputeJobStatus.FAILED)


def test_resolve_compute_job_result_raises_not_found_for_missing_job():
    with pytest.raises(APIError) as exc_info:
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
    with pytest.raises(APIError) as exc_info:
        _require_compute_job(None, not_found_detail="not found")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"


def test_resolve_compute_job_result_raises_conflict_for_failed_job():
    calculation_id = uuid4()
    job = _job_record(calculation_id, job_status=ComputeJobStatus.FAILED, error_message="worker failed")

    with pytest.raises(APIError) as exc_info:
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
    assert exc_info.value.detail == GENERIC_ASYNC_FAILURE_MESSAGE
    assert exc_info.value.error_code == "ASYNC_EXECUTION_FAILED"


def test_resolve_compute_job_result_restores_governed_failure_classification():
    calculation_id = uuid4()
    failure = DurableFailureClassification(
        contract_version="v1",
        status_code=422,
        error_code="PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE",
        message="History window exceeds the governed maximum.",
        retryable=False,
    )
    job = _job_record(
        calculation_id,
        job_status=ComputeJobStatus.FAILED,
        error_message=failure.message,
        failure=failure,
    )

    with pytest.raises(APIError) as exc_info:
        _resolve_compute_job_result(
            calculation_id=calculation_id,
            job=job,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            accepted_response_factory=_accepted_response,
            not_found_detail="not found",
            failed_detail="failed",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE"
    assert exc_info.value.retryable is False


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
    assert response.content == {
        "calculation_id": str(calculation_id),
        "status": "accepted",
    }


def test_resolve_async_result_hides_existing_result_when_execution_identity_missing(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    monkeypatch.setattr(async_result_service, "execution_registry", _ExecutionStore(None))
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

    with pytest.raises(APIError) as exc_info:
        resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            accepted_response_factory=_accepted_response,
            not_found_detail="not found",
            failed_detail="failed",
            request_headers=_identity_headers(**{"X-Capabilities": "operations.runtime.read"}),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"


def test_resolve_async_result_denies_cross_portfolio_access(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    monkeypatch.setattr(async_result_service, "execution_registry", _ExecutionStore(_execution_record(calculation_id)))
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
        request_headers=_identity_headers(**{"X-Portfolio-Id": "PORT-2"}),
    )

    assert response.status_code == 403


def test_resolve_async_result_allows_same_portfolio_access(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    monkeypatch.setattr(async_result_service, "execution_registry", _ExecutionStore(_execution_record(calculation_id)))
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
        request_headers=_identity_headers(**{"X-Portfolio-Id": "PORT-1"}),
    )

    assert response == _AsyncResponse(calculation_id=calculation_id, status="complete")


def test_resolve_async_result_falls_back_to_authorized_retained_execution(monkeypatch):
    calculation_id = uuid4()
    execution = _execution_record(
        calculation_id,
        response_payload={"calculation_id": str(calculation_id), "status": "complete"},
    )
    result_store = _ResultStore()
    job_store = _JobStore(None)
    monkeypatch.setattr(async_result_service, "execution_registry", _ExecutionStore(execution))
    monkeypatch.setattr(async_result_service, "async_result_store", result_store)
    monkeypatch.setattr(async_result_service, "compute_job_store", job_store)

    response = resolve_async_result(
        calculation_id=calculation_id,
        expected_analytics_type="ReturnsSeries",
        response_model=_AsyncResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="not found",
        failed_detail="failed",
        request_headers=_identity_headers(**{"X-Portfolio-Id": "PORT-1"}),
    )

    assert response == _AsyncResponse(calculation_id=calculation_id, status="complete")
    assert result_store.requested_tenants == ["tenant-private-bank"]
    assert job_store.requested_tenants == ["tenant-private-bank"]


@pytest.mark.parametrize("retained_state", ["missing", "failed", "response_missing"])
def test_resolve_retained_execution_result_refuses_unavailable_states(retained_state):
    calculation_id = uuid4()
    execution = None
    if retained_state == "failed":
        execution = _execution_record(
            calculation_id,
            status=ExecutionStatus.FAILED,
            error_message="retained execution failed",
        )
    elif retained_state == "response_missing":
        execution = _execution_record(calculation_id)

    with pytest.raises(APIError) as exc_info:
        _resolve_retained_execution_result(
            calculation_id=calculation_id,
            execution=execution,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            not_found_detail="not found",
            failed_detail="failed",
        )

    assert exc_info.value.status_code == (409 if retained_state == "failed" else 404)
    assert exc_info.value.detail == (GENERIC_ASYNC_FAILURE_MESSAGE if retained_state == "failed" else "not found")


def test_resolve_async_result_uses_persisted_empty_authority_for_stateless_poll(monkeypatch):
    calculation_id = uuid4()
    result_store = _ResultStore(
        _async_result_record(
            calculation_id,
            result_status=AsyncResultStatus.COMPLETE,
            response_payload={"calculation_id": str(calculation_id), "status": "complete"},
        )
    )
    monkeypatch.setattr(
        async_result_service, "execution_registry", _ExecutionStore(_execution_record(calculation_id, tenant_id=""))
    )
    monkeypatch.setattr(async_result_service, "async_result_store", result_store)
    tenant_token = async_result_service.tenant_id_var.set("tenant-private-bank")

    try:
        response = resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            accepted_response_factory=_accepted_response,
            not_found_detail="not found",
            failed_detail="failed",
            request_headers=_identity_headers(**{"X-Portfolio-Id": "PORT-1"}),
        )
    finally:
        async_result_service.tenant_id_var.reset(tenant_token)

    assert response == _AsyncResponse(calculation_id=calculation_id, status="complete")
    assert result_store.requested_tenants == [""]


def test_resolve_async_result_upgrades_then_validates_stored_async_result_payload(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(
        async_result_service,
        "async_result_store",
        _ResultStore(
            _async_result_record(
                calculation_id,
                result_status=AsyncResultStatus.COMPLETE,
                response_payload={"calculation_id": str(calculation_id)},
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
        response_payload_upgrader=lambda payload: {**(payload or {}), "status": "complete"},
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
        with pytest.raises(APIError) as exc_info:
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
        with pytest.raises(APIError) as exc_info:
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

    with pytest.raises(APIError) as exc_info:
        resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type="ReturnsSeries",
            response_model=_AsyncResponse,
            accepted_response_factory=_accepted_response,
            not_found_detail="not found",
            failed_detail="failed",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == GENERIC_ASYNC_FAILURE_MESSAGE


def test_resolve_async_result_upgrades_then_validates_completed_compute_job_payload(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(async_result_service, "async_result_store", _ResultStore())
    monkeypatch.setattr(
        async_result_service,
        "compute_job_store",
        _JobStore(
            _job_record(
                calculation_id,
                job_status=ComputeJobStatus.COMPLETE,
                response_payload={"calculation_id": str(calculation_id)},
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
        response_payload_upgrader=lambda payload: {**(payload or {}), "status": "complete"},
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
        with pytest.raises(APIError) as exc_info:
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
        with pytest.raises(APIError) as exc_info:
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
