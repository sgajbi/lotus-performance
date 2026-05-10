from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.attribution_requests import (
    AttributionPortfolioData,
    AttributionRequest,
    BenchmarkGroup,
    InstrumentData,
    PortfolioGroup,
)
from app.models.stateful_position_inputs import StatefulDimensionName, StatefulPositionFilters


class AttributionInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class AttributionStatelessInput(BaseModel):
    portfolio_data: AttributionPortfolioData | None = Field(
        default=None,
        description="Total portfolio series for position-level stateless attribution.",
    )
    instruments_data: list[InstrumentData] | None = Field(
        default=None,
        description="Position or instrument series for by_instrument stateless attribution.",
    )
    portfolio_groups_data: list[PortfolioGroup] | None = Field(
        default=None,
        description="Pre-aggregated portfolio group series for by_group stateless attribution.",
    )
    benchmark_groups_data: list[BenchmarkGroup] = Field(
        description="Benchmark group observations aligned to the requested attribution window.",
    )


class AttributionStatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_basis: str = Field(
        default="NET",
        description="Metric basis applied when building stateful attribution portfolio inputs.",
        examples=["NET"],
    )
    benchmark_id: str | None = Field(
        default=None,
        description="Optional benchmark identifier override. When omitted, lotus-core benchmark assignment is used.",
        examples=["BMK_PRIVATE_BANKING_BALANCED"],
    )
    dimensions: list[StatefulDimensionName] = Field(
        default_factory=list,
        description="Dimension labels requested from lotus-core position-timeseries for attribution metadata.",
        examples=[["asset_class", "sector"]],
    )
    include_cash_flows: bool = Field(
        default=True,
        description="Whether stateful position sourcing should request canonical cash flow rows.",
        examples=[True],
    )
    filters: StatefulPositionFilters = Field(
        default_factory=StatefulPositionFilters,
        description="Optional inclusion filters for stateful position sourcing.",
    )


