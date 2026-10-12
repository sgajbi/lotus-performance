"""Strict source-time precision evidence; never an approval or replacement result."""

from datetime import date
from math import gcd
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.composite_authority import Digest
from app.models.composites import CompositeMemberReturnFact, CompositeTWRRequest, CompositeTWRWindowEvidence

PROFILE = "AW_TWR_DECIMAL_REPLAY.v1"
SIGNALS = frozenset(
    {
        "Clamped",
        "DivisionByZero",
        "FloatOperation",
        "Inexact",
        "InvalidOperation",
        "Overflow",
        "Rounded",
        "Subnormal",
        "Underflow",
    }
)
DecimalText = Annotated[str, Field(strict=True, min_length=1, max_length=160)]
IntegerText = Annotated[str, Field(strict=True, pattern=r"^-?[0-9]{1,4096}$")]


class CaptureWire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecimalContextCapture(CaptureWire):
    prec: int = Field(strict=True, ge=1, le=4096)
    rounding: str
    Emin: int = Field(strict=True)
    Emax: int = Field(strict=True)
    capitals: int = Field(strict=True, ge=0, le=1)
    clamp: int = Field(strict=True, ge=0, le=1)
    traps: dict[str, bool]
    entry_flags: dict[str, bool]

    @field_validator("traps", "entry_flags", mode="before")
    @classmethod
    def complete_signals(cls, mapping):
        if (
            not isinstance(mapping, dict)
            or set(mapping) != SIGNALS
            or any(type(value) is not bool for value in mapping.values())
        ):
            raise ValueError("Every Decimal signal must be explicitly boolean")
        return mapping


class CaptureSource(CaptureWire):
    owner: Literal["lotus-performance"] = "lotus-performance"
    tenant_id: str
    candidate_id: UUID
    calculation_id: UUID
    original_response_digest: Digest
    request_binding_digest: Digest


class ArithmeticRuntime(CaptureWire):
    python_implementation: str
    python_version: str
    decimal_version: str
    libmpdec_version: str
    decimal_contextvar: bool = Field(strict=True)


class ArithmeticAlgorithm(CaptureWire):
    engine_version: str
    release_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    kernel_source_digest: Digest
    projection_policy: Literal["composite-quantize-inherited.v1"]
    runtime: ArithmeticRuntime


class CapturedWindow(CompositeTWRWindowEvidence):
    model_config = ConfigDict(extra="forbid")


class ArithmeticScope(CaptureWire):
    composite_id: str
    period_start: date
    period_end: date
    return_view: str
    reporting_currency: str
    materialization_vector: list[UUID] = Field(min_length=1, max_length=120)
    windows: list[CapturedWindow] = Field(min_length=1, max_length=120)


class RetainedWindowRef(CaptureWire):
    kind: Literal["RETAINED_MATERIALIZATION"] = "RETAINED_MATERIALIZATION"
    owner: Literal["lotus-performance"] = "lotus-performance"
    tenant_id: str
    materialization_id: UUID
    retained_receipt_fingerprint: str
    source_cut_id: str


class OrderedArithmeticFact(CaptureWire):
    ordinal: int = Field(strict=True, ge=0)
    window_ordinal: int = Field(strict=True, ge=0, lt=120)
    fact: CompositeMemberReturnFact


class ArithmeticCheckpoint(CaptureWire):
    period_start: date
    period_end: date
    beginning_assets: DecimalText
    ending_assets: DecimalText
    weighted_return: DecimalText
    next_cumulative_growth: DecimalText
    cumulative_return_before_quantize: DecimalText


class ExactQuantity(CaptureWire):
    numerator: IntegerText
    denominator: Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,4095}$")]

    @model_validator(mode="after")
    def canonical_fraction(self):
        numerator, denominator = int(self.numerator), int(self.denominator)
        if str(numerator) != self.numerator or gcd(numerator, denominator) != 1:
            raise ValueError("Exact quantities must be canonical reduced fractions")
        return self


class ProjectionQualification(CaptureWire):
    status: Literal["MATCHED"]
    adapter: Literal["AW_TWR_DECIMAL_REPLAY.v1"]
    input_digest: Digest
    mathematical_return: ExactQuantity
    internal_return: ExactQuantity
    reported_return: ExactQuantity
    internal_arithmetic_error: ExactQuantity
    output_quantization_error: ExactQuantity


class CaptureProvenance(CaptureWire):
    captured_by: str
    captured_at_utc: str
    credential_id: str
    principal_kind: Literal["user", "service", "delegated"]
    delegated_actor: str | None


class ResponseBinding(CaptureWire):
    wire_codec: Literal["candidate-wire.v1"] = "candidate-wire.v1"
    original_response_digest: Digest


class CompositeArithmeticCapture(CaptureWire):
    schema_version: Literal["CompositeArithmeticCapture.v1"]
    adapter: Literal["AW_TWR_DECIMAL_REPLAY.v1"]
    source: CaptureSource
    algorithm: ArithmeticAlgorithm
    scope: ArithmeticScope
    calculation_request: CompositeTWRRequest
    source_refs: list[RetainedWindowRef] = Field(min_length=1, max_length=120)
    ordered_facts: list[OrderedArithmeticFact] = Field(min_length=1, max_length=120000)
    input_digest: Digest
    context_route: Literal["AMBIENT", "SCHEDULED_COMPONENT_SCOPED"]
    effective_context: DecimalContextCapture
    exit_flags: dict[str, bool]
    checkpoints: list[ArithmeticCheckpoint] = Field(min_length=1, max_length=120)
    response_binding: ResponseBinding
    capture_binding: CaptureProvenance
    projection_replay: ProjectionQualification
    evidence_binding_digest: Digest

    @field_validator("exit_flags", mode="before")
    @classmethod
    def complete_exit_flags(cls, mapping):
        if (
            not isinstance(mapping, dict)
            or set(mapping) != SIGNALS
            or any(type(value) is not bool for value in mapping.values())
        ):
            raise ValueError("Every exit signal must be explicitly boolean")
        return mapping


class ArithmeticCaptureEnvelope(CaptureWire):
    digest: Digest
    payload: CompositeArithmeticCapture
