# app/models/requests.py
from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.request_window_validation import validate_ordered_explicit_window
from common.enums import Frequency, PeriodType, canonical_performance_period_code
from core.envelope import (
    Annualization,
    Calendar,
    DataPolicy,
    Flags,
    FXRequestBlock,
    HedgingRequestBlock,
    Output,
)
from core.monetary_input import MoneyInput
from core.valuation_observation_admission import admit_valuation_observations


class DailyInputData(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    perf_date: date = Field(..., description="The specific date of the observation in YYYY-MM-DD format.")
    begin_mv: MoneyInput = Field(
        ..., description="The market value of the portfolio at the beginning of the day, before any cash flows."
    )
    bod_cf: MoneyInput = Field(
        Decimal(0),
        description="Cash flow occurring at the beginning of the day (before trading). Positive for inflows, negative for outflows.",
    )
    eod_cf: MoneyInput = Field(
        Decimal(0),
        description="Cash flow occurring at the end of the day (after trading). Positive for inflows, negative for outflows.",
    )
    mgmt_fees: MoneyInput = Field(
        Decimal(0),
        description="Management or other fees charged for the day. Should be a negative value to reduce performance.",
    )
    end_mv: MoneyInput = Field(
        ...,
        allow_inf_nan=False,
        description="The market value of the portfolio at the end of the day.",
    )


def admit_daily_input_data(value: List[DailyInputData]) -> List[DailyInputData]:
    """Return the canonical first-occurrence list after daily economic admission."""
    serialized = [point.model_dump(mode="python") for point in value]
    admitted = admit_valuation_observations(serialized)
    admitted_ids = {id(point) for point in admitted}
    return [point for point, payload in zip(value, serialized, strict=True) if id(payload) in admitted_ids]


class FeeEffect(BaseModel):
    enabled: bool = False


class ResetPolicy(BaseModel):
    emit: bool = Field(
        False, description="If true, the response will include a list of any performance reset events that occurred."
    )


from app.models.source_quality import PerformanceSourceQualityEvidence  # noqa: E402


class Analysis(BaseModel):
    """Defines a single analysis with its period and desired frequencies."""

    period: PeriodType = Field(
        ...,
        description=(
            "Reporting period to resolve. Supported canonical values: MTD, QTD, YTD, SI, 1Y, 3Y, 5Y, "
            "EXPLICIT. Legacy aliases ITD, INCEPTION_TO_DATE, and SINCE_INCEPTION are accepted and "
            "normalized to SI."
        ),
    )
    frequencies: List[Frequency] = Field(
        ...,
        description="Breakdown frequencies to emit for the resolved period. Supported values: daily, weekly, monthly, quarterly, yearly.",
    )

    @field_validator("frequencies")
    @classmethod
    def frequencies_must_not_be_empty(cls, v):
        if not v:
            raise ValueError("frequencies list cannot be empty for an analysis")
        return v

    @field_validator("period", mode="before")
    @classmethod
    def normalize_period_aliases(cls, value):
        return canonical_performance_period_code(value)


class PerformanceRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="A unique identifier for the calculation request. If not provided, one will be generated.",
    )
    portfolio_id: str = Field(..., description="A unique identifier for the portfolio being analyzed.")
    performance_start_date: Optional[date] = Field(
        None,
        description=(
            "The inception date of the portfolio or the earliest date for which performance data is available. "
            "Some stateful request flows allow lotus-performance to derive this value upstream."
        ),
    )
    metric_basis: Literal["NET", "GROSS"] = Field(
        ..., description="Specifies whether to calculate returns 'NET' (after fees) or 'GROSS' (before fees)."
    )
    report_start_date: Optional[date] = Field(
        None,
        description=(
            "The start date for an 'EXPLICIT' period calculation; it must be on or before report_end_date. "
            "Ignored for other period types."
        ),
    )
    report_end_date: date = Field(
        ...,
        description="The final date of the analysis period. Also used as the anchor date for resolving relative periods like YTD.",
    )
    analyses: List[Analysis] = Field(..., description="Requested period analyses and breakdown frequencies.")

    valuation_points: List[DailyInputData] = Field(
        ...,
        description=(
            "Finite canonical portfolio valuation observations. Identical observations for a business date are "
            "admitted once; conflicting economics for that date are rejected. Sequence is derived server-side."
        ),
    )
    currency: str = Field("USD", description="The three-letter ISO currency code for the request (e.g., 'USD').")
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = Field(
        "FLOAT64", description="The numerical precision mode for the calculation engine."
    )
    rounding_precision: int = Field(6, description="The number of decimal places to round final float results to.")
    calendar: Calendar = Field(default_factory=Calendar)
    annualization: Annualization = Field(default_factory=Annualization)
    output: Output = Field(default_factory=Output)
    flags: Flags = Field(default_factory=Flags)
    fee_effect: FeeEffect = Field(default_factory=FeeEffect)
    reset_policy: ResetPolicy = Field(default_factory=ResetPolicy)
    data_policy: Optional[DataPolicy] = None
    source_quality_evidence: Optional[PerformanceSourceQualityEvidence] = Field(
        default=None,
        description="Internal source-quality evidence preserved from stateful source normalization.",
    )

    currency_mode: Optional[Literal["BASE_ONLY", "LOCAL_ONLY", "BOTH"]] = None
    report_ccy: Optional[str] = None
    fx: Optional[FXRequestBlock] = None
    hedging: Optional[HedgingRequestBlock] = None

    @field_validator("analyses")
    @classmethod
    def analyses_must_not_be_empty(cls, v):
        if not v:
            raise ValueError("analyses list cannot be empty")
        return v

    @field_validator("valuation_points")
    @classmethod
    def valuation_points_must_have_consistent_daily_economics(
        cls,
        value: List[DailyInputData],
    ) -> List[DailyInputData]:
        return admit_daily_input_data(value)

    @model_validator(mode="after")
    def validate_explicit_window_order(self) -> "PerformanceRequestBase":
        validate_ordered_explicit_window(
            requested_periods=(analysis.period for analysis in self.analyses),
            report_start_date=self.report_start_date,
            report_end_date=self.report_end_date,
        )
        return self


class PerformanceRequest(PerformanceRequestBase):
    performance_start_date: date = Field(
        ...,
        description="The inception date of the portfolio or the earliest date for which performance data is available.",
    )
    valuation_points: List[DailyInputData]
