# app/models/mwr_requests.py
from datetime import date
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.envelope import Annualization, Calendar, Flags, Output, Periods


class CashFlow(BaseModel):
    """Represents a single cash flow with its date and amount."""

    amount: float
    date: date


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


class MoneyWeightedReturnRequest(MoneyWeightedReturnRequestBase):
    """Request model for calculating Money-Weighted Return."""

    begin_mv: float
    end_mv: float
    cash_flows: List[CashFlow]
