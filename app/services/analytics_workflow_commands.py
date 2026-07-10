from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast

from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.models.returns_series import ReturnsSeriesRequest
from app.models.twr_requests import TWRAnalyticsRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest


@dataclass(frozen=True)
class TWRWorkflowCommand:
    request: TWRAnalyticsRequest


@dataclass(frozen=True)
class WorkspaceSummaryWorkflowCommand:
    request: WorkspaceSummaryRequest


@dataclass(frozen=True)
class ContributionWorkflowCommand:
    request: ContributionAnalyticsRequest


@dataclass(frozen=True)
class BenchmarkWorkflowCommand:
    request: BenchmarkAnalyticsRequest


@dataclass(frozen=True)
class ReturnsSeriesWorkflowCommand:
    request: ReturnsSeriesRequest


CommandT = TypeVar(
    "CommandT",
    TWRWorkflowCommand,
    WorkspaceSummaryWorkflowCommand,
    ContributionWorkflowCommand,
    BenchmarkWorkflowCommand,
    ReturnsSeriesWorkflowCommand,
)
RequestT = TypeVar(
    "RequestT",
    TWRAnalyticsRequest,
    WorkspaceSummaryRequest,
    ContributionAnalyticsRequest,
    BenchmarkAnalyticsRequest,
    ReturnsSeriesRequest,
)


def workflow_request(command: CommandT, request_type: type[RequestT]) -> RequestT:
    """Return the validated request carried by a workflow command.

    The fallback keeps existing lower-level tests compatible while API routes migrate to explicit
    command mapping. Route-level direct DTO leakage is guarded by the architecture inventory.
    """

    request = getattr(command, "request", command)
    if isinstance(request, request_type):
        return request
    return cast(RequestT, request)
