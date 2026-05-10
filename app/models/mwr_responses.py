# app/models/mwr_responses.py
from datetime import date
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.mwr_analytics_requests import MWRInputMode
from app.models.mwr_requests import CashFlow
from app.models.responses import PerformanceCalculationSupportability
from core.envelope import Audit, Diagnostics, Meta


class Convergence(BaseModel):
    iterations: Optional[int] = Field(
        default=None, description="Number of solver iterations used when an iterative method ran.", examples=[8]
    )
    residual: Optional[float] = Field(
        default=None,
        description="Final solver residual in decimal form for the numerical algorithm.",
        examples=[1e-10],
    )
    converged: Optional[bool] = Field(default=None, description="Whether the numerical method converged successfully.")
    algorithm: Optional[str] = Field(default=None, description="Solver algorithm used for root detection/refinement.")
    root_count_detected: Optional[int] = Field(default=None, description="Number of unique XIRR roots detected.")
    residual_npv: Optional[float] = Field(default=None, description="Final NPV residual for the selected root.")
    rate_lower_bound: Optional[float] = Field(default=None, description="Lower searched annual rate bound.")
    rate_upper_bound: Optional[float] = Field(default=None, description="Upper searched annual rate bound.")
    day_count_basis: Optional[str] = Field(default=None, description="Day-count convention used for dated XIRR.")
    anchor_date: Optional[date] = Field(default=None, description="Anchor date used for year-fraction calculation.")
    normalized_flow_count: Optional[int] = Field(default=None, description="Number of normalized solver flows.")
    gross_cash_flow_scale: Optional[float] = Field(default=None, description="Gross absolute solver-flow scale.")


class MWRResult(BaseModel):
    """A simple data container for the results of an MWR calculation from the engine."""

    mwr: float = Field(description="Money-weighted return in percentage-point output units.", examples=[11.723])
    mwr_annualized: Optional[float] = Field(
        default=None,
        description="Annualized money-weighted return in percentage-point output units when available.",
        examples=[18.42],
    )
    method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"] = Field(description="Computation method used for the result.")
    start_date: date = Field(description="Inclusive start date for the evaluated window.", examples=["2026-01-01"])
    end_date: date = Field(description="Inclusive end date for the evaluated window.", examples=["2026-03-31"])
    notes: List[str] = Field(description="Method or validation notes returned by the engine.")
    convergence: Optional[Convergence] = Field(
        default=None, description="Numerical convergence diagnostics when applicable."
    )
    status: Literal["CALCULATED", "FALLBACK_USED", "NOT_CALCULABLE", "NOT_APPLICABLE"] = Field(
        default="CALCULATED", description="Calculation status for the MWR result."
    )
    reason_codes: List[str] = Field(default_factory=list, description="Machine-readable reason codes.")
    warnings: List[str] = Field(default_factory=list, description="Machine-readable warning codes.")
    holding_period_return: Optional[float] = Field(
        default=None, description="Holding-period money-weighted return in percentage-point output units."
    )
    is_annualized_primary: Optional[bool] = Field(
        default=None, description="Whether money_weighted_return is an annualized value."
    )
    fallback_from: Optional[str] = Field(default=None, description="Primary method that fell back, when applicable.")
    fallback_reason: Optional[str] = Field(default=None, description="Reason fallback method was used.")
    is_approximation: Optional[bool] = Field(default=None, description="Whether the returned method is approximate.")


class MoneyWeightedReturnResponse(BaseModel):
    """Response model for a Money-Weighted Return calculation."""

    calculation_id: UUID = Field(description="Stable calculation handle for this MWR request.")
    portfolio_id: str = Field(description="Portfolio identifier.", examples=["PORTFOLIO_001"])
    input_mode: MWRInputMode = Field(default=MWRInputMode.STATELESS, description="Resolved MWR input mode.")

    money_weighted_return: float = Field(
        description="Money-weighted return in percentage-point output units.",
        examples=[11.723],
    )
    mwr_annualized: Optional[float] = Field(
        default=None,
        description="Annualized money-weighted return in percentage-point output units when available.",
        examples=[18.42],
    )
    method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"] = Field(description="Computation method used for the result.")
    status: Literal["CALCULATED", "FALLBACK_USED", "NOT_CALCULABLE", "NOT_APPLICABLE"] = Field(
        default="CALCULATED", description="Calculation status for the MWR result."
    )
    reason_codes: List[str] = Field(default_factory=list, description="Machine-readable reason codes.")
    warnings: List[str] = Field(default_factory=list, description="Machine-readable warning codes.")
    holding_period_return: Optional[float] = Field(
        default=None, description="Holding-period money-weighted return in percentage-point output units."
    )
    is_annualized_primary: Optional[bool] = Field(
        default=None, description="Whether money_weighted_return is an annualized value."
    )
    fallback_from: Optional[str] = Field(default=None, description="Primary method that fell back, when applicable.")
    fallback_reason: Optional[str] = Field(default=None, description="Reason fallback method was used.")
    is_approximation: Optional[bool] = Field(default=None, description="Whether the returned method is approximate.")
    convergence: Optional[Convergence] = Field(
        default=None, description="Numerical convergence diagnostics when applicable."
    )
    cashflows_used: Optional[List[CashFlow]] = Field(
        default=None,
        description="Cash flows used by the MWR calculation in reporting currency units.",
    )
    start_date: date = Field(description="Inclusive start date for the evaluated window.", examples=["2026-01-01"])
    end_date: date = Field(description="Inclusive end date for the evaluated window.", examples=["2026-03-31"])
    notes: List[str] = Field(description="Method or validation notes returned by the engine.")
    calculation_supportability: PerformanceCalculationSupportability = Field(
        description=(
            "Bounded supportability state for completed MWR output, including source freshness and "
            "resolved-input counts used by front-office degraded-state handling."
        )
    )

    meta: Meta = Field(description="Shared metadata envelope for the calculation.")
    diagnostics: Diagnostics = Field(description="Diagnostic details for the calculation.")
    audit: Audit = Field(description="Audit details for the calculation.")
