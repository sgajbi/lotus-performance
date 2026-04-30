# app/models/attribution_responses.py
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.attribution_analytics_requests import AttributionInputMode
from app.models.responses import PerformanceCalculationSupportability
from common.enums import AttributionModel, LinkingMethod
from core.envelope import Audit, Diagnostics, Meta


class AttributionGroupResult(BaseModel):
    """The calculated attribution effects for a single group."""

    key: Dict[str, Any] = Field(
        description="Resolved grouping key for the attribution row.", examples=[{"asset_class": "equity"}]
    )
    portfolio_weight_avg: float = Field(
        description="Average portfolio weight for the group in percentage units. Example: 65.0 means 65%.",
        examples=[65.0],
    )
    benchmark_weight_avg: float = Field(
        description="Average benchmark weight for the group in percentage units. Example: 60.0 means 60%.",
        examples=[60.0],
    )
    portfolio_return: float = Field(
        description="Linked portfolio return for the group in percentage-point output units.",
        examples=[4.25],
    )
    benchmark_return: float = Field(
        description="Linked benchmark return for the group in percentage-point output units.",
        examples=[3.8],
    )
    allocation: float = Field(description="Allocation effect in percentage-point output units.", examples=[0.24])
    selection: float = Field(description="Selection effect in percentage-point output units.", examples=[0.15])
    interaction: float = Field(description="Interaction effect in percentage-point output units.", examples=[0.03])
    total_effect: float = Field(
        description="Total attribution effect in percentage-point output units.", examples=[0.42]
    )


class AttributionLevelTotals(BaseModel):
    """The summed attribution effects for an entire level."""

    allocation: float = Field(description="Level allocation total in percentage-point output units.", examples=[0.31])
    selection: float = Field(description="Level selection total in percentage-point output units.", examples=[0.22])
    interaction: float = Field(description="Level interaction total in percentage-point output units.", examples=[0.05])
    total_effect: float = Field(description="Level total effect in percentage-point output units.", examples=[0.58])


class AttributionLevelResult(BaseModel):
    """The complete set of results for a single dimension/level of the hierarchy."""

    dimension: str = Field(description="Grouping dimension used at this attribution level.", examples=["asset_class"])
    parent_key: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parent grouping key when this level is nested under another dimension.",
    )
    groups: List[AttributionGroupResult] = Field(description="Group-level attribution effects for this level.")
    totals: AttributionLevelTotals = Field(description="Summed attribution effects for the level.")
    allocation_total_pct: float = Field(
        description=(
            "Authoritative level allocation total in percentage-point output units. "
            "Use this field for UI footers and summary-only views instead of summing visible rows."
        ),
        examples=[0.31],
    )
    selection_total_pct: float = Field(
        description=(
            "Authoritative level selection total in percentage-point output units. "
            "Use this field for UI footers and summary-only views instead of summing visible rows."
        ),
        examples=[0.22],
    )
    interaction_total_pct: float = Field(
        description=(
            "Authoritative level interaction total in percentage-point output units. "
            "Use this field for UI footers and summary-only views instead of summing visible rows."
        ),
        examples=[0.05],
    )
    total_effect_pct: float = Field(
        description=(
            "Authoritative level total effect in percentage-point output units. "
            "This equals allocation_total_pct + selection_total_pct + interaction_total_pct after engine linking."
        ),
        examples=[0.58],
    )

    @model_validator(mode="before")
    @classmethod
    def populate_authoritative_total_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        totals = data.get("totals")
        if totals is None:
            return data
        if isinstance(totals, AttributionLevelTotals):
            totals_payload = totals.model_dump()
        elif isinstance(totals, dict):
            totals_payload = totals
        else:
            return data
        data.setdefault("allocation_total_pct", totals_payload.get("allocation"))
        data.setdefault("selection_total_pct", totals_payload.get("selection"))
        data.setdefault("interaction_total_pct", totals_payload.get("interaction"))
        data.setdefault("total_effect_pct", totals_payload.get("total_effect"))
        return data


class Reconciliation(BaseModel):
    """Validation block to confirm the sum of effects matches the active return."""

    total_active_return: float = Field(
        description="Active return for the period in percentage-point output units.",
        examples=[1.25],
    )
    sum_of_effects: float = Field(
        description="Summed attribution effects in percentage-point output units.",
        examples=[1.24],
    )
    residual: float = Field(
        description="Residual between active return and summed effects in percentage-point output units.",
        examples=[0.01],
    )


