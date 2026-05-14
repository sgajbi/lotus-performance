# app/models/attribution_responses.py
from typing import Any, Dict, List, Literal, Optional
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
    residual_materiality: "AttributionResidualMateriality" = Field(
        description=(
            "Materiality classification for the residual in percentage-point output units. "
            "Operations should use this block to distinguish immaterial rounding from reviewable breaks."
        )
    )


AttributionPeriodStatus = Literal["valid", "warning", "partial", "unavailable", "invalid"]
AttributionReasonSeverity = Literal["info", "warning", "error"]
AttributionReasonCode = Literal[
    "off_benchmark_exposure",
    "benchmark_only_exposure",
    "unclassified_segment",
    "missing_benchmark_data",
    "missing_benchmark_return",
    "negative_weight",
    "zero_portfolio_exposure",
    "currency_attribution_unavailable",
    "linking_scaling_skipped",
    "linking_invalid_return_chain",
    "material_residual",
    "residual_watch",
]
AttributionResidualClassification = Literal["immaterial", "watch", "material"]
AttributionResidualTreatment = Literal["no_action", "review", "investigate"]
AttributionCurrencyEvidenceStatus = Literal["not_requested", "complete", "unavailable"]
AttributionLinkingEvidenceStatus = Literal["not_requested", "linked", "scaling_skipped", "invalid_return_chain"]


class AttributionResidualMateriality(BaseModel):
    """Residual materiality policy and classification for a resolved attribution period."""

    classification: AttributionResidualClassification = Field(
        description="Materiality classification applied to the residual.", examples=["immaterial"]
    )
    treatment: AttributionResidualTreatment = Field(
        description="Operational treatment for the residual classification.", examples=["no_action"]
    )
    absolute_residual: float = Field(
        description="Absolute residual in percentage-point output units.", examples=[0.00002]
    )
    warning_threshold: float = Field(
        description="Residual threshold, in percentage points, at which operations should review the result.",
        examples=[0.001],
    )
    material_threshold: float = Field(
        description="Residual threshold, in percentage points, at which the result is treated as material.",
        examples=[0.01],
    )


class AttributionReason(BaseModel):
    """Controlled attribution status reason emitted for operations and downstream consumers."""

    code: AttributionReasonCode = Field(
        description="Controlled attribution reason code.", examples=["off_benchmark_exposure"]
    )
    severity: AttributionReasonSeverity = Field(
        description="Bounded reason severity for support workflows.", examples=["warning"]
    )
    message: str = Field(
        description="Client-safe support message describing the reason without exposing raw payload values.",
        examples=["Portfolio holds one or more groups that are absent from the benchmark."],
    )
    affected_group_count: int = Field(
        default=0,
        ge=0,
        description="Count of affected attribution groups. Identifiers are intentionally not emitted.",
        examples=[2],
    )


