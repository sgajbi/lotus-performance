from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

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


@dataclass(frozen=True)
class _AttributionInputShape:
    has_legacy_by_instrument: bool
    has_partial_legacy_by_instrument: bool
    has_legacy_by_group: bool
    has_legacy_benchmark: bool

    @property
    def has_legacy_stateless(self) -> bool:
        return self.has_legacy_by_instrument or self.has_legacy_by_group or self.has_legacy_benchmark


@dataclass(frozen=True)
class _ResolvedAttributionStatelessInput:
    portfolio_data: AttributionPortfolioData | None
    instruments_data: list[InstrumentData] | None
    portfolio_groups_data: list[PortfolioGroup] | None
    benchmark_groups_data: list[BenchmarkGroup] | None


class AttributionAnalyticsRequest(AttributionRequest):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "report_start_date": "2026-01-01",
                    "report_end_date": "2026-03-31",
                    "analyses": [{"period": "SI", "frequencies": ["daily"]}],
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
        input_shape = _attribution_input_shape(self)
        if input_shape.has_partial_legacy_by_instrument:
            raise ValueError(
                "portfolio_data and instruments_data must be provided together for legacy by_instrument mode"
            )

        if self.input_mode == AttributionInputMode.STATELESS:
            _validate_stateless_input_shape(self, input_shape)

        if self.input_mode == AttributionInputMode.STATEFUL:
            _validate_stateful_input_shape(self, input_shape)
        return self

    def to_stateless_attribution_request(
        self,
        *,
        portfolio_data: AttributionPortfolioData | None = None,
        instruments_data: list[InstrumentData] | None = None,
        portfolio_groups_data: list[PortfolioGroup] | None = None,
        benchmark_groups_data: list[BenchmarkGroup] | None = None,
    ) -> AttributionRequest:
        resolved_input = _resolve_attribution_stateless_input(
            request=self,
            portfolio_data=portfolio_data,
            instruments_data=instruments_data,
            portfolio_groups_data=portfolio_groups_data,
            benchmark_groups_data=benchmark_groups_data,
        )
        if not resolved_input.benchmark_groups_data:
            raise ValueError("No stateless benchmark_groups_data are available to build an AttributionRequest")

        payload = _attribution_request_payload(request=self, resolved_input=resolved_input)
        return AttributionRequest.model_validate(payload)


def _attribution_request_payload(
    *,
    request: AttributionAnalyticsRequest,
    resolved_input: _ResolvedAttributionStatelessInput,
) -> dict[str, object]:
    payload = request.model_dump(
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
    payload["portfolio_data"] = _model_payload_or_none(resolved_input.portfolio_data)
    payload["instruments_data"] = _model_list_payload_or_none(resolved_input.instruments_data)
    payload["portfolio_groups_data"] = _model_list_payload_or_none(resolved_input.portfolio_groups_data)
    payload["benchmark_groups_data"] = _model_list_payload_or_none(resolved_input.benchmark_groups_data) or []
    return payload


def _model_payload_or_none(model: BaseModel | None) -> dict[str, Any] | None:
    return model.model_dump(mode="python") if model is not None else None


def _model_list_payload_or_none(models: Sequence[BaseModel] | None) -> list[dict[str, Any]] | None:
    if models is None:
        return None
    return [model.model_dump(mode="python") for model in models]


def _resolve_attribution_stateless_input(
    *,
    request: AttributionAnalyticsRequest,
    portfolio_data: AttributionPortfolioData | None = None,
    instruments_data: list[InstrumentData] | None = None,
    portfolio_groups_data: list[PortfolioGroup] | None = None,
    benchmark_groups_data: list[BenchmarkGroup] | None = None,
) -> _ResolvedAttributionStatelessInput:
    if benchmark_groups_data is not None:
        return _ResolvedAttributionStatelessInput(
            portfolio_data=portfolio_data,
            instruments_data=instruments_data,
            portfolio_groups_data=portfolio_groups_data,
            benchmark_groups_data=benchmark_groups_data,
        )
    if request.stateless_input is not None:
        return _ResolvedAttributionStatelessInput(
            portfolio_data=request.stateless_input.portfolio_data,
            instruments_data=request.stateless_input.instruments_data,
            portfolio_groups_data=request.stateless_input.portfolio_groups_data,
            benchmark_groups_data=request.stateless_input.benchmark_groups_data,
        )
    return _ResolvedAttributionStatelessInput(
        portfolio_data=request.portfolio_data,
        instruments_data=request.instruments_data,
        portfolio_groups_data=request.portfolio_groups_data,
        benchmark_groups_data=request.benchmark_groups_data,
    )


def _attribution_input_shape(request: AttributionAnalyticsRequest) -> _AttributionInputShape:
    has_legacy_by_instrument = request.portfolio_data is not None or request.instruments_data is not None
    return _AttributionInputShape(
        has_legacy_by_instrument=has_legacy_by_instrument,
        has_partial_legacy_by_instrument=(request.portfolio_data is None) != (request.instruments_data is None),
        has_legacy_by_group=request.portfolio_groups_data is not None,
        has_legacy_benchmark=len(request.benchmark_groups_data) > 0,
    )


def _validate_stateless_input_shape(
    request: AttributionAnalyticsRequest,
    input_shape: _AttributionInputShape,
) -> None:
    if request.stateful_input is not None:
        raise ValueError("stateful_input must be null when input_mode=stateless")
    envelope_issue = _stateless_input_envelope_issue(
        has_nested=request.stateless_input is not None,
        has_legacy=input_shape.has_legacy_stateless,
    )
    if envelope_issue is not None:
        raise ValueError(envelope_issue)


def _stateless_input_envelope_issue(*, has_nested: bool, has_legacy: bool) -> str | None:
    if _has_exactly_one_stateless_input_shape(has_nested=has_nested, has_legacy=has_legacy):
        return None
    if has_nested:
        return "Provide either stateless_input or legacy attribution input fields, not both, for stateless mode"
    return "stateless_input or legacy attribution input fields are required when input_mode=stateless"


def _has_exactly_one_stateless_input_shape(*, has_nested: bool, has_legacy: bool) -> bool:
    return has_nested != has_legacy


def _validate_stateful_input_shape(
    request: AttributionAnalyticsRequest,
    input_shape: _AttributionInputShape,
) -> None:
    if request.stateful_input is None:
        raise ValueError("stateful_input is required when input_mode=stateful")
    if request.stateless_input is not None:
        raise ValueError("stateless_input must be null when input_mode=stateful")
    if input_shape.has_legacy_stateless:
        raise ValueError("legacy attribution input fields must be null when input_mode=stateful")
