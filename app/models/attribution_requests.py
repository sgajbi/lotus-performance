from __future__ import annotations

# app/models/attribution_requests.py
from datetime import date as Date
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

    metric_basis: Literal["NET", "GROSS"] = Field(
        description="Portfolio return basis used to build attribution inputs. NET includes fee drag; GROSS neutralizes it.",
        examples=["NET"],
    )
    valuation_points: List[DailyInputData] = Field(
        description="Total portfolio valuation observations used to derive instrument weights in by_instrument mode.",
    )


class InstrumentData(BaseModel):
    """Time series and metadata for a single instrument."""

    instrument_id: str = Field(description="Stable instrument or position identifier.", examples=["AAPL_US"])
    meta: Dict[str, Any] = Field(
        description="Instrument grouping metadata. Keys should cover every requested group_by dimension.",
        examples=[{"asset_class": "equity", "sector": "technology", "currency": "USD"}],
    )
    valuation_points: List[DailyInputData] = Field(
        description="Instrument valuation observations used to compute group returns and beginning weights.",
    )


class BenchmarkObservation(BaseModel):
    """Represents a single benchmark data point for a period."""

    date: Date = Field(description="Observation date for the benchmark group return and beginning weight.")
    weight_bop: float = Field(
        description="Benchmark group beginning-of-period weight as a decimal ratio. Example: 0.6 means 60%.",
        examples=[0.6],
    )
    return_base: float = Field(
        description="Benchmark group base-currency return for the observation as a decimal ratio.",
        examples=[0.0125],
    )
    return_local: Optional[float] = Field(
        default=None,
        description="Optional local-currency benchmark return as a decimal ratio for currency-aware attribution.",
        examples=[0.01],
    )
    return_fx: Optional[float] = Field(
        default=None,
        description="Optional FX return component as a decimal ratio for currency-aware attribution.",
        examples=[0.0025],
    )


class BenchmarkGroup(BaseModel):
    """Time series data for a single benchmark group."""

    key: Dict[str, Any] = Field(
        description="Benchmark grouping key. Keys must match the requested group_by dimensions.",
        examples=[{"asset_class": "equity"}],
    )
    observations: List[BenchmarkObservation] = Field(
        description="Benchmark group observations aligned to the attribution period."
    )


class PortfolioGroup(BaseModel):
    """Pre-aggregated time series data for a single portfolio group."""

    key: Dict[str, Any] = Field(
        description="Portfolio grouping key. Keys must match the requested group_by dimensions.",
        examples=[{"asset_class": "equity"}],
    )
    observations: List[Dict] = Field(
        description=(
            "Portfolio group observations. Each observation should include date, weight_bop, and return_base; "
            "return_local and return_fx are used by currency-aware attribution when present."
        )
    )


class AttributionRequest(BaseModel):
    """Request model for the Attribution engine."""

    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Optional caller-supplied idempotency and lineage handle for this attribution calculation.",
    )
    portfolio_id: str = Field(
        description="Portfolio identifier for lineage and downstream correlation.", examples=["PORT_001"]
    )
    report_start_date: Date = Field(description="Inclusive report window start date.")
    report_end_date: Date = Field(description="Inclusive report window end date.")
    analyses: List[Analysis] = Field(description="Analysis periods to calculate over the requested report window.")

    mode: AttributionMode = Field(
        description="Attribution input shape. Use by_instrument for position-level portfolio inputs or by_group for pre-aggregated group inputs.",
        examples=["by_instrument"],
    )
    frequency: Frequency = Field(
        default=Frequency.MONTHLY,
        description="Frequency used to resample observations before attribution effects are linked.",
        examples=["monthly"],
    )
    group_by: List[str] = Field(
        ...,
        min_length=1,
        description="Ordered grouping dimensions for attribution levels, for example asset_class then sector.",
        examples=[["asset_class"], ["asset_class", "sector"]],
        json_schema_extra={"example": ["asset_class"]},
    )
    model: AttributionModel = Field(
        default=AttributionModel.BRINSON_FACHLER,
        description="Attribution model used for allocation, selection, and interaction effects.",
        examples=["BF"],
    )
    linking: LinkingMethod = Field(
        default=LinkingMethod.CARINO,
        description="Multi-period linking method used to reconcile summed effects to active return.",
        examples=["carino"],
    )
    portfolio_data: Optional[AttributionPortfolioData] = Field(
        default=None,
        description="Legacy stateless total portfolio series for by_instrument mode. Prefer stateless_input for new callers.",
    )
    instruments_data: Optional[List[InstrumentData]] = Field(
        default=None,
        description="Legacy stateless instrument series for by_instrument mode. Prefer stateless_input for new callers.",
    )
    portfolio_groups_data: Optional[List[PortfolioGroup]] = Field(
        default=None,
        description="Legacy stateless pre-aggregated portfolio groups for by_group mode. Prefer stateless_input for new callers.",
    )
    benchmark_groups_data: List[BenchmarkGroup] = Field(
        description="Benchmark group observations used to calculate benchmark returns and active effects."
    )
    currency: str = Field(default="USD", description="Base currency for attribution output.", examples=["USD"])
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = Field(
        default="FLOAT64",
        description="Numeric precision mode. FLOAT64 is the current production execution path.",
        examples=["FLOAT64"],
    )
    rounding_precision: int = Field(
        default=6,
        description="Requested decimal precision for rounded presentation fields where rounding is applied.",
        examples=[6],
    )
    calendar: Calendar = Field(default_factory=Calendar, description="Calendar controls used by period resolution.")
    annualization: Annualization = Field(default_factory=Annualization, description="Annualization controls.")
    output: Output = Field(default_factory=Output, description="Output selection and diagnostics controls.")
    flags: Flags = Field(default_factory=Flags, description="Engine behavior flags.")
    currency_mode: Optional[Literal["BASE_ONLY", "LOCAL_ONLY", "BOTH"]] = Field(
        default="BASE_ONLY",
        description="Currency attribution mode. Use BOTH with report_ccy and FX data for Karnosky-Singer effects.",
        examples=["BASE_ONLY"],
    )
    report_ccy: Optional[str] = Field(
        default=None,
        description="Reporting currency for multi-currency attribution when currency_mode is BOTH.",
        examples=["USD"],
    )
    fx: Optional[FXRequestBlock] = Field(
        default=None,
        description="Optional FX request block required for some currency-aware attribution scenarios.",
    )
    hedging: Optional[HedgingRequestBlock] = Field(
        default=None,
        description="Optional hedging request block for hedged multi-currency calculations.",
    )

    @field_validator("analyses")
    @classmethod
    def analyses_must_not_be_empty(cls, v):
        if not v:
            raise ValueError("analyses list cannot be empty")
        return v
