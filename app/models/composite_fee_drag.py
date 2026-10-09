"""Pinned same-population gross/model return differences, never actual cash fees."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.composite_authority import EvidenceBinding
from app.models.composites import CompositeReturnView, CompositeTWRRequest, CompositeTWRSelectionManifest


class CompositeFeeDragRequest(CompositeTWRRequest):
    metric_id: Literal["MODEL_FEE_DRAG"]
    return_view: Literal[CompositeReturnView.NET_MODEL_FEE] = CompositeReturnView.NET_MODEL_FEE
    materialization_ids: list[UUID] = Field(
        min_length=1,
        max_length=120,
        description="Exact complete model-fee windows; gross comes from their original retained receipts.",
    )
    method: Literal["ADDITIVE_GROSS_MINUS_MODEL:v1"] = "ADDITIVE_GROSS_MINUS_MODEL:v1"


class CompositeFeeDragPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    period_start: date
    period_end: date
    gross_return: Decimal
    model_net_return: Decimal
    fee_drag: Decimal = Field(description="Gross minus model-net return; a decimal return difference, not money.")
    member_count: int
    excluded_member_count: int


class CompositeFeeDragMemberSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str
    period_start: date
    period_end: date
    gross_receipt_digest: str
    model_receipt_digest: str


class CompositeFeeDragResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    metric_id: Literal["MODEL_FEE_DRAG"] = "MODEL_FEE_DRAG"
    calculation_id: UUID
    composite_id: str
    period_start: date
    period_end: date
    reporting_currency: str
    method: Literal["ADDITIVE_GROSS_MINUS_MODEL:v1"] = "ADDITIVE_GROSS_MINUS_MODEL:v1"
    units: Literal["DECIMAL_RETURN_DIFFERENCE"] = "DECIMAL_RETURN_DIFFERENCE"
    status: Literal["CALCULATED_ANALYSIS"] = "CALCULATED_ANALYSIS"
    qualification: Literal["RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"] = (
        "RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"
    )
    gross_baseline: Literal["ORIGINAL_GROSS_RECEIPTS_SAME_MODEL_POPULATION"] = (
        "ORIGINAL_GROSS_RECEIPTS_SAME_MODEL_POPULATION"
    )
    model_fee_binding: EvidenceBinding
    cumulative_gross_return: Decimal
    cumulative_model_net_return: Decimal
    cumulative_fee_drag: Decimal = Field(
        description="Difference of geometrically linked gross/model returns; not the sum of period differences."
    )
    periods: list[CompositeFeeDragPeriod]
    member_sources: list[CompositeFeeDragMemberSource]
    selection_manifest: CompositeTWRSelectionManifest
