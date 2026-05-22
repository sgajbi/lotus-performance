from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MandatePerformanceHealthState = Literal["ready", "attention", "unavailable"]


class MandatePerformanceHealthContextRequest(BaseModel):
    portfolio_id: str = Field(
        description="Portfolio identifier for the mandate performance health context.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    as_of_date: date = Field(
        description="As-of date used for the source-owned performance health context.",
        examples=["2026-02-27"],
    )
    period_name: str = Field(
        description="Resolved performance period label evaluated by the source product.",
        examples=["YTD"],
    )
    portfolio_period_return: Decimal | None = Field(
        default=None,
        description="Portfolio period return in percentage-point output units.",
        examples=["2.45"],
    )
    benchmark_period_return: Decimal | None = Field(
        default=None,
        description="Benchmark period return in percentage-point output units.",
        examples=["2.80"],
    )
    active_return_attention_threshold: Decimal = Field(
        default=Decimal("-0.50"),
        description=(
            "Active-return attention threshold in percentage points. Negative values indicate "
            "underperformance tolerance; -0.50 means attention when portfolio underperforms by "
            "more than 50 bps for the evaluated period."
        ),
        examples=["-0.50"],
    )

    model_config = ConfigDict(extra="forbid")


class MandatePerformanceHealthSourceMetric(BaseModel):
    metric_name: Literal["ACTIVE_RETURN"] = Field(
        default="ACTIVE_RETURN",
        description="Source-owned performance metric used for mandate health posture.",
        examples=["ACTIVE_RETURN"],
    )
    portfolio_period_return: Decimal | None = Field(
        default=None,
        description="Portfolio period return in percentage-point output units.",
        examples=["2.45"],
    )
    benchmark_period_return: Decimal | None = Field(
        default=None,
        description="Benchmark period return in percentage-point output units.",
        examples=["2.80"],
    )
    active_return: Decimal | None = Field(
        default=None,
        description="Portfolio return minus benchmark return in percentage points.",
        examples=["-0.35"],
    )


class MandatePerformanceHealthMethodologyPosture(BaseModel):
    source_product_name: Literal["MandatePerformanceHealthContext"] = Field(
        default="MandatePerformanceHealthContext",
        description="Source-owned mandate health performance product name.",
        examples=["MandatePerformanceHealthContext"],
    )
    source_product_version: Literal["v1"] = Field(
        default="v1",
        description="Source-owned mandate health performance product version.",
        examples=["v1"],
    )
    source_service: Literal["lotus-performance"] = Field(
        default="lotus-performance",
        description="Authoritative source service for this performance context.",
        examples=["lotus-performance"],
    )
    source_metrics_product: Literal["TimeWeightedReturnAnalytics:v1"] = Field(
        default="TimeWeightedReturnAnalytics:v1",
        description="Underlying source-owned performance product family used for this context.",
        examples=["TimeWeightedReturnAnalytics:v1"],
    )
    methodology_version: Literal["twr.v1"] = Field(
        default="twr.v1",
        description="Source methodology family used for period and active-return interpretation.",
        examples=["twr.v1"],
    )
    source_route: Literal["/performance/twr"] = Field(
        default="/performance/twr",
        description="Underlying source route for full source-owned TWR calculation.",
        examples=["/performance/twr"],
    )


class MandatePerformanceBenchmarkContext(BaseModel):
    benchmark_available: bool = Field(
        description="Whether benchmark period-return evidence was available for active-return evaluation.",
        examples=[True],
    )
    benchmark_return_source: Literal["request_supplied_period_return"] = Field(
        default="request_supplied_period_return",
        description="Bounded benchmark-return source posture for this stateless context product.",
        examples=["request_supplied_period_return"],
    )


class MandatePerformanceHealthContextResponse(BaseModel):
    product_name: Literal["MandatePerformanceHealthContext"] = Field(
        default="MandatePerformanceHealthContext",
        description="Source-owned product emitted by lotus-performance for mandate health performance context.",
        examples=["MandatePerformanceHealthContext"],
    )
    product_version: Literal["v1"] = Field(
        default="v1",
        description="Product contract version.",
        examples=["v1"],
    )
    portfolio_id: str = Field(
        description="Portfolio identifier evaluated by the source product.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    as_of_date: date = Field(
        description="As-of date for the source-owned mandate performance health context.",
        examples=["2026-02-27"],
    )
    period_name: str = Field(
        description="Resolved period key evaluated by the source product.",
        examples=["YTD"],
    )
    health_state: MandatePerformanceHealthState = Field(
        description="Bounded performance health posture derived from source-owned active return.",
        examples=["ready"],
    )
    threshold_breached: bool | None = Field(
        default=None,
        description="Whether active return breached the supplied underperformance threshold.",
        examples=[False],
    )
    active_return_attention_threshold: Decimal = Field(
        description="Applied active-return threshold in percentage points.",
        examples=["-0.50"],
    )
    source_metric: MandatePerformanceHealthSourceMetric = Field(
        description="Bounded source metric evidence used to derive health state.",
        json_schema_extra={
            "example": {
                "metric_name": "ACTIVE_RETURN",
                "portfolio_period_return": "2.45",
                "benchmark_period_return": "2.80",
                "active_return": "-0.35",
            }
        },
    )
    methodology_posture: MandatePerformanceHealthMethodologyPosture = Field(
        default_factory=MandatePerformanceHealthMethodologyPosture,
        description="Source ownership and methodology posture for consumers.",
        json_schema_extra={
            "example": {
                "source_product_name": "MandatePerformanceHealthContext",
                "source_product_version": "v1",
                "source_service": "lotus-performance",
                "source_metrics_product": "TimeWeightedReturnAnalytics:v1",
                "methodology_version": "twr.v1",
                "source_route": "/performance/twr",
            }
        },
    )
    source_services: list[Literal["lotus-performance"]] = Field(
        default_factory=lambda: ["lotus-performance"],
        description="Ordered source services that materially contribute to this product payload.",
        examples=[["lotus-performance"]],
    )
    benchmark_context: MandatePerformanceBenchmarkContext = Field(
        description="Benchmark evidence posture for the active-return evaluation.",
        json_schema_extra={
            "example": {
                "benchmark_available": True,
                "benchmark_return_source": "request_supplied_period_return",
            }
        },
    )
    request_fingerprint: str = Field(
        description="Fingerprint of the mandate performance health context request.",
        examples=["sha256:..."],
    )
    reason_codes: list[str] = Field(
        description="Bounded reason codes safe for downstream supportability and audit use.",
        examples=[
            [
                "MANDATE_PERFORMANCE_HEALTH_ACTIVE_RETURN_SOURCE_READY",
                "PERFORMANCE_METHODOLOGY_SOURCE_OWNED",
            ]
        ],
    )
