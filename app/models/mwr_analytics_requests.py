from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.mwr_requests import CashFlow, MoneyWeightedReturnRequest, MoneyWeightedReturnRequestBase


class MWRInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class MWRStatelessInput(BaseModel):
    begin_mv: float
    end_mv: float
    cash_flows: list[CashFlow]


class MWRStatefulInput(BaseModel):
    consumer_system: str = Field(
        default="lotus-performance",
        description="Consumer system used for lotus-core stateful sourcing policy and lineage.",
        examples=["lotus-performance"],
    )
    window_start_date: date = Field(
        description="Inclusive start date for the sourced MWR measurement window.",
        examples=["2025-01-01"],
    )


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
        has_legacy_stateless = self.begin_mv is not None or self.end_mv is not None or self.cash_flows is not None
        has_partial_legacy = (
            any(value is None for value in (self.begin_mv, self.end_mv, self.cash_flows)) and has_legacy_stateless
        )
        if has_partial_legacy:
            raise ValueError("begin_mv, end_mv, and cash_flows must be provided together for legacy stateless mode")

        if self.input_mode == MWRInputMode.STATELESS:
            if self.stateful_input is not None:
                raise ValueError("stateful_input must be null when input_mode=stateless")
            if self.stateless_input is not None and has_legacy_stateless:
                raise ValueError(
                    "Provide either stateless_input or legacy begin_mv/end_mv/cash_flows, not both, for stateless mode"
                )
            if self.stateless_input is None and not has_legacy_stateless:
                raise ValueError(
                    "stateless_input or legacy begin_mv/end_mv/cash_flows is required when input_mode=stateless"
                )

        if self.input_mode == MWRInputMode.STATEFUL:
            if self.stateful_input is None:
                raise ValueError("stateful_input is required when input_mode=stateful")
            if self.stateless_input is not None:
                raise ValueError("stateless_input must be null when input_mode=stateful")
            if has_legacy_stateless:
                raise ValueError("begin_mv, end_mv, and cash_flows must be null when input_mode=stateful")
        return self

    def to_stateless_mwr_request(
        self,
        *,
        begin_mv: float | None = None,
        end_mv: float | None = None,
        cash_flows: list[CashFlow] | None = None,
        start_date: date | None = None,
    ) -> MoneyWeightedReturnRequest:
        if begin_mv is not None and end_mv is not None and cash_flows is not None:
            resolved_begin_mv = begin_mv
            resolved_end_mv = end_mv
            resolved_cash_flows = cash_flows
        elif self.stateless_input is not None:
            resolved_begin_mv = self.stateless_input.begin_mv
            resolved_end_mv = self.stateless_input.end_mv
            resolved_cash_flows = self.stateless_input.cash_flows
        elif self.begin_mv is not None and self.end_mv is not None and self.cash_flows is not None:
            resolved_begin_mv = self.begin_mv
            resolved_end_mv = self.end_mv
            resolved_cash_flows = self.cash_flows
        else:
            raise ValueError("No stateless MWR inputs are available to build a MoneyWeightedReturnRequest")

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
        payload["begin_mv"] = resolved_begin_mv
        payload["end_mv"] = resolved_end_mv
        payload["cash_flows"] = [cash_flow.model_dump(mode="python") for cash_flow in resolved_cash_flows]
        payload["start_date"] = start_date if start_date is not None else self.start_date
        return MoneyWeightedReturnRequest.model_validate(payload)
