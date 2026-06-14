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
    envelope_issue = _stateless_contribution_envelope_issue(
        has_nested=request.stateless_input is not None,
        has_legacy=has_legacy_stateless,
    )
    if envelope_issue is not None:
        raise ValueError(envelope_issue)


def _stateless_contribution_envelope_issue(*, has_nested: bool, has_legacy: bool) -> str | None:
    if has_nested and has_legacy:
        return "Provide either stateless_input or legacy portfolio_data/positions_data, not both, for stateless mode"
    if not has_nested and not has_legacy:
        return "stateless_input or legacy portfolio_data/positions_data is required when input_mode=stateless"
    return None


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


def _resolved_stateless_contribution_inputs(
    request: "ContributionAnalyticsRequest",
    *,
    portfolio_data: PortfolioData | None,
    positions_data: list[PositionData] | None,
) -> tuple[PortfolioData, list[PositionData]]:
    if portfolio_data is not None and positions_data is not None:
        return portfolio_data, positions_data
    if request.stateless_input is not None:
        return request.stateless_input.portfolio_data, request.stateless_input.positions_data
    if request.portfolio_data is not None and request.positions_data is not None:
        return request.portfolio_data, request.positions_data
    raise ValueError("No stateless contribution inputs are available to build a ContributionRequest")


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
        resolved_portfolio_data, resolved_positions_data = _resolved_stateless_contribution_inputs(
            self,
            portfolio_data=portfolio_data,
            positions_data=positions_data,
        )

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