class AttributionAnalyticsRequest(AttributionRequest):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "report_start_date": "2026-01-01",
                    "report_end_date": "2026-03-31",
                    "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                    "mode": "by_instrument",
                    "frequency": "daily",
                    "group_by": ["asset_class", "sector"],
                    "model": "BF",
                    "linking": "carino",
                    "input_mode": "stateful",
                    "stateful_input": {
                        "metric_basis": "NET",
                        "dimensions": ["asset_class", "sector"],
                        "include_cash_flows": True,
                    },
                }
            ]
        },
    )

    portfolio_data: AttributionPortfolioData | None = Field(
        default=None,
        description="Legacy stateless portfolio attribution payload. Prefer stateless_input for new integrations.",
    )
    instruments_data: list[InstrumentData] | None = Field(
        default=None,
        description="Legacy stateless instrument attribution payload. Prefer stateless_input for new integrations.",
    )
    portfolio_groups_data: list[PortfolioGroup] | None = Field(
        default=None,
        description="Legacy stateless grouped portfolio attribution payload. Prefer stateless_input for new integrations.",
    )
    benchmark_groups_data: list[BenchmarkGroup] = Field(
        default_factory=list,
        description="Legacy stateless benchmark attribution payload. Prefer stateless_input for new integrations.",
    )
    input_mode: AttributionInputMode = Field(
        default=AttributionInputMode.STATELESS,
        description="Execution mode for attribution analytics.",
        examples=["stateful"],
    )
    stateless_input: AttributionStatelessInput | None = Field(
        default=None,
        description="Stateless attribution input payload.",
        examples=[
            {
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [{"perf_date": "2026-03-31", "begin_mv": 1000000, "end_mv": 1012500}],
                },
                "instruments_data": [
                    {
                        "instrument_id": "SEC_PRIVATE_BANKING_EQ_01",
                        "meta": {"asset_class": "equity", "sector": "technology"},
                        "valuation_points": [{"perf_date": "2026-03-31", "begin_mv": 600000, "end_mv": 610500}],
                    }
                ],
                "benchmark_groups_data": [
                    {
                        "key": {"asset_class": "equity", "sector": "technology"},
                        "observations": [{"date": "2026-03-31", "weight_bop": 0.6, "return_base": 0.01}],
                    }
                ],
            }
        ],
    )
    stateful_input: AttributionStatefulInput | None = Field(
        default=None,
        description="Stateful attribution input payload resolved through lotus-core integrations.",
        examples=[{"metric_basis": "NET", "dimensions": ["asset_class", "sector"], "include_cash_flows": True}],
    )

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "AttributionAnalyticsRequest":
        has_legacy_by_instrument = self.portfolio_data is not None or self.instruments_data is not None
        has_partial_legacy_by_instrument = (self.portfolio_data is None) != (self.instruments_data is None)
        has_legacy_by_group = self.portfolio_groups_data is not None
        has_legacy_benchmark = len(self.benchmark_groups_data) > 0
        has_legacy_stateless = has_legacy_by_instrument or has_legacy_by_group or has_legacy_benchmark

        if has_partial_legacy_by_instrument:
            raise ValueError(
                "portfolio_data and instruments_data must be provided together for legacy by_instrument mode"
            )

        if self.input_mode == AttributionInputMode.STATELESS:
            if self.stateful_input is not None:
                raise ValueError("stateful_input must be null when input_mode=stateless")
            if self.stateless_input is not None and has_legacy_stateless:
                raise ValueError(
                    "Provide either stateless_input or legacy attribution input fields, not both, for stateless mode"
                )
            if self.stateless_input is None and not has_legacy_stateless:
                raise ValueError(
                    "stateless_input or legacy attribution input fields are required when input_mode=stateless"
                )

        if self.input_mode == AttributionInputMode.STATEFUL:
            if self.stateful_input is None:
                raise ValueError("stateful_input is required when input_mode=stateful")
            if self.stateless_input is not None:
                raise ValueError("stateless_input must be null when input_mode=stateful")
            if has_legacy_stateless:
                raise ValueError("legacy attribution input fields must be null when input_mode=stateful")
        return self

    def to_stateless_attribution_request(
        self,
        *,
        portfolio_data: AttributionPortfolioData | None = None,
        instruments_data: list[InstrumentData] | None = None,
        portfolio_groups_data: list[PortfolioGroup] | None = None,
        benchmark_groups_data: list[BenchmarkGroup] | None = None,
    ) -> AttributionRequest:
        resolved_benchmark_groups: list[BenchmarkGroup] | None
        resolved_portfolio_data: AttributionPortfolioData | None
        resolved_instruments_data: list[InstrumentData] | None
        resolved_portfolio_groups: list[PortfolioGroup] | None
        if benchmark_groups_data is not None:
            resolved_benchmark_groups = benchmark_groups_data
            resolved_portfolio_data = portfolio_data
            resolved_instruments_data = instruments_data
            resolved_portfolio_groups = portfolio_groups_data
        elif self.stateless_input is not None:
            resolved_benchmark_groups = self.stateless_input.benchmark_groups_data
            resolved_portfolio_data = self.stateless_input.portfolio_data
            resolved_instruments_data = self.stateless_input.instruments_data
            resolved_portfolio_groups = self.stateless_input.portfolio_groups_data
        else:
            resolved_benchmark_groups = self.benchmark_groups_data
            resolved_portfolio_data = self.portfolio_data
            resolved_instruments_data = self.instruments_data
            resolved_portfolio_groups = self.portfolio_groups_data
        if not resolved_benchmark_groups:
            raise ValueError("No stateless benchmark_groups_data are available to build an AttributionRequest")

        payload = self.model_dump(
            exclude={
                "input_mode",
                "stateless_input",
                "stateful_input",
                "portfolio_data",
                "instruments_data",
                "portfolio_groups_data",
                "benchmark_groups_data",
            },
            mode="python",
        )
        payload["portfolio_data"] = (
            resolved_portfolio_data.model_dump(mode="python") if resolved_portfolio_data is not None else None
        )
        payload["instruments_data"] = (
            [instrument.model_dump(mode="python") for instrument in resolved_instruments_data]
            if resolved_instruments_data is not None
            else None
        )
        payload["portfolio_groups_data"] = (
            [group.model_dump(mode="python") for group in resolved_portfolio_groups]
            if resolved_portfolio_groups is not None
            else None
        )
        payload["benchmark_groups_data"] = [group.model_dump(mode="python") for group in resolved_benchmark_groups]
        return AttributionRequest.model_validate(payload)
