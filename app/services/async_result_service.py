from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.core.application_responses import ApplicationHttpResponse, accepted_application_response
from app.services.async_result_store import AsyncResultRecord, AsyncResultStatus, async_result_store
from app.services.calculation_result_access import authorize_calculation_result_access
from app.services.compute_job_store import ComputeJobRecord, ComputeJobStatus, compute_job_store
from app.services.execution_registry import execution_registry
from core.errors import APIConflictError, APINotFoundError

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)
AcceptedModelT = TypeVar("AcceptedModelT", bound=BaseModel)
ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL = "Async result payload failed response contract validation."
ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON = "async_result_response_schema_invalid"
ASYNC_RESULT_ANALYTICS_TYPE_MISMATCH_REASON = "async_result_analytics_type_mismatch"
logger = logging.getLogger(__name__)

ACTIVE_ASYNC_JOB_STATUSES = frozenset(
    {
        ComputeJobStatus.PENDING,
        ComputeJobStatus.LEASED,
        ComputeJobStatus.RUNNING,
    }
)


def _is_active_async_job_status(job_status: ComputeJobStatus) -> bool:
    return job_status in ACTIVE_ASYNC_JOB_STATUSES


def _resolve_stored_async_result(
    *,
    async_result: AsyncResultRecord,
    expected_analytics_type: str,
    response_model: type[ResponseModelT],
    not_found_detail: str,
    failed_detail: str,
) -> ResponseModelT:
    _ensure_expected_analytics_type(
        calculation_id=async_result.calculation_id,
        actual_analytics_type=async_result.analytics_type,
        expected_analytics_type=expected_analytics_type,
        not_found_detail=not_found_detail,
        source="async_result_store",
    )
    if async_result.result_status == AsyncResultStatus.FAILED:
        raise APIConflictError(async_result.error_message or failed_detail)
    return _validate_response_payload(
        calculation_id=async_result.calculation_id,
        response_model=response_model,
        response_payload=async_result.response_payload,
        source="async_result_store",
    )


def _resolve_compute_job_result(
    *,
    calculation_id: UUID,
    job: ComputeJobRecord | None,
    expected_analytics_type: str,
    response_model: type[ResponseModelT],
    accepted_response_factory: Callable[[UUID], AcceptedModelT],
    not_found_detail: str,
    failed_detail: str,
) -> ResponseModelT | ApplicationHttpResponse:
    job = _require_compute_job(job, not_found_detail=not_found_detail)
    _ensure_expected_analytics_type(
        calculation_id=calculation_id,
        actual_analytics_type=job.analytics_type,
        expected_analytics_type=expected_analytics_type,
        not_found_detail=not_found_detail,
        source="compute_job_store",
    )
    if _is_active_async_job_status(job.job_status):
        return accepted_application_response(accepted_response_factory(calculation_id))
    if job.job_status == ComputeJobStatus.FAILED:
        raise APIConflictError(job.error_message or failed_detail)
    return _validate_response_payload(
        calculation_id=calculation_id,
        response_model=response_model,
        response_payload=job.response_payload,
        source="compute_job_store",
    )


def _ensure_expected_analytics_type(
    *,
    calculation_id: UUID,
    actual_analytics_type: str,
    expected_analytics_type: str,
    not_found_detail: str,
    source: str,
) -> None:
    if actual_analytics_type == expected_analytics_type:
        return
    logger.warning(
        "Async result analytics type did not match endpoint.",
        extra={
            "calculation_id": str(calculation_id),
            "source": source,
            "expected_analytics_type": expected_analytics_type,
            "actual_analytics_type": actual_analytics_type,
            "reason": ASYNC_RESULT_ANALYTICS_TYPE_MISMATCH_REASON,
        },
    )
    raise APINotFoundError(not_found_detail) from None


def _validate_response_payload(
    *,
    calculation_id: UUID,
    response_model: type[ResponseModelT],
    response_payload: dict[str, Any] | None,
    source: str,
) -> ResponseModelT:
    try:
        return response_model.model_validate(response_payload)
    except ValidationError as exc:
        logger.warning(
            "Async result response payload failed schema validation.",
            extra={
                "calculation_id": str(calculation_id),
                "source": source,
                "response_model": response_model.__name__,
                "reason": ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON,
                "validation_error_count": exc.error_count(),
            },
        )
        raise APIConflictError(ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL) from None


def _require_compute_job(
    job: ComputeJobRecord | None,
    *,
    not_found_detail: str,
) -> ComputeJobRecord:
    if job is None:
        raise APINotFoundError(not_found_detail)
    return job


def resolve_async_result(
    *,
    calculation_id: UUID,
    expected_analytics_type: str,
    response_model: type[ResponseModelT],
    accepted_response_factory: Callable[[UUID], AcceptedModelT],
    not_found_detail: str,
    failed_detail: str,
    request_headers: Mapping[str, Any] | None = None,
) -> ResponseModelT | ApplicationHttpResponse:
    access_denial = _authorize_async_result_access(
        calculation_id=calculation_id,
        request_headers=request_headers,
        not_found_detail=not_found_detail,
    )
    if access_denial is not None:
        return access_denial

    async_result = async_result_store.get_result(calculation_id)
    if async_result is not None:
        return _resolve_stored_async_result(
            async_result=async_result,
            expected_analytics_type=expected_analytics_type,
            response_model=response_model,
            not_found_detail=not_found_detail,
            failed_detail=failed_detail,
        )

    return _resolve_compute_job_result(
        calculation_id=calculation_id,
        job=compute_job_store.get_job(calculation_id),
        expected_analytics_type=expected_analytics_type,
        response_model=response_model,
        accepted_response_factory=accepted_response_factory,
        not_found_detail=not_found_detail,
        failed_detail=failed_detail,
    )


def _authorize_async_result_access(
    *,
    calculation_id: UUID,
    request_headers: Mapping[str, Any] | None,
    not_found_detail: str,
) -> ApplicationHttpResponse | None:
    if request_headers is None:
        return None
    execution = execution_registry.get_execution(calculation_id)
    if execution is None:
        raise APINotFoundError(not_found_detail)
    return authorize_calculation_result_access(execution=execution, headers=request_headers)
