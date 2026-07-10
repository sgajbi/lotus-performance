from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.core.async_polling import ASYNC_RETRY_AFTER_HEADER, DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS
from app.models.platform_surfaces import ErrorDetailResponse

_EXAMPLE_CALCULATION_ID = "209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3"


def async_submission_responses(
    *,
    accepted_model: type[BaseModel],
    analytics_name: str,
    result_path_template: str,
) -> dict[int, dict[str, Any]]:
    return {
        202: {
            "model": accepted_model,
            "description": (
                f"Accepted for asynchronous {analytics_name} execution. Poll poll_path for execution "
                f"status or result_path for the completed {analytics_name} response. Wait at least "
                "recommended_poll_after_seconds between polls; the same value is also returned in "
                f"the {ASYNC_RETRY_AFTER_HEADER} header."
            ),
            "headers": _accepted_polling_headers(),
            "content": {"application/json": {"example": _accepted_example(accepted_model, result_path_template)}},
        }
    }


def async_result_responses(
    *,
    accepted_model: type[BaseModel],
    analytics_name: str,
    result_path_template: str,
    not_found_detail: str,
    failed_detail: str,
) -> dict[int, dict[str, Any]]:
    id_field_name = _accepted_id_field_name(accepted_model)
    return {
        202: {
            "model": accepted_model,
            "description": (
                f"The async {analytics_name} calculation is still pending or running. Wait at least "
                "recommended_poll_after_seconds between polls; the same value is also returned in "
                f"the {ASYNC_RETRY_AFTER_HEADER} header."
            ),
            "headers": _accepted_polling_headers(),
            "content": {"application/json": {"example": _accepted_example(accepted_model, result_path_template)}},
        },
        404: {
            "model": ErrorDetailResponse,
            "description": f"No async {analytics_name} result exists for the supplied {id_field_name}.",
            "content": {
                "application/json": {
                    "example": _error_detail_example(
                        detail=not_found_detail,
                        error_code="RESOURCE_NOT_FOUND",
                        message=not_found_detail,
                        retryable=False,
                    )
                }
            },
        },
        409: {
            "model": ErrorDetailResponse,
            "description": f"The async {analytics_name} execution failed and no completed result is available.",
            "content": {
                "application/json": {
                    "example": _error_detail_example(
                        detail=failed_detail,
                        error_code="ASYNC_EXECUTION_FAILED",
                        message=failed_detail,
                        retryable=False,
                    )
                }
            },
        },
    }


def _accepted_example(
    accepted_model: type[BaseModel],
    result_path_template: str,
) -> dict[str, str | int]:
    id_field_name = _accepted_id_field_name(accepted_model)
    example: dict[str, str | int] = {
        id_field_name: _EXAMPLE_CALCULATION_ID,
        "poll_path": f"/performance/executions/{_EXAMPLE_CALCULATION_ID}",
        "result_path": result_path_template.format(
            calculation_id=_EXAMPLE_CALCULATION_ID,
            inspection_id=_EXAMPLE_CALCULATION_ID,
        ),
        "recommended_poll_after_seconds": DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
    }
    for field_name in ("source_service", "contract_version", "execution_mode", "status"):
        field = accepted_model.model_fields.get(field_name)
        if field is not None and field.default is not None:
            example[field_name] = str(field.default)
    return example


def _accepted_id_field_name(accepted_model: type[BaseModel]) -> str:
    return "inspection_id" if "inspection_id" in accepted_model.model_fields else "calculation_id"


def _accepted_polling_headers() -> dict[str, dict[str, str | dict[str, str | int]]]:
    return {
        ASYNC_RETRY_AFTER_HEADER: {
            "description": "Minimum seconds clients should wait before polling the async status or result route again.",
            "schema": {
                "type": "integer",
                "minimum": DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
                "example": DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
            },
        }
    }


def _error_detail_example(
    *,
    detail: str,
    error_code: str,
    message: str,
    retryable: bool,
) -> dict[str, str | bool | None]:
    return {
        "detail": detail,
        "error_code": error_code,
        "message": message,
        "correlation_id": "corr_55956bbc6cb3",
        "request_id": "req_0d19d1d768c1",
        "source": "lotus-performance",
        "retryable": retryable,
        "retry_after_seconds": None,
        "remediation_hint": "Use the async status endpoint to inspect execution posture before retrying.",
    }
