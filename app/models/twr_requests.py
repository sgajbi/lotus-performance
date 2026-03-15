from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.requests import DailyInputData, PerformanceRequest, PerformanceRequestBase


class TWRInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class TWRStatelessInput(BaseModel):
    valuation_points: list[DailyInputData]


class TWRStatefulInput(BaseModel):
    consumer_system: str = Field(
        default="lotus-performance",
        description="Consumer system used for lotus-core stateful sourcing policy and lineage.",
        examples=["lotus-performance"],
    )


class TWRAnalyticsRequest(PerformanceRequestBase):
    input_mode: TWRInputMode = Field(
        default=TWRInputMode.STATELESS,
        description="Execution mode for TWR analytics.",
        examples=["stateful"],
    )
    stateless_input: TWRStatelessInput | None = Field(
        default=None,
        description="Stateless TWR input payload.",
    )
    stateful_input: TWRStatefulInput | None = Field(
        default=None,
        description="Stateful TWR input payload resolved through lotus-core integrations.",
    )
    valuation_points: list[DailyInputData] = Field(
        default_factory=list,
        description="Legacy stateless valuation input payload. Prefer stateless_input for new integrations.",
    )

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "TWRAnalyticsRequest":
        if self.input_mode == TWRInputMode.STATELESS:
            has_nested = self.stateless_input is not None
            has_legacy = len(self.valuation_points) > 0
            if has_nested and has_legacy:
                raise ValueError("Provide either stateless_input or valuation_points, not both, for stateless mode")
            if not has_nested and not has_legacy:
                raise ValueError("stateless_input or valuation_points is required when input_mode=stateless")
            if self.stateful_input is not None:
                raise ValueError("stateful_input must be null when input_mode=stateless")
        if self.input_mode == TWRInputMode.STATEFUL:
            if self.stateful_input is None:
                raise ValueError("stateful_input is required when input_mode=stateful")
            if self.stateless_input is not None:
                raise ValueError("stateless_input must be null when input_mode=stateful")
            if self.valuation_points:
                raise ValueError("valuation_points must be null when input_mode=stateful")
        return self

    def to_stateless_performance_request(
        self, *, valuation_points: list[DailyInputData] | None = None
    ) -> PerformanceRequest:
        if valuation_points is not None:
            resolved_points = valuation_points
        elif self.stateless_input is not None:
            resolved_points = self.stateless_input.valuation_points
        elif self.valuation_points:
            resolved_points = self.valuation_points
        else:
            raise ValueError("No stateless valuation_points are available to build a PerformanceRequest")

        payload = self.model_dump(
            exclude={
                "input_mode",
                "stateless_input",
                "stateful_input",
                "valuation_points",
            },
            mode="python",
        )
        payload["valuation_points"] = [point.model_dump(mode="python") for point in resolved_points]
        return PerformanceRequest.model_validate(payload)
