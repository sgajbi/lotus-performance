from __future__ import annotations

from typing import cast

from app.api.mappers.analytics_workflow_requests import (
    map_benchmark_request,
    map_contribution_request,
    map_returns_series_request,
    map_twr_request,
    map_workspace_summary_request,
)
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


def test_analytics_workflow_mappers_preserve_validated_request_identity():
    twr_request = cast(TWRAnalyticsRequest, object())
    workspace_request = cast(WorkspaceSummaryRequest, object())
    contribution_request = cast(ContributionAnalyticsRequest, object())
    benchmark_request = cast(BenchmarkAnalyticsRequest, object())
    returns_series_request = cast(ReturnsSeriesRequest, object())

    assert map_twr_request(twr_request) == TWRWorkflowCommand(request=twr_request)
    assert map_twr_request(twr_request).request is twr_request
    assert map_workspace_summary_request(workspace_request) == WorkspaceSummaryWorkflowCommand(
        request=workspace_request
    )
    assert map_workspace_summary_request(workspace_request).request is workspace_request
    assert map_contribution_request(contribution_request) == ContributionWorkflowCommand(request=contribution_request)
    assert map_contribution_request(contribution_request).request is contribution_request
    assert map_benchmark_request(benchmark_request) == BenchmarkWorkflowCommand(request=benchmark_request)
    assert map_benchmark_request(benchmark_request).request is benchmark_request
    assert map_returns_series_request(returns_series_request) == ReturnsSeriesWorkflowCommand(
        request=returns_series_request
    )
    assert map_returns_series_request(returns_series_request).request is returns_series_request
