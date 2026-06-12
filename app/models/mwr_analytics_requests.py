from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.mwr_requests import CashFlow, MoneyWeightedReturnRequest, MoneyWeightedReturnRequestBase


class MWRInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class MWRStatelessInput(BaseModel):
    begin_mv: float
    end_mv: float
    cash_flows: list[CashFlow]


class MWRStatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_start_date: date = Field(
        description="Inclusive start date for the sourced MWR measurement window.",
        examples=["2025-01-01"],
    )


@dataclass(frozen=True)
class _ResolvedMWRStatelessInput:
    begin_mv: float
    end_mv: float
    cash_flows: list[CashFlow]


def _has_legacy_stateless_payload(request: "MoneyWeightedReturnAnalyticsRequest") -> bool:
    return request.begin_mv is not None or request.end_mv is not None or request.cash_flows is not None


def _validate_legacy_stateless_payload_complete(request: "MoneyWeightedReturnAnalyticsRequest") -> bool:
    has_legacy_stateless = _has_legacy_stateless_payload(request)
    has_partial_legacy = (
        any(value is None for value in (request.begin_mv, request.end_mv, request.cash_flows)) and has_legacy_stateless
    )
    if has_partial_legacy:
        raise ValueError("begin_mv, end_mv, and cash_flows must be provided together for legacy stateless mode")
    return has_legacy_stateless


def _validate_stateless_mwr_payloads(
    request: "MoneyWeightedReturnAnalyticsRequest",
    *,
    has_legacy_stateless: bool,
) -> None:
    if request.stateful_input is not None:
        raise ValueError("stateful_input must be null when input_mode=stateless")
    if request.stateless_input is not None and has_legacy_stateless:
        raise ValueError(
            "Provide either stateless_input or legacy begin_mv/end_mv/cash_flows, not both, for stateless mode"
        )
    if request.stateless_input is None and not has_legacy_stateless:
        raise ValueError("stateless_input or legacy begin_mv/end_mv/cash_flows is required when input_mode=stateless")


def _validate_stateful_mwr_payloads(
    request: "MoneyWeightedReturnAnalyticsRequest",
    *,
    has_legacy_stateless: bool,
) -> None:
    if request.stateful_input is None:
        raise ValueError("stateful_input is required when input_mode=stateful")
    if request.stateless_input is not None:
        raise ValueError("stateless_input must be null when input_mode=stateful")
    if has_legacy_stateless:
        raise ValueError("begin_mv, end_mv, and cash_flows must be null when input_mode=stateful")
    if request.source_preconverted_fx_evidence is not None:
        raise ValueError("source_preconverted_fx_evidence must be null when input_mode=stateful")


class MoneyWeightedReturnAnalyticsRequest(MoneyWeightedReturnRequestBase):
    input_mode: MWRInputMode = Field(
        default=MWRInputMode.STATELESS,
        description="Execution mode for money-weighted return analytics.",
        examples=["stateful"],
    )
    stateless_input: MWRStatelessInput | None = Field(
        default=None,
        description="Stateless MWR input payload.",
    )
    stateful_input: MWRStatefulInput | None = Field(
        default=None,
        description="Stateful MWR input payload resolved through lotus-core integrations.",
    )
    begin_mv: float | None = Field(
        default=None,
        description="Legacy stateless beginning market value. Prefer stateless_input for new integrations.",
    )
    end_mv: float | None = Field(
        default=None,
        description="Legacy stateless ending market value. Prefer stateless_input for new integrations.",
    )
    cash_flows: list[CashFlow] | None = Field(
        default=None,
        description="Legacy stateless cash flow schedule. Prefer stateless_input for new integrations.",
    )

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "MoneyWeightedReturnAnalyticsRequest":
        has_legacy_stateless = _validate_legacy_stateless_payload_complete(self)

        if self.input_mode == MWRInputMode.STATELESS:
            _validate_stateless_mwr_payloads(self, has_legacy_stateless=has_legacy_stateless)

        if self.input_mode == MWRInputMode.STATEFUL:
            _validate_stateful_mwr_payloads(self, has_legacy_stateless=has_legacy_stateless)
        return self

    def to_stateless_mwr_request(
        self,
        *,
        begin_mv: float | None = None,
        end_mv: float | None = None,
        cash_flows: list[CashFlow] | None = None,
        start_date: date | None = None,
    ) -> MoneyWeightedReturnRequest:
        resolved_input = _resolve_mwr_stateless_input(
            request=self,
            begin_mv=begin_mv,
            end_mv=end_mv,
            cash_flows=cash_flows,
        )
        payload = self.model_dump(
            exclude={
                "input_mode",
                "stateless_input",
                "stateful_input",
                "begin_mv",
                "end_mv",
                "cash_flows",
            },
            mode="python",
        )
        payload["begin_mv"] = resolved_input.begin_mv
        payload["end_mv"] = resolved_input.end_mv
        payload["cash_flows"] = [cash_flow.model_dump(mode="python") for cash_flow in resolved_input.cash_flows]
        payload["start_date"] = start_date if start_date is not None else self.start_date
        return MoneyWeightedReturnRequest.model_validate(payload)


def _resolve_mwr_stateless_input(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    begin_mv: float | None = None,
    end_mv: float | None = None,
    cash_flows: list[CashFlow] | None = None,
) -> _ResolvedMWRStatelessInput:
    if begin_mv is not None and end_mv is not None and cash_flows is not None:
        return _ResolvedMWRStatelessInput(begin_mv=begin_mv, end_mv=end_mv, cash_flows=cash_flows)
    if request.stateless_input is not None:
        return _ResolvedMWRStatelessInput(
            begin_mv=request.stateless_input.begin_mv,
            end_mv=request.stateless_input.end_mv,
            cash_flows=request.stateless_input.cash_flows,
        )
    if request.begin_mv is not None and request.end_mv is not None and request.cash_flows is not None:
        return _ResolvedMWRStatelessInput(
            begin_mv=request.begin_mv,
            end_mv=request.end_mv,
            cash_flows=request.cash_flows,
        )
    raise ValueError("No stateless MWR inputs are available to build a MoneyWeightedReturnRequest")
