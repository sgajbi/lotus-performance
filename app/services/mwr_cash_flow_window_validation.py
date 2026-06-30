from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from core.errors import APIUnprocessableEntityError
from engine.mwr_types import CashFlowLike

MWR_CASH_FLOW_OUT_OF_WINDOW = "MWR_CASH_FLOW_OUT_OF_WINDOW"


@dataclass(frozen=True)
class MWRCashFlowWindowIssue:
    before_start_dates: tuple[date, ...]
    after_end_dates: tuple[date, ...]

    @property
    def offending_cash_flow_count(self) -> int:
        return len(self.before_start_dates) + len(self.after_end_dates)


def validate_mwr_cash_flow_window(
    *,
    cash_flows: Sequence[CashFlowLike],
    start_date: date,
    end_date: date,
) -> None:
    """Reject MWR cash flows that do not belong to the resolved measurement window."""
    issue = mwr_cash_flow_window_issue(cash_flows=cash_flows, start_date=start_date, end_date=end_date)
    if issue is None:
        return
    raise APIUnprocessableEntityError(
        detail={
            "code": MWR_CASH_FLOW_OUT_OF_WINDOW,
            "message": "MWR cash-flow dates must fall inside the resolved measurement window.",
            "measurement_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "offending_cash_flow_count": issue.offending_cash_flow_count,
            "before_start_dates": [item.isoformat() for item in issue.before_start_dates],
            "after_end_dates": [item.isoformat() for item in issue.after_end_dates],
        },
        error_code=MWR_CASH_FLOW_OUT_OF_WINDOW,
    )


def mwr_cash_flow_window_issue(
    *,
    cash_flows: Sequence[CashFlowLike],
    start_date: date,
    end_date: date,
) -> MWRCashFlowWindowIssue | None:
    before_start_dates = tuple(cash_flow.date for cash_flow in cash_flows if cash_flow.date < start_date)
    after_end_dates = tuple(cash_flow.date for cash_flow in cash_flows if cash_flow.date > end_date)
    if not before_start_dates and not after_end_dates:
        return None
    return MWRCashFlowWindowIssue(
        before_start_dates=tuple(sorted(before_start_dates)),
        after_end_dates=tuple(sorted(after_end_dates)),
    )
