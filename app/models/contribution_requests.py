# app/models/contribution_requests.py
from datetime import date
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.requests import Analysis  # Import the new shared model
from common.enums import WeightingScheme
from core.envelope import (
    Annualization,
    Calendar,
    DataPolicy,
    Flags,
    FXRequestBlock,
    HedgingRequestBlock,
    Output,
)


class PositionDailyData(BaseModel):
    """Time series data for a single position on a single day."""

    model_config = ConfigDict(extra="forbid")

    perf_date: date = Field(..., description="Observation date for the valuation point.")
    begin_mv: float = Field(..., description="Beginning market value before any cash flows.")
    end_mv: float = Field(..., description="Ending market value after market movement and fees.")
    bod_cf: float = Field(0.0, description="Beginning-of-day cash flow applied before performance.")
    eod_cf: float = Field(0.0, description="End-of-day cash flow applied after performance.")
    mgmt_fees: float = Field(0.0, description="Management fees booked for the day.")


class PositionData(BaseModel):
    """Contains the full time series and metadata for a single position."""

    position_id: str = Field(..., description="Position identifier.")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Position metadata used for grouping and labels.")
    valuation_points: List[PositionDailyData] = Field(
        ...,
        description="Canonical position valuation observations ordered by perf_date. Sequence is derived server-side.",
    )


class PortfolioData(BaseModel):
    """Contains the full time series and config for the total portfolio."""

    metric_basis: Literal["NET", "GROSS"] = Field(..., description="Whether portfolio inputs are net or gross of fees.")
    valuation_points: List[PositionDailyData] = Field(
        ...,
        description="Canonical portfolio valuation observations ordered by perf_date. Sequence is derived server-side.",
    )


class Smoothing(BaseModel):
    method: Literal["CARINO", "NONE"] = "CARINO"


class Emit(BaseModel):
    timeseries: bool = False
    by_position_timeseries: bool = False
    by_level: bool = False
    top_n_per_level: int = 20
    threshold_weight: float = 0.005
    include_other: bool = True
    include_unclassified: bool = True
    residual_per_position: bool = False


class Lookthrough(BaseModel):
    enabled: bool = False
    fallback_policy: Literal["error", "unclassified", "scale_to_1"] = "error"


class ContributionRequestBase(BaseModel):
    """Common contribution analytics configuration independent of input mode."""

    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(default_factory=uuid4)
    portfolio_id: str
    report_start_date: date
    report_end_date: date
    analyses: List[Analysis]

    hierarchy: Optional[List[str]] = None
    weighting_scheme: WeightingScheme = WeightingScheme.BOD
    smoothing: Smoothing = Field(default_factory=Smoothing)
    emit: Emit = Field(default_factory=Emit)
    lookthrough: Lookthrough = Field(default_factory=Lookthrough)
    bucketing: Optional[Dict[str, Any]] = None
    currency: str = "USD"
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = "FLOAT64"
    rounding_precision: int = 6
    calendar: Calendar = Field(default_factory=Calendar)
    annualization: Annualization = Field(default_factory=Annualization)
    output: Output = Field(default_factory=Output)
    flags: Flags = Field(default_factory=Flags)
    data_policy: Optional[DataPolicy] = None

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


class ContributionRequest(ContributionRequestBase):
    """Stateless request model consumed by the contribution engine."""

    portfolio_data: PortfolioData
    positions_data: List[PositionData]
