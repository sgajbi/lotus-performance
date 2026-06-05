from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.contribution_requests import (
    ContributionRequest,
    ContributionRequestBase,
    PortfolioData,
    PositionData,
)
from app.models.stateful_position_inputs import StatefulDimensionName, StatefulPositionFilters


class ContributionInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class ContributionStatelessInput(BaseModel):
    portfolio_data: PortfolioData
    positions_data: list[PositionData]


class ContributionStatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_basis: Literal["NET", "GROSS"] = Field(
        default="NET",
        description="Metric basis applied when building stateful contribution portfolio inputs.",
        examples=["NET"],
    )
    dimensions: list[StatefulDimensionName] = Field(
        default_factory=list,
        description="Dimension labels requested from lotus-core position-timeseries for position metadata.",
    )
    include_cash_flows: bool = Field(
        default=True,
        description="Whether stateful position sourcing should request canonical cash flow rows.",
    )
    filters: StatefulPositionFilters = Field(
        default_factory=StatefulPositionFilters,
        description="Optional inclusion filters for stateful position sourcing.",
    )


def _has_legacy_stateless_payload(request: "ContributionAnalyticsRequest") -> bool:
    return request.portfolio_data is not None or request.positions_data is not None


def _validate_legacy_stateless_payload_shape(request: "ContributionAnalyticsRequest") -> bool:
    has_partial_legacy = (request.portfolio_data is None) != (request.positions_data is None)
    if has_partial_legacy:
        raise ValueError("portfolio_data and positions_data must be provided together for legacy stateless mode")
    return _has_legacy_stateless_payload(request)


def _validate_stateless_contribution_payloads(
    request: "ContributionAnalyticsRequest",
    *,
    has_legacy_stateless: bool,
) -> None:
    if request.stateful_input is not None:
        raise ValueError("stateful_input must be null when input_mode=stateless")
    if request.stateless_input is not None and has_legacy_stateless:
        raise ValueError(
            "Provide either stateless_input or legacy portfolio_data/positions_data, not both, for stateless mode"
        )
    if request.stateless_input is None and not has_legacy_stateless:
        raise ValueError(
            "stateless_input or legacy portfolio_data/positions_data is required when input_mode=stateless"
        )


def _validate_stateful_contribution_payloads(
    request: "ContributionAnalyticsRequest",
    *,
    has_legacy_stateless: bool,
) -> None:
    if request.stateful_input is None:
        raise ValueError("stateful_input is required when input_mode=stateful")
    if request.stateless_input is not None:
        raise ValueError("stateless_input must be null when input_mode=stateful")
    if has_legacy_stateless:
        raise ValueError("portfolio_data and positions_data must be null when input_mode=stateful")


class ContributionAnalyticsRequest(ContributionRequestBase):
    input_mode: ContributionInputMode = Field(
        default=ContributionInputMode.STATELESS,
        description="Execution mode for contribution analytics.",
        examples=["stateful"],
    )
    stateless_input: ContributionStatelessInput | None = Field(
        default=None,
        description="Stateless contribution input payload.",
    )
    stateful_input: ContributionStatefulInput | None = Field(
        default=None,
        description="Stateful contribution input payload resolved through lotus-core integrations.",
    )
    portfolio_data: PortfolioData | None = Field(
        default=None,
        description="Legacy stateless portfolio contribution payload. Prefer stateless_input for new integrations.",
    )
    positions_data: list[PositionData] | None = Field(
        default=None,
        description="Legacy stateless positions contribution payload. Prefer stateless_input for new integrations.",
    )

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "ContributionAnalyticsRequest":
        has_legacy_stateless = _validate_legacy_stateless_payload_shape(self)
        if self.input_mode == ContributionInputMode.STATELESS:
            _validate_stateless_contribution_payloads(self, has_legacy_stateless=has_legacy_stateless)

        if self.input_mode == ContributionInputMode.STATEFUL:
            _validate_stateful_contribution_payloads(self, has_legacy_stateless=has_legacy_stateless)
        return self

    def to_stateless_contribution_request(
        self,
        *,
        portfolio_data: PortfolioData | None = None,
        positions_data: list[PositionData] | None = None,
    ) -> ContributionRequest:
        if portfolio_data is not None and positions_data is not None:
            resolved_portfolio_data = portfolio_data
            resolved_positions_data = positions_data
        elif self.stateless_input is not None:
            resolved_portfolio_data = self.stateless_input.portfolio_data
            resolved_positions_data = self.stateless_input.positions_data
        elif self.portfolio_data is not None and self.positions_data is not None:
            resolved_portfolio_data = self.portfolio_data
            resolved_positions_data = self.positions_data
        else:
            raise ValueError("No stateless contribution inputs are available to build a ContributionRequest")

        payload = self.model_dump(
            exclude={
                "input_mode",
                "stateless_input",
                "stateful_input",
                "portfolio_data",
                "positions_data",
            },
            mode="python",
        )
        payload["portfolio_data"] = resolved_portfolio_data.model_dump(mode="python")
        payload["positions_data"] = [position.model_dump(mode="python") for position in resolved_positions_data]
        return ContributionRequest.model_validate(payload)
