from __future__ import annotations

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
