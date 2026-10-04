"""Pinned annual result comparison; no official revision selection."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest, CompositeAnnualDispersionResponse


class CompositeAnnualComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: CompositeAnnualDispersionRequest = Field(description="Explicit pinned baseline receipt vector.")
    candidate: CompositeAnnualDispersionRequest = Field(description="Explicit pinned candidate receipt vector.")

    @model_validator(mode="after")
    def common_scope(self) -> "CompositeAnnualComparisonRequest":
        fields = ("composite_id", "year", "return_view", "reporting_currency", "method")
        if any(getattr(self.baseline, name) != getattr(self.candidate, name) for name in fields):
            raise ValueError("baseline and candidate must share composite, year, return view, currency and method")
        return self


class CompositeAnnualComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: Literal["DISPERSION_OUTPUT_DELTA"] = "DISPERSION_OUTPUT_DELTA"
    comparison_version: Literal["v1"] = "v1"
    convention: Literal["DIFFERENCE_OF_QUANTIZED_V1_OUTPUTS"] = "DIFFERENCE_OF_QUANTIZED_V1_OUTPUTS"
    unit: Literal["DECIMAL_RETURN"] = "DECIMAL_RETURN"
    baseline: CompositeAnnualDispersionResponse = Field(description="Complete independently admitted baseline result.")
    candidate: CompositeAnnualDispersionResponse = Field(
        description="Complete independently admitted candidate result."
    )
    value: Decimal | None = Field(description="Candidate minus baseline v1 output; null if either is unavailable.")
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    reason_codes: list[str] = Field(description="Side-prefixed annual unavailability reasons.")
    full_year_members_added: list[str] = Field(
        description="Sorted candidate full-year identities absent from baseline."
    )
    full_year_members_removed: list[str] = Field(
        description="Sorted baseline full-year identities absent from candidate."
    )
    result_fingerprint: str = Field(description="Digest binding tenant, both complete results and comparison version.")
