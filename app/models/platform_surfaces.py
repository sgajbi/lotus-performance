from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RootResponse(BaseModel):
    message: str = Field(
        description="Human-readable service entry message that points operators and developers to the API docs.",
        json_schema_extra={
            "example": "Welcome to the Portfolio Performance Analytics API. Access /docs for API documentation."
        },
    )


class HealthStatusResponse(BaseModel):
    status: str = Field(
        description="Current service health state for the selected endpoint.",
        json_schema_extra={"example": "ok"},
    )
    reason: str | None = Field(
        default=None,
        description="Concrete readiness failure reason when the service is not healthy or ready.",
        json_schema_extra={"example": "durable_metadata_store_unreachable"},
    )
    remediation_hint: str | None = Field(
        default=None,
        description="Operator-facing remediation hint when the service can suggest an immediate recovery action.",
        json_schema_extra={
            "example": "Confirm the durable metadata database URL and verify the database is reachable from lotus-performance."
        },
    )


class ErrorDetailResponse(BaseModel):
    detail: str | dict[str, Any] | list[dict[str, Any]] = Field(
        description=(
            "Backward-compatible legacy error detail. New consumers should use error_code, message, "
            "correlation_id, source, retryable, and validation_errors instead of parsing this field."
        ),
        json_schema_extra={"example": "Execution data not found for the given calculation_id."},
    )
    error_code: str | None = Field(
        default=None,
        description="Stable machine-readable error code from the lotus-performance governed error vocabulary.",
        json_schema_extra={"example": "RESOURCE_NOT_FOUND"},
    )
    message: str | None = Field(
        default=None,
        description="Support-safe human-readable message suitable for downstream clients and operator surfaces.",
        json_schema_extra={"example": "Execution data not found for the given calculation_id."},
    )
    correlation_id: str | None = Field(
        default=None,
        description="Request correlation identifier returned to support troubleshooting across service boundaries.",
        json_schema_extra={"example": "corr_55956bbc6cb3"},
    )
    request_id: str | None = Field(
        default=None,
        description="Request identifier returned to support request-level diagnostics.",
        json_schema_extra={"example": "req_0d19d1d768c1"},
    )
    source: str | None = Field(
        default=None,
        description="Service that authored the public error envelope.",
        json_schema_extra={"example": "lotus-performance"},
    )
    retryable: bool | None = Field(
        default=None,
        description="Whether the caller may retry the request without changing the payload or authorization context.",
        json_schema_extra={"example": False},
    )
    retry_after_seconds: int | None = Field(
        default=None,
        description="Optional retry delay in seconds when the service can recommend one.",
        json_schema_extra={"example": 30},
    )
    remediation_hint: str | None = Field(
        default=None,
        description="Optional operator-facing hint for resolving the failure.",
        json_schema_extra={"example": "Verify the calculation_id and retry after the upstream source is healthy."},
    )
    validation_errors: list[dict[str, Any]] | None = Field(
        default=None,
        description="Structured request-validation details when the request payload or query parameters are invalid.",
        json_schema_extra={
            "example": [
                {
                    "type": "missing",
                    "loc": ["body", "portfolio_id"],
                    "msg": "Field required",
                    "input": {},
                }
            ]
        },
    )
