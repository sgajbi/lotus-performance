from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_ATTRIBUTION,
    ANALYTICS_WORKFLOW_BENCHMARK,
    ANALYTICS_WORKFLOW_BENCHMARK_EXPOSURE_CONTEXT,
    ANALYTICS_WORKFLOW_CONTRIBUTION,
    ANALYTICS_WORKFLOW_MWR,
    ANALYTICS_WORKFLOW_RETURNS_SERIES,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_TWR_INSPECTION,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)


def test_benchmark_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_BENCHMARK == "BENCHMARK"


def test_benchmark_exposure_context_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_BENCHMARK_EXPOSURE_CONTEXT == "BENCHMARK_EXPOSURE_CONTEXT"


def test_attribution_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_ATTRIBUTION == "Attribution"


def test_contribution_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_CONTRIBUTION == "Contribution"


def test_mwr_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_MWR == "MWR"


def test_returns_series_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_RETURNS_SERIES == "ReturnsSeries"


def test_twr_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_TWR == "TWR"


def test_twr_inspection_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_TWR_INSPECTION == "TWR_INSPECTION"


def test_workspace_summary_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY == "WORKSPACE_SUMMARY"
