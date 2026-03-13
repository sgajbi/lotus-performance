# app/models/attribution_requests.py
from datetime import date
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.requests import Analysis, DailyInputData  # Import the shared Analysis model
from common.enums import (
    AttributionMode,
    AttributionModel,
    Frequency,
    LinkingMethod,
)
from core.envelope import (
    Annualization,
    Calendar,
    Flags,
    FXRequestBlock,
    HedgingRequestBlock,
    Output,
)


class AttributionPortfolioData(BaseModel):
    """Contains the full time series and config for the total portfolio for attribution."""

    metric_basis: Literal["NET", "GROSS"]
    valuation_points: List[DailyInputData]


class InstrumentData(BaseModel):
    """Time series and metadata for a single instrument."""

    instrument_id: str
    meta: Dict[str, Any]
    valuation_points: List[DailyInputData]


class BenchmarkObservation(BaseModel):
    """Represents a single benchmark data point for a period."""

    date: date
    weight_bop: float
    return_base: float
    return_local: Optional[float] = None
    return_fx: Optional[float] = None


class BenchmarkGroup(BaseModel):
    """Time series data for a single benchmark group."""

    key: Dict[str, Any]
    observations: List[BenchmarkObservation]


class PortfolioGroup(BaseModel):
    """Pre-aggregated time series data for a single portfolio group."""

    key: Dict[str, Any]
    observations: List[Dict]


class AttributionRequest(BaseModel):
    """Request model for the Attribution engine."""

    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(default_factory=uuid4)
    portfolio_id: str
    report_start_date: date
    report_end_date: date
    analyses: List[Analysis]

    mode: AttributionMode
    frequency: Frequency = Frequency.MONTHLY
    group_by: List[str] = Field(..., min_length=1)
    model: AttributionModel = AttributionModel.BRINSON_FACHLER
    linking: LinkingMethod = LinkingMethod.CARINO
    portfolio_data: Optional[AttributionPortfolioData] = None
    instruments_data: Optional[List[InstrumentData]] = None
    portfolio_groups_data: Optional[List[PortfolioGroup]] = None
    benchmark_groups_data: List[BenchmarkGroup]
    currency: str = "USD"
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = "FLOAT64"
    rounding_precision: int = 6
    calendar: Calendar = Field(default_factory=Calendar)
    annualization: Annualization = Field(default_factory=Annualization)
    output: Output = Field(default_factory=Output)
    flags: Flags = Field(default_factory=Flags)
    currency_mode: Optional[Literal["BASE_ONLY", "LOCAL_ONLY", "BOTH"]] = "BASE_ONLY"
    report_ccy: Optional[str] = None
    fx: Optional[FXRequestBlock] = None
    hedging: Optional[HedgingRequestBlock] = None

    @field_validator("analyses")
    @classmethod
    def analyses_must_not_be_empty(cls, v):
        if not v:
            raise ValueError("analyses list cannot be empty")
        return v
