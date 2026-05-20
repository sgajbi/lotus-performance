# app/models/mwr_requests.py
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.envelope import Annualization, Calendar, Flags, Output, Periods


class CashFlow(BaseModel):
    """Represents a single cash flow with its date and amount."""

    amount: float
    date: date


class MWRSourcePreconvertedFXComponent(BaseModel):
    """Per-input FX provenance for a value that was converted before MWR execution."""

    source_amount: Decimal = Field(description="Amount in the source currency before upstream conversion.")
    source_currency: str = Field(description="Currency of the source amount before upstream conversion.")
    reporting_amount: Decimal = Field(description="Amount supplied to MWR in the reporting currency.")
    reporting_currency: str = Field(description="Reporting currency used by the MWR calculation.")
    fx_rate: Decimal = Field(gt=0, description="Positive source-to-reporting FX rate applied upstream.")
    fx_pair: str = Field(description="Currency pair used for upstream conversion, for example EUR/USD.")
    fx_rate_date: date = Field(description="Date of the FX rate used for upstream conversion.")
    fx_rate_source: str = Field(description="Authoritative source of the FX rate.")
    fx_rate_version: str = Field(description="Version, snapshot, or fixing identifier for the FX rate.")
    conversion_policy: str = Field(description="Named policy used to select and apply the FX rate.")
    conversion_timestamp: datetime = Field(description="Timestamp when the upstream conversion was performed.")
    conversion_fingerprint: str = Field(description="Stable fingerprint of the conversion evidence.")


class MWRMarketValueFXEvidence(MWRSourcePreconvertedFXComponent):
    value_role: Literal["beginning_market_value", "ending_market_value"] = Field(
        description="Whether the evidence covers the beginning or ending market value."
    )


class MWRCashFlowFXEvidence(MWRSourcePreconvertedFXComponent):
    cash_flow_index: int = Field(ge=0, description="Zero-based index of the corresponding cash flow.")
    cash_flow_date: date = Field(description="Date of the corresponding cash flow.")


class MWRSourcePreconvertedFXEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_scope: Literal["stateless_mwr_source_preconverted"] = Field(
        default="stateless_mwr_source_preconverted",
        description="Scope of source-preconverted FX evidence supplied by the caller.",
    )
    market_values: List[MWRMarketValueFXEvidence] = Field(
        description="Complete beginning and ending market-value conversion evidence."
    )
    cash_flows: List[MWRCashFlowFXEvidence] = Field(
        description="Complete per-cash-flow conversion evidence aligned by cash_flow_index."
    )


class Solver(BaseModel):
    method: str = "brent"
    max_iter: int = 200
    tolerance: float = 1e-10
    rate_lower_bound: float = -0.999999999
    rate_upper_bound: float = 1000.0
    root_scan_steps: int = 512


class MoneyWeightedReturnRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(default_factory=uuid4)
    portfolio_id: str
    mwr_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"] = "XIRR"
    solver: Solver = Field(default_factory=Solver)
    emit_cashflows_used: bool = True
    as_of: date
    start_date: Optional[date] = None
    currency: str = "USD"
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = "FLOAT64"
    rounding_precision: int = 6
    calendar: Calendar = Field(default_factory=Calendar)
    annualization: Annualization = Field(default_factory=Annualization)
    periods: Optional[Periods] = None
    output: Output = Field(default_factory=Output)
    flags: Flags = Field(default_factory=Flags)
    report_ccy: Optional[str] = None
    source_preconverted_fx_evidence: Optional[MWRSourcePreconvertedFXEvidence] = Field(
        default=None,
        description=(
            "Optional complete FX provenance for stateless MWR inputs that were converted upstream. "
            "Lotus-performance validates this evidence and computes on the supplied reporting amounts; "
            "it does not convert source-currency amounts inside the MWR engine."
        ),
    )


class MoneyWeightedReturnRequest(MoneyWeightedReturnRequestBase):
    """Request model for calculating Money-Weighted Return."""

    begin_mv: float
    end_mv: float
    cash_flows: List[CashFlow]