class CurrencyAttributionEffects(BaseModel):
    """The four decomposed effects from the Karnosky-Singer model."""

    local_allocation: float = Field(
        description="Local allocation effect in percentage-point output units.", examples=[0.08]
    )
    local_selection: float = Field(
        description="Local selection effect in percentage-point output units.", examples=[0.11]
    )
    currency_allocation: float = Field(
        description="Currency allocation effect in percentage-point output units.", examples=[0.03]
    )
    currency_selection: float = Field(
        description="Currency selection effect in percentage-point output units. This captures the interaction-style currency term.",
        examples=[0.02],
    )
    total_effect: float = Field(
        description="Total currency attribution effect in percentage-point output units.", examples=[0.24]
    )


class CurrencyAttributionResult(BaseModel):
    """The complete currency attribution breakdown for a single currency."""

    currency: str = Field(description="Currency bucket identifier.", examples=["USD"])
    weight_portfolio_avg: float = Field(
        description="Average portfolio currency weight in percentage units. Example: 65.0 means 65%.",
        examples=[65.0],
    )
    weight_benchmark_avg: float = Field(
        description="Average benchmark currency weight in percentage units. Example: 60.0 means 60%.",
        examples=[60.0],
    )
    effects: CurrencyAttributionEffects = Field(description="Currency attribution effect breakdown.")


class SinglePeriodAttributionResult(BaseModel):
    """Contains the full set of attribution results for a single, resolved period."""

    levels: List[AttributionLevelResult] = Field(description="Hierarchical attribution levels for the period.")
    reconciliation: Reconciliation = Field(
        description="Reconciliation between active return and summed attribution effects."
    )
    currency_attribution: Optional[List[CurrencyAttributionResult]] = Field(
        default=None,
        description="Optional currency attribution breakdown in percentage-point output units.",
    )


class AttributionBenchmarkContext(BaseModel):
    """Resolved benchmark context for attribution requests that sourced a benchmark."""

    benchmark_id: str = Field(description="Resolved benchmark identifier.", examples=["BMK_GLOBAL_60_40"])
    return_source: str = Field(description="Resolved benchmark return source.", examples=["calculated"])


class AttributionResponse(BaseModel):
    """Response model for the Attribution engine."""

    calculation_id: UUID = Field(description="Stable calculation handle for this attribution request.")
    portfolio_id: str = Field(description="Portfolio identifier.", examples=["PORTFOLIO_001"])
    input_mode: AttributionInputMode = Field(
        default=AttributionInputMode.STATELESS, description="Resolved attribution input mode."
    )
    model: AttributionModel = Field(
        description="Attribution model used for the response.", examples=["brinson_fachler"]
    )
    linking: LinkingMethod = Field(
        description="Linking method used to aggregate attribution effects.", examples=["carino"]
    )
    results_by_period: Dict[str, SinglePeriodAttributionResult] = Field(
        description="Per-period attribution outputs. Attribution effects and reconciliation values are emitted in percentage-point output units."
    )
    benchmark_context: Optional[AttributionBenchmarkContext] = Field(
        default=None,
        description="Resolved benchmark context when the request sourced a benchmark.",
    )
    calculation_supportability: PerformanceCalculationSupportability = Field(
        description=(
            "Bounded supportability state for completed attribution output, including source freshness and "
            "resolved input and benchmark counts used by front-office degraded-state handling."
        )
    )

    meta: Meta = Field(description="Shared metadata envelope for the calculation.")
    diagnostics: Optional[Diagnostics] = Field(default=None, description="Diagnostic details for the calculation.")
    audit: Optional[Audit] = Field(default=None, description="Audit details for the calculation.")


class AttributionAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(
        description="Stable calculation handle for the accepted attribution request.",
        examples=["209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3"],
    )
    poll_path: str = Field(
        description="Execution-status endpoint to poll while the attribution request is running.",
        examples=["/performance/executions/209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3"],
    )
    result_path: str = Field(
        description="Endpoint that returns the completed attribution response once execution is complete.",
        examples=["/performance/attribution/results/209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3"],
    )
