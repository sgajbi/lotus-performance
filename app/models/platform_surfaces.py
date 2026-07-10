from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BuildMetadataResponse(BaseModel):
    service_name: str = Field(
        description="Configured service display name.",
        json_schema_extra={"example": "Portfolio Performance Analytics API"},
    )
    service_version: str = Field(
        description="Application version carried by OpenAPI, runtime metadata, and OCI image labels.",
        json_schema_extra={"example": "0.1.0"},
    )
    git_commit_sha: str = Field(
        description="Git commit SHA used to build the running image or local process.",
        json_schema_extra={"example": "0123456789abcdef0123456789abcdef01234567"},
    )
    git_branch: str = Field(
        description="Git branch or ref name used by the build pipeline.",
        json_schema_extra={"example": "main"},
    )
    build_timestamp: str = Field(
        description="UTC build timestamp supplied by CI or the local build command.",
        json_schema_extra={"example": "2026-07-10T07:45:00Z"},
    )
    repository_url: str = Field(
        description="Source repository URL for correlating runtime identity to source and attestations.",
        json_schema_extra={"example": "https://github.com/sgajbi/lotus-performance"},
    )
    image_digest: str = Field(
        description=(
            "Registry image digest supplied by CI/promotion when available. Local builds use "
            "`unavailable-before-push` because Dockerfile labels cannot know the final pushed digest."
        ),
        json_schema_extra={"example": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
    )
    ci_pipeline_run_id: str = Field(
        description="CI pipeline or GitHub Actions run identifier that produced the image.",
        json_schema_extra={"example": "1234567890"},
    )


class RootResponse(BaseModel):
    message: str = Field(
        description="Human-readable service entry message that points operators and developers to the API docs.",
        json_schema_extra={
            "example": "Welcome to the Portfolio Performance Analytics API. Access /docs for API documentation."
        },
    )
    build: "BuildMetadataResponse" = Field(
        description=(
            "Support-safe runtime build identity for correlating this service instance to image, SBOM, "
            "vulnerability, and provenance evidence."
        ),
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