class AttributionSupportabilityEvidence(BaseModel):
    """Support-safe evidence summary for a resolved attribution period."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "portfolio_only_group_count": 1,
                    "benchmark_only_group_count": 0,
                    "unclassified_group_count": 0,
                    "missing_benchmark_return_count": 0,
                    "negative_weight_count": 0,
                    "zero_portfolio_exposure_count": 0,
                    "currency_attribution_status": "not_requested",
                    "linking_status": "linked",
                }
            ]
        }
    )

    portfolio_only_group_count: int = Field(
        default=0,
        ge=0,
        description="Count of groups with portfolio exposure and no benchmark exposure.",
        examples=[1],
    )
    benchmark_only_group_count: int = Field(
        default=0,
        ge=0,
        description="Count of groups with benchmark exposure and no portfolio exposure.",
        examples=[1],
    )
    unclassified_group_count: int = Field(
        default=0,
        ge=0,
        description="Count of groups resolved to the governed unclassified bucket.",
        examples=[1],
    )
    missing_benchmark_return_count: int = Field(
        default=0,
        ge=0,
        description="Count of benchmark-exposed groups whose benchmark return is missing or unavailable.",
        examples=[1],
    )
    negative_weight_count: int = Field(
        default=0,
        ge=0,
        description="Count of rows with negative portfolio or benchmark weights.",
        examples=[0],
    )
    zero_portfolio_exposure_count: int = Field(
        default=0,
        ge=0,
        description="Count of rows where portfolio and benchmark exposure are both zero after alignment.",
        examples=[0],
    )
    currency_attribution_status: AttributionCurrencyEvidenceStatus = Field(
        description="Currency attribution evidence status for the period.", examples=["not_requested"]
    )
    linking_status: AttributionLinkingEvidenceStatus = Field(
        description="Linking evidence status for the period.", examples=["linked"]
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


class CurrencyAttributionTotals(BaseModel):
    """Portfolio-level total of the currency attribution breakdown."""

    local_allocation: float = Field(
        description="Portfolio-level local allocation effect in percentage-point output units.",
        examples=[0.08],
    )
    local_selection: float = Field(
        description="Portfolio-level local selection effect in percentage-point output units.",
        examples=[0.11],
    )
    currency_allocation: float = Field(
        description="Portfolio-level currency allocation effect in percentage-point output units.",
        examples=[0.03],
    )
    currency_selection: float = Field(
        description="Portfolio-level currency selection effect in percentage-point output units.",
        examples=[0.02],
    )
    total_effect: float = Field(
        description=(
            "Portfolio-level total currency attribution effect in percentage-point output units. "
            "This equals the sum of local allocation, local selection, currency allocation, and "
            "currency selection across all emitted currency buckets."
        ),
        examples=[0.24],
    )
    currency_count: int = Field(
        ge=0,
        description="Number of currency buckets included in the portfolio-level total.",
        examples=[2],
    )


class SinglePeriodAttributionResult(BaseModel):
    """Contains the full set of attribution results for a single, resolved period."""

    status: AttributionPeriodStatus = Field(
        default="valid",
        description="Controlled attribution period status for downstream degraded-state handling.",
        examples=["valid"],
    )
    reason_codes: List[AttributionReasonCode] = Field(
        default_factory=list,
        description="Controlled reason-code list for the attribution period.",
        examples=[["off_benchmark_exposure"]],
    )
    reasons: List[AttributionReason] = Field(
        default_factory=list,
        description="Detailed controlled reasons for the attribution period.",
        examples=[
            [
                {
                    "code": "off_benchmark_exposure",
                    "severity": "warning",
                    "message": "Portfolio holds one or more groups that are absent from the benchmark.",
                    "affected_group_count": 1,
                }
            ]
        ],
    )
    supportability_evidence: AttributionSupportabilityEvidence = Field(
        description="Support-safe attribution evidence summary for this period.",
        examples=[
            {
                "portfolio_only_group_count": 1,
                "benchmark_only_group_count": 0,
                "unclassified_group_count": 0,
                "missing_benchmark_return_count": 0,
                "negative_weight_count": 0,
                "zero_portfolio_exposure_count": 0,
                "currency_attribution_status": "not_requested",
                "linking_status": "linked",
            }
        ],
    )
    levels: List[AttributionLevelResult] = Field(description="Hierarchical attribution levels for the period.")
    reconciliation: Reconciliation = Field(
        description="Reconciliation between active return and summed attribution effects."
    )
    currency_attribution: Optional[List[CurrencyAttributionResult]] = Field(
        default=None,
        description="Optional currency attribution breakdown in percentage-point output units.",
    )
    currency_attribution_totals: Optional[CurrencyAttributionTotals] = Field(
        default=None,
        description=(
            "Optional portfolio-level currency attribution total in percentage-point output "
            "units. Downstream consumers should use this field instead of summing displayed "
            "currency rows."
        ),
    )


class AttributionBenchmarkContext(BaseModel):
    """Resolved benchmark context for attribution requests that sourced a benchmark."""

    benchmark_id: str = Field(description="Resolved benchmark identifier.", examples=["BMK_GLOBAL_60_40"])
    return_source: str = Field(description="Resolved benchmark return source.", examples=["calculated"])


class AttributionResponse(BaseModel):
    """Response model for the Attribution engine."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "calculation_id": "209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3",
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "input_mode": "stateful",
                    "model": "brinson_fachler",
                    "linking": "carino",
                    "results_by_period": {
                        "ITD": {
                            "status": "partial",
                            "reason_codes": ["off_benchmark_exposure"],
                            "reasons": [
                                {
                                    "code": "off_benchmark_exposure",
                                    "severity": "warning",
                                    "message": (
                                        "Portfolio holds one or more groups that are absent from the benchmark."
                                    ),
                                    "affected_group_count": 1,
                                }
                            ],
                            "supportability_evidence": {
                                "portfolio_only_group_count": 1,
                                "benchmark_only_group_count": 0,
                                "unclassified_group_count": 0,
                                "missing_benchmark_return_count": 0,
                                "negative_weight_count": 0,
                                "zero_portfolio_exposure_count": 0,
                                "currency_attribution_status": "not_requested",
                                "linking_status": "linked",
                            },
                            "levels": [
                                {
                                    "dimension": "asset_class",
                                    "parent_key": None,
                                    "groups": [
                                        {
                                            "key": {"asset_class": "equity"},
                                            "portfolio_weight_avg": 65.0,
                                            "benchmark_weight_avg": 60.0,
                                            "portfolio_return": 4.25,
                                            "benchmark_return": 3.8,
                                            "allocation": 0.24,
                                            "selection": 0.15,
                                            "interaction": 0.03,
                                            "total_effect": 0.42,
                                        }
                                    ],
                                    "totals": {
                                        "allocation": 0.24,
                                        "selection": 0.15,
                                        "interaction": 0.03,
                                        "total_effect": 0.42,
                                    },
                                    "allocation_total_pct": 0.24,
                                    "selection_total_pct": 0.15,
                                    "interaction_total_pct": 0.03,
                                    "total_effect_pct": 0.42,
                                }
                            ],
                            "reconciliation": {
                                "total_active_return": 0.42,
                                "sum_of_effects": 0.42,
                                "residual": 0.0,
                                "residual_materiality": {
                                    "classification": "immaterial",
                                    "treatment": "no_action",
                                    "absolute_residual": 0.0,
                                    "warning_threshold": 0.001,
                                    "material_threshold": 0.01,
                                },
                            },
                        }
                    },
                    "benchmark_context": {
                        "benchmark_id": "BMK_PRIVATE_BANKING_BALANCED",
                        "return_source": "calculated",
                    },
                    "calculation_supportability": {
                        "state": "ready",
                        "reason": "calculation_complete",
                        "freshness_bucket": "current",
                        "input_row_count": 4,
                        "resolved_period_count": 1,
                        "benchmark_row_count": 2,
                        "source_quality_evidence": None,
                        "metric_labels": [
                            "operation",
                            "supportability_state",
                            "reason",
                            "freshness_bucket",
                        ],
                    },
                    "meta": {"schema_version": "1.0.0"},
                    "diagnostics": None,
                    "audit": None,
                }
            ]
        }
    )

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
