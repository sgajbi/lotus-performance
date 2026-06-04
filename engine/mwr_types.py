from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

Number = float


class CashFlowLike(Protocol):
    amount: Number
    date: date


@dataclass(frozen=True)
class MWRConvergence:
    iterations: int | None = None
    residual: float | None = None
    converged: bool | None = None
    algorithm: str | None = None
    root_count_detected: int | None = None
    residual_npv: float | None = None
    rate_lower_bound: Number | None = None
    rate_upper_bound: Number | None = None
    day_count_basis: str | None = None
    anchor_date: date | None = None
    normalized_flow_count: int | None = None
    gross_cash_flow_scale: float | None = None


@dataclass(frozen=True)
class MWRResult:
    mwr: float
    method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"]
    start_date: date
    end_date: date
    notes: list[str]
    mwr_annualized: float | None = None
    convergence: MWRConvergence | None = None
    status: Literal["CALCULATED", "FALLBACK_USED", "NOT_CALCULABLE", "NOT_APPLICABLE"] = "CALCULATED"
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    holding_period_return: Number | None = None
    is_annualized_primary: bool | None = None
    fallback_from: str | None = None
    fallback_reason: str | None = None
    is_approximation: bool | None = None
