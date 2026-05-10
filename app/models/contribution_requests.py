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
    method: Literal["CARINO", "NONE"] = Field(
        default="CARINO",
        description=(
            "Contribution linking method. CARINO links multi-period contribution so rows reconcile "
            "to geometric portfolio return when the return path stays inside the valid logarithmic domain; "
            "it applies the Carino factor F_t = k_t / K to raw daily contribution, where "
            "k_t = log1p(daily portfolio return) / daily portfolio return and K is the same factor "
            "for the linked period return. "
            "NONE leaves daily contribution unlinked."
        ),
        examples=["CARINO"],
    )


class Emit(BaseModel):
    timeseries: bool = Field(
        default=False,
        description=("When true, emit the residual-adjusted daily total contribution series for each resolved period."),
        examples=[True],
    )
    by_position_timeseries: bool = Field(
        default=False,
        description=(
            "When true, emit residual-adjusted daily contribution series for each position. The summed "
            "position daily series reconciles to the period total contribution."
        ),
        examples=[True],
    )
    by_level: bool = Field(
        default=False,
        description=(
            "Requests hierarchy-level output when hierarchy dimensions are supplied. For backward "
            "compatibility, hierarchy dimensions also imply level output."
        ),
        examples=[True],
    )
    top_n_per_level: int = Field(
        default=20,
        description=(
            "Maximum explicit rows to emit for each hierarchy level before excluded rows are rolled "
            "into an Other bucket when include_other is true."
        ),
        examples=[10],
    )
    threshold_weight: float = Field(
        default=0.005,
        description=(
            "Minimum average weight ratio for an explicit hierarchy row. Example: 0.005 means 0.5% "
            "average portfolio weight."
        ),
        examples=[0.005],
    )
    include_other: bool = Field(
        default=True,
        description="Whether rows excluded by top_n_per_level or threshold_weight are rolled into an Other bucket.",
        examples=[True],
    )
    include_unclassified: bool = Field(
        default=True,
        description=(
            "Whether positions missing a requested hierarchy dimension are retained under an "
            "Unclassified bucket. When false, those rows are excluded from hierarchy rows."
        ),
        examples=[True],
    )
    residual_per_position: bool = Field(
        default=False,
        description=(
            "Reserved compatibility flag for older clients. Current contribution output always keeps "
            "position, daily, and hierarchy totals reconciled through the service's residual allocation policy."
        ),
        examples=[False],
    )


class Lookthrough(BaseModel):
    enabled: bool = Field(
        default=False,
        description=(
            "Reserved look-through switch for fund or structured-product decomposition. Current stateful "
            "contribution expects position rows from lotus-core at the requested visible scope."
        ),
        examples=[False],
    )
    fallback_policy: Literal["error", "unclassified", "scale_to_1"] = Field(
        default="error",
        description="Reserved fallback policy for future look-through decomposition gaps.",
        examples=["error"],
    )


class ContributionRequestBase(BaseModel):
    """Common contribution analytics configuration independent of input mode."""

    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Client-supplied or server-generated stable calculation identifier.",
    )
    portfolio_id: str = Field(description="Portfolio identifier for the contribution calculation.")
    report_start_date: date = Field(description="Inclusive report start date.")
    report_end_date: date = Field(description="Inclusive report end date.")
    analyses: List[Analysis] = Field(description="Resolved contribution periods and requested frequencies.")

    hierarchy: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional hierarchy dimensions such as asset_class, sector, country, currency, or position_id. "
            "When supplied, the response includes summary and level rows that reconcile to period contribution."
        ),
        examples=[["asset_class"]],
    )
    weighting_scheme: WeightingScheme = Field(
        default=WeightingScheme.BOD,
        description="Position weighting convention used for daily contribution.",
        examples=["BOD"],
    )
    smoothing: Smoothing = Field(default_factory=Smoothing)
    emit: Emit = Field(default_factory=Emit)
    lookthrough: Lookthrough = Field(default_factory=Lookthrough)
    bucketing: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional future bucketing rules for hierarchy rows.",
        examples=[{"sector": {"unclassified_label": "Unclassified"}}],
    )
    currency: str = Field(
        default="USD", description="Portfolio base currency for stateless requests.", examples=["USD"]
    )
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = Field(
        default="FLOAT64",
        description="Numeric precision mode used by the calculation engine.",
        examples=["FLOAT64"],
    )
    rounding_precision: int = Field(
        default=6,
        description="Decimal places used for configured rounding-sensitive outputs.",
        examples=[6],
    )
    calendar: Calendar = Field(default_factory=Calendar)
    annualization: Annualization = Field(default_factory=Annualization)
    output: Output = Field(default_factory=Output)
    flags: Flags = Field(default_factory=Flags)
    data_policy: Optional[DataPolicy] = None

    currency_mode: Optional[Literal["BASE_ONLY", "LOCAL_ONLY", "BOTH"]] = Field(
        default=None,
        description=(
            "Currency treatment for contribution. BASE_ONLY uses portfolio currency, LOCAL_ONLY uses "
            "position currency, and BOTH emits local and FX contribution where supported."
        ),
        examples=["BASE_ONLY"],
    )
    report_ccy: Optional[str] = Field(
        default=None,
        description="Optional reporting currency for stateful or multi-currency contribution.",
        examples=["USD"],
    )
    fx: Optional[FXRequestBlock] = Field(
        default=None,
        description="Optional FX rates for stateless or mixed-currency contribution calculations.",
    )
    hedging: Optional[HedgingRequestBlock] = Field(
        default=None,
        description="Optional hedging request block for FX-aware contribution extensions.",
    )

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
