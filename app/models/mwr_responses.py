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
