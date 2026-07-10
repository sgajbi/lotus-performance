from __future__ import annotations

from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.models.returns_series import ReturnsSeriesRequest
from app.models.twr_requests import TWRAnalyticsRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.services.analytics_workflow_commands import (
    BenchmarkWorkflowCommand,
    ContributionWorkflowCommand,
    ReturnsSeriesWorkflowCommand,
    TWRWorkflowCommand,
    WorkspaceSummaryWorkflowCommand,
)


def map_twr_request(request: TWRAnalyticsRequest) -> TWRWorkflowCommand:
    return TWRWorkflowCommand(request=request)


def map_workspace_summary_request(request: WorkspaceSummaryRequest) -> WorkspaceSummaryWorkflowCommand:
    return WorkspaceSummaryWorkflowCommand(request=request)


def map_contribution_request(request: ContributionAnalyticsRequest) -> ContributionWorkflowCommand:
    return ContributionWorkflowCommand(request=request)


def map_benchmark_request(request: BenchmarkAnalyticsRequest) -> BenchmarkWorkflowCommand:
    return BenchmarkWorkflowCommand(request=request)


def map_returns_series_request(request: ReturnsSeriesRequest) -> ReturnsSeriesWorkflowCommand:
    return ReturnsSeriesWorkflowCommand(request=request)
