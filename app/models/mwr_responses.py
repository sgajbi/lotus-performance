# app/models/mwr_responses.py
from datetime import date as Date
from datetime import datetime as DateTime
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
    anchor_date: Optional[Date] = Field(default=None, description="Anchor date used for year-fraction calculation.")
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
    start_date: Date = Field(description="Inclusive start date for the evaluated window.", examples=["2026-01-01"])
    end_date: Date = Field(description="Inclusive end date for the evaluated window.", examples=["2026-03-31"])
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
    reporting_currency: Optional[str] = Field(
        default=None,
        description="Effective reporting currency for MWR market values and cash flows.",
    )
    currency_evidence: Optional["MWRCurrencyEvidence"] = Field(
        default=None,
        description=(
            "Currency context and source-component evidence for MWR. The block is additive to legacy "
            "cashflows_used and documents either stateful upstream pre-conversion without per-input FX "
            "metadata or stateless source-preconverted inputs with complete per-input FX provenance."
        ),
    )
    start_date: Date = Field(description="Inclusive start date for the evaluated window.", examples=["2026-01-01"])
    end_date: Date = Field(description="Inclusive end date for the evaluated window.", examples=["2026-03-31"])
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


class MWRCashFlowEvidenceComponent(BaseModel):
    component_type: Literal["source_cash_flow", "carry_forward_adjustment"] = Field(
        description="Source component type contributing to the MWR cash-flow amount."
    )
    amount: str = Field(description="Signed component amount in the MWR reporting currency.")
    currency: Optional[str] = Field(default=None, description="Currency context for the component amount.")
    cash_flow_type: Optional[str] = Field(default=None, description="Canonical source cash-flow type when available.")
    flow_scope: Optional[str] = Field(default=None, description="Canonical source flow scope when available.")
    source_classification: Optional[str] = Field(
        default=None,
        description="Underlying source classification that produced the cash-flow component.",
    )


class MWRCashFlowEvidence(BaseModel):
    date: Date = Field(description="Cash-flow date used by the MWR calculation.")
    amount: str = Field(description="Signed aggregate amount used by MWR.")
    currency: Optional[str] = Field(default=None, description="Currency context for the aggregate amount.")
    source_components: List[MWRCashFlowEvidenceComponent] = Field(
        default_factory=list,
        description="Source components aggregated into this MWR cash flow.",
    )
    source_amount: Optional[str] = Field(
        default=None, description="Cash-flow amount in source currency before upstream FX conversion."
    )
    source_currency: Optional[str] = Field(default=None, description="Source currency before upstream FX conversion.")
    reporting_amount: Optional[str] = Field(default=None, description="Cash-flow amount supplied to MWR.")
    reporting_currency: Optional[str] = Field(default=None, description="Reporting currency supplied to MWR.")
    fx_rate: Optional[str] = Field(default=None, description="FX rate applied before MWR execution.")
    fx_pair: Optional[str] = Field(default=None, description="FX pair used for upstream conversion.")
    fx_rate_date: Optional[Date] = Field(default=None, description="FX rate date used for upstream conversion.")
    fx_rate_source: Optional[str] = Field(default=None, description="Source of the FX rate.")
    fx_rate_version: Optional[str] = Field(default=None, description="Version or fixing identifier for the FX rate.")
    conversion_policy: Optional[str] = Field(default=None, description="Policy used for upstream FX conversion.")
    conversion_timestamp: Optional[DateTime] = Field(
        default=None, description="Timestamp when upstream conversion was performed."
    )
    conversion_fingerprint: Optional[str] = Field(
        default=None, description="Stable fingerprint of the conversion evidence."
    )


class MWRMarketValueEvidence(BaseModel):
    valuation_date: Optional[Date] = Field(
        default=None,
        description="Source valuation date for the market value used by MWR.",
    )
    amount: str = Field(description="Market value amount used by MWR.")
    currency: Optional[str] = Field(default=None, description="Currency context for the market value.")
    value_role: Literal["beginning_market_value", "ending_market_value"] = Field(
        description="Whether this value is the beginning or ending MWR market value."
    )
    source_product: Literal["PortfolioTimeseriesInput"] = Field(
        default="PortfolioTimeseriesInput",
        description="Upstream source data product used for stateful MWR sourcing.",
    )
    conversion_status: Literal[
        "upstream_preconverted",
        "source_preconverted_with_fx_evidence",
        "no_conversion_required",
    ] = Field(
        default="upstream_preconverted",
        description="Conversion posture for the source amount.",
    )
    source_amount: Optional[str] = Field(
        default=None, description="Market value amount in source currency before upstream FX conversion."
    )
    source_currency: Optional[str] = Field(default=None, description="Source currency before upstream FX conversion.")
    reporting_amount: Optional[str] = Field(default=None, description="Market value amount supplied to MWR.")
    reporting_currency: Optional[str] = Field(default=None, description="Reporting currency supplied to MWR.")
    fx_rate: Optional[str] = Field(default=None, description="FX rate applied before MWR execution.")
    fx_pair: Optional[str] = Field(default=None, description="FX pair used for upstream conversion.")
    fx_rate_date: Optional[Date] = Field(default=None, description="FX rate date used for upstream conversion.")
    fx_rate_source: Optional[str] = Field(default=None, description="Source of the FX rate.")
    fx_rate_version: Optional[str] = Field(default=None, description="Version or fixing identifier for the FX rate.")
    conversion_policy: Optional[str] = Field(default=None, description="Policy used for upstream FX conversion.")
    conversion_timestamp: Optional[DateTime] = Field(
        default=None, description="Timestamp when upstream conversion was performed."
    )
    conversion_fingerprint: Optional[str] = Field(
        default=None, description="Stable fingerprint of the conversion evidence."
    )


class MWRCurrencyEvidence(BaseModel):
    reporting_currency: Optional[str] = Field(
        default=None,
        description="Effective reporting currency used for the MWR market values and cash flows.",
    )
    portfolio_currency: Optional[str] = Field(default=None, description="Portfolio base currency reported by core.")
    currency_mode: Literal["SINGLE_REPORTING_CURRENCY", "SOURCE_PRECONVERTED_WITH_FX_EVIDENCE"] = Field(
        description=(
            "MWR calculation currency mode. Source-preconverted mode means the caller supplied complete "
            "per-input FX provenance while the engine still calculated one reporting-currency schedule."
        )
    )
    conversion_evidence_status: Literal[
        "upstream_preconverted_missing_per_input_fx_metadata",
        "complete_source_preconverted_fx_metadata",
        "not_required_single_currency_inputs",
    ] = Field(description="Whether per-input FX conversion evidence is complete for the MWR response.")
    conversion_evidence_reason_codes: List[str] = Field(
        default_factory=list,
        description="Machine-readable reason codes for conversion evidence completeness.",
    )
    market_values_used: List[MWRMarketValueEvidence] = Field(
        default_factory=list,
        description="Beginning and ending market values used by the MWR calculation.",
    )
    cashflow_evidence: List[MWRCashFlowEvidence] = Field(
        default_factory=list,
        description="MWR cash-flow schedule with source component evidence.",
    )
