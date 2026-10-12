"""Bounded calculated candidate capture; approval and freeze are separate work."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from app.models.composite_arithmetic_capture import ArithmeticCaptureEnvelope
from app.models.composites import CompositeTWRRequest, CompositeTWRResponse


class CompositeResultCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: UUID = Field(description="Retry identity for this explicit calculated result capture.")
    calculation: CompositeTWRRequest
    precision_capture_profile: Literal["AW_TWR_DECIMAL_REPLAY.v1"] | None = None

    @model_validator(mode="after")
    def require_explicit_vector(self):
        if self.calculation.materialization_ids is None:
            raise ValueError("Candidate capture requires an explicit complete retained materialization vector")
        return self


class CompositeResultCandidateResponse(BaseModel):
    candidate_id: UUID
    qualification: Literal["CALCULATED_RESULT_CANDIDATE"]
    tenant_id: str
    original_response_digest: str
    build_commit: str
    engine_version: str
    captured_by: str
    principal_kind: Literal["user", "service", "delegated"]
    delegated_actor: str | None
    credential_id: str
    captured_at_utc: datetime
    response: CompositeTWRResponse
    arithmetic_capture: ArithmeticCaptureEnvelope | None = None

    @model_serializer(mode="wrap")
    def retain_legacy_wire(self, handler):
        payload = handler(self)
        if self.arithmetic_capture is None:
            payload.pop("arithmetic_capture", None)
        return payload


class CompositeResultCandidateErrorResponse(BaseModel):
    detail: str | dict
    error_code: str
    message: str
    source: Literal["lotus-performance"]
    retryable: bool
    correlation_id: str | None = None
    request_id: str | None = None
    retry_after_seconds: int | None = None
    remediation_hint: str | None = None
