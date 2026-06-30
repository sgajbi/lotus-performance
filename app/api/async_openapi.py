from __future__ import annotations

from typing import Any

from pydantic import BaseModel

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
                f"status or result_path for the completed {analytics_name} response."
            ),
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
    return {
        202: {
            "model": accepted_model,
            "description": f"The async {analytics_name} calculation is still pending or running.",
            "content": {"application/json": {"example": _accepted_example(accepted_model, result_path_template)}},
        },
        404: {
            "model": ErrorDetailResponse,
            "description": f"No async {analytics_name} result exists for the supplied calculation_id.",
            "content": {"application/json": {"example": {"detail": not_found_detail}}},
        },
        409: {
            "model": ErrorDetailResponse,
            "description": f"The async {analytics_name} execution failed and no completed result is available.",
            "content": {"application/json": {"example": {"detail": failed_detail}}},
        },
    }


def _accepted_example(
    accepted_model: type[BaseModel],
    result_path_template: str,
) -> dict[str, str]:
    example = {
        "calculation_id": _EXAMPLE_CALCULATION_ID,
        "poll_path": f"/performance/executions/{_EXAMPLE_CALCULATION_ID}",
        "result_path": result_path_template.format(calculation_id=_EXAMPLE_CALCULATION_ID),
    }
    for field_name in ("source_service", "contract_version", "execution_mode", "status"):
        field = accepted_model.model_fields.get(field_name)
        if field is not None and field.default is not None:
            example[field_name] = str(field.default)
    return example
