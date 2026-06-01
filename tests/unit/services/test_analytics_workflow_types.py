from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_BENCHMARK,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_TWR_INSPECTION,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)


def test_benchmark_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_BENCHMARK == "BENCHMARK"


def test_twr_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_TWR == "TWR"


def test_twr_inspection_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_TWR_INSPECTION == "TWR_INSPECTION"


def test_workspace_summary_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY == "WORKSPACE_SUMMARY"
