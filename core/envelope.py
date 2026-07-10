# core/envelope.py
from datetime import date
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from common.enums import canonical_performance_period_code


# --- NEW FX & Hedging Request Models ---
class FXRate(BaseModel):
    date: date
    ccy: str
    rate: float


class FXRequestBlock(BaseModel):
    source: Literal["CLIENT_SUPPLIED"] = "CLIENT_SUPPLIED"
    fixing: Literal["EOD"] = "EOD"
    rates: List[FXRate] = Field(default_factory=list)


class HedgeRatio(BaseModel):
    date: date
    ccy: str
    hedge_ratio: float = Field(..., ge=0.0, le=1.0)


class HedgingRequestBlock(BaseModel):
    mode: Literal["RATIO"] = "RATIO"
    series: List[HedgeRatio] = Field(default_factory=list)


# --- Existing Data Policy Models ---
class OverridesPolicy(BaseModel):
    market_values: List[Dict[str, Any]] = Field(default_factory=list)
    cash_flows: List[Dict[str, Any]] = Field(default_factory=list)


class IgnoreDaysPolicy(BaseModel):
    entity_type: Literal["PORTFOLIO", "POSITION"]
    entity_id: str
    dates: List[date]


class OutlierPolicy(BaseModel):
    enabled: bool = False
    scope: List[str] = ["SECURITY_RETURNS"]
    method: Literal["MAD"] = "MAD"
    params: Dict[str, Any] = {"mad_k": 5.0, "window": 63}
    action: Literal["FLAG"] = "FLAG"


class DataPolicy(BaseModel):
    overrides: Optional[OverridesPolicy] = None
    ignore_days: Optional[List[IgnoreDaysPolicy]] = None
    outliers: Optional[OutlierPolicy] = None


# --- Shared Request Components ---
class Calendar(BaseModel):
    type: Literal["BUSINESS", "NATURAL"] = "BUSINESS"
    trading_calendar: Optional[str] = "NYSE"


class Annualization(BaseModel):
    enabled: bool = Field(
        False, description="Whether to enable the calculation of annualized returns for applicable periods."
    )
    basis: Literal["BUS/252", "ACT/365", "ACT/ACT"] = Field(
        "BUS/252",
        description="The day-count convention to use. BUS/252 for business days; ACT/365 for actual days over 365; ACT/ACT for actual days over actual days in year.",
    )
    periods_per_year: Optional[float] = Field(
        None,
        description="Optional override for the annualization factor (e.g., 252 or 365). If provided, this value is used instead of the 'basis'.",
    )


class ExplicitPeriod(BaseModel):
    start: date
    end: date


class RollingPeriod(BaseModel):
    months: Optional[int] = None
    days: Optional[int] = None

    @model_validator(mode="after")
    def check_exclusive_fields(self) -> "RollingPeriod":
        if not (self.months is None) ^ (self.days is None):
            raise ValueError('Exactly one of "months" or "days" must be specified for rolling period.')
        return self


class Periods(BaseModel):
    type: Literal["YTD", "QTD", "MTD", "WTD", "1Y", "3Y", "5Y", "SI", "ROLLING", "EXPLICIT"] = "EXPLICIT"
    explicit: Optional[ExplicitPeriod] = None
    rolling: Optional[RollingPeriod] = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_period_aliases(cls, value):
        return canonical_performance_period_code(value)

    @model_validator(mode="after")
    def check_conditional_fields(self) -> "Periods":
        period_definition_issue = _period_definition_issue(
            period_type=self.type,
            explicit=self.explicit,
            rolling=self.rolling,
        )
        if period_definition_issue is not None:
            raise ValueError(period_definition_issue)
        return self


def _period_definition_issue(
    *,
    period_type: str,
    explicit: ExplicitPeriod | None,
    rolling: RollingPeriod | None,
) -> str | None:
    if period_type == "EXPLICIT" and explicit is None:
        return '"explicit" period definition is required when type is "EXPLICIT"'
    if period_type == "ROLLING" and rolling is None:
        return '"rolling" period definition is required when type is "ROLLING"'
    return None


class Output(BaseModel):
    include_timeseries: bool = False
    include_cumulative: bool = False
    top_n: Optional[int] = 20


class Flags(BaseModel):
    fail_fast: bool = Field(
        default=False,
        description=(
            "When true, completed TWR, MWR, Contribution, and Attribution responses that contain governed "
            "warning, fallback, diagnostic-note, degraded supportability, or supportability-reason evidence "
            "are rejected with HTTP 422 and error_code FAIL_FAST_SOFT_WARNING instead of returning a 200 "
            "degraded result. Async 202 Accepted envelopes are not rejected before execution completes."
        ),
    )


class BaseRequest(BaseModel):
    """Base Pydantic model for all performance-related API requests."""

    calculation_id: UUID = Field(default_factory=uuid4)
    as_of: date
    currency: str = "USD"
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = "FLOAT64"
    rounding_precision: int = 6
    calendar: Calendar = Field(default_factory=Calendar)
    annualization: Annualization = Field(default_factory=Annualization)
    periods: Periods
    output: Output = Field(default_factory=Output)
    flags: Flags = Field(default_factory=Flags)
    data_policy: Optional[DataPolicy] = None


# --- Shared Response Components ---
class Meta(BaseModel):
    calculation_id: UUID
    engine_version: str
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"]
    annualization: Annualization
    calendar: Calendar
    periods: Dict
    input_fingerprint: Optional[str] = None
    calculation_hash: Optional[str] = None
    report_ccy: Optional[str] = None


class PolicyDiagnostics(BaseModel):
    overrides: Dict[str, int] = {"applied_mv_count": 0, "applied_cf_count": 0}
    ignored_days_count: int = 0
    outliers: Dict[str, int] = {"flagged_rows": 0}


class Diagnostics(BaseModel):
    nip_days: int
    nip_rule_delta_days: int | None = None
    reset_days: int
    nctrl4_reset_days: int | None = None
    nctrl4_exclusive_reset_days: int | None = None
    account_reset_shadow_days: int | None = None
    sod_reset_shadow_days: int | None = None
    shadow_reset_overlap_days: int | None = None
    shadow_only_candidate_reset_days: int | None = None
    active_reset_with_shadow_days: int | None = None
    candidate_canonical_reset_days: int | None = None
    reset_delta_days: int | None = None
    nip_days_since_last_reset: int | None = None
    valid_days_since_last_reset: int | None = None
    effective_period_start: date
    notes: List[str] = Field(default_factory=list)
    policy: Optional[PolicyDiagnostics] = None
    samples: Optional[Dict[str, List[Dict]]] = None


class Audit(BaseModel):
    sum_of_parts_vs_total_bp: Optional[float] = None
    residual_applied_bp: Optional[float] = None
    counts: Dict[str, int] = Field(default_factory=dict)


class BaseResponse(BaseModel):
    """Base Pydantic model for all performance-related API responses."""

    meta: Meta
    diagnostics: Diagnostics
    audit: Audit
