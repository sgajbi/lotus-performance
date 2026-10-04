"""Typed annual metric selection and reproducible analysis evidence."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composites import CompositeReturnView, ReportingCurrency
from engine.composite_annual_dispersion import AnnualDispersionMethod


class CompositeAnnualDispersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: Literal["ANNUAL_MEMBER_DISPERSION"] = Field(
        default="ANNUAL_MEMBER_DISPERSION",
        description="Cross-sectional annual member dispersion, distinct from composite volatility.",
    )
    composite_id: str = Field(
        min_length=1,
        max_length=128,
        description="Composite identity of every pinned receipt.",
        examples=["NEUTRAL_BALANCED_USD"],
    )
    year: int = Field(ge=1, le=9999, strict=True, description="Complete calendar year under analysis.", examples=[2025])
    return_view: Literal[CompositeReturnView.GROSS, CompositeReturnView.NET_ACTUAL] = Field(
        description="One actual fee basis across the complete year.", examples=["NET_ACTUAL"]
    )
    reporting_currency: ReportingCurrency = Field(
        description="One evidenced return and asset currency.", examples=["USD"]
    )
    method: AnnualDispersionMethod = Field(
        default="EQUAL_WEIGHT_SAMPLE_STDDEV",
        description="Explicit sample estimator or year-begin asset-weighted population estimator.",
    )
    materialization_ids: list[UUID] = Field(
        min_length=12,
        max_length=12,
        description="Twelve exact immutable monthly receipts. Order is normalized by their retained calendar windows.",
    )

    @model_validator(mode="after")
    def unique_receipts(self) -> "CompositeAnnualDispersionRequest":
        if len(set(self.materialization_ids)) != 12:
            raise ValueError("materialization_ids must be unique")
        return self


class AnnualDispersionMonthEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materialization_id: UUID = Field(description="Retained complete month receipt.")
    period_start: date = Field(description="Inclusive calendar-month start.")
    period_end: date = Field(description="Inclusive calendar-month end.")
    definition_version: str = Field(description="Exact Manage definition version.")
    definition_content_hash: str = Field(description="Admitted producer definition digest.")
    membership_revision: str = Field(description="Exact historical Manage membership revision.")
    membership_content_hash: str = Field(description="Admitted producer membership digest.")
    attestation_version: str = Field(description="Exact universe attestation version.")
    attestation_content_hash: str = Field(description="Admitted producer universe digest.")
    policy_version: str = Field(description="Pinned membership policy.")
    source_cut_id: str = Field(description="Producer source cut, not inferred from year.")
    restatement_sequence: int = Field(description="Exact immutable member-fact chronology.")


class AnnualDispersionMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: str = Field(description="Historical full-year member, including subsequently closed portfolios.")
    annual_return: Decimal = Field(description="Geometrically linked full-year member return; decimal ratio.")
    year_begin_assets: Decimal = Field(description="January beginning assets in the selected currency.")
    source_snapshot_ids: list[str] = Field(description="Ordered twelve retained member evidence digests.")
    source_fingerprints: list[str] = Field(description="Ordered twelve exact calculation fingerprints.")


class CompositeAnnualDispersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: Literal["ANNUAL_MEMBER_DISPERSION"] = Field(
        default="ANNUAL_MEMBER_DISPERSION", description="Executed cross-sectional annual metric."
    )
    method: AnnualDispersionMethod = Field(description="Financial estimator actually executed.")
    method_version: Literal["v1"] = Field(default="v1", description="Registered financial method revision.")
    composite_id: str = Field(description="Analyzed composite identity.")
    period_start: date = Field(description="Inclusive annual start.")
    period_end: date = Field(description="Inclusive annual end.")
    return_view: CompositeReturnView = Field(description="Single fee basis.")
    reporting_currency: ReportingCurrency = Field(description="Single evidenced currency.")
    unit: Literal["DECIMAL_RETURN"] = Field(default="DECIMAL_RETURN", description="Decimal return ratio, not percent.")
    value: Decimal | None = Field(
        description="Dispersion quantized to 1e-12; null when population cannot support estimator."
    )
    status: Literal["AVAILABLE", "UNAVAILABLE"] = Field(description="Financial computability only.")
    reason_codes: list[str] = Field(description="Typed financial unavailability reasons.")
    year_end_member_count: int = Field(
        description="December included member count, independent of full-year intersection."
    )
    full_year_member_count: int = Field(description="Member count included for every complete calendar month.")
    reporting_applicability: Literal["NOT_REQUIRED_SMALL_POPULATION", "REQUIRES_PROFILE_REVIEW"] = Field(
        description="Provision-level presentation review signal, never methodology approval."
    )
    publication_state: Literal["CALCULATED_ANALYSIS"] = Field(
        default="CALCULATED_ANALYSIS", description="Analysis result requiring separate official publication controls."
    )
    qualification: Literal["RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"] = Field(
        default="RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED",
        description="Retained attested evidence was validated; live qualification is outside this operation.",
    )
    result_fingerprint: str = Field(
        description="Deterministic digest binding tenant, method, selected input versions and result."
    )
    months: list[AnnualDispersionMonthEvidence] = Field(
        description="Exact chronological source vector; no latest-version substitution."
    )
    members: list[AnnualDispersionMember] = Field(
        description="Sorted qualifying annual member economics and evidence references."
    )
