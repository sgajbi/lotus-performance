from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_ATTRIBUTION,
    ANALYTICS_WORKFLOW_BENCHMARK,
    ANALYTICS_WORKFLOW_CONTRIBUTION,
    ANALYTICS_WORKFLOW_RETURNS_SERIES,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_TWR_INSPECTION,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)
from app.services.operator_navigation_service import build_operator_navigation_links


def test_operator_navigation_links_cover_supported_async_result_surfaces():
    expected_paths = {
        ANALYTICS_WORKFLOW_TWR: "/performance/twr/results/calc-1",
        ANALYTICS_WORKFLOW_BENCHMARK: "/performance/benchmark/results/calc-1",
        ANALYTICS_WORKFLOW_RETURNS_SERIES: "/integration/returns/series/results/calc-1",
        ANALYTICS_WORKFLOW_CONTRIBUTION: "/performance/contribution/results/calc-1",
        ANALYTICS_WORKFLOW_ATTRIBUTION: "/performance/attribution/results/calc-1",
        ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY: "/performance/workspace-summary/results/calc-1",
        ANALYTICS_WORKFLOW_TWR_INSPECTION: "/performance/inspections/calc-1",
    }

    for workflow_type, expected_path in expected_paths.items():
        links = build_operator_navigation_links("calc-1", workflow_type=workflow_type)

        assert links.execution_path == "/performance/executions/calc-1"
        assert links.result_path == expected_path


def test_operator_navigation_links_use_inspection_lineage_path_and_omit_unknown_result_path():
    inspection_links = build_operator_navigation_links("inspect-1", workflow_type=ANALYTICS_WORKFLOW_TWR_INSPECTION)
    unsupported_links = build_operator_navigation_links("calc-unknown", workflow_type="UnknownWorkflow")

    assert inspection_links.lineage_path == "/performance/inspections/inspect-1"
    assert unsupported_links.lineage_path == "/performance/lineage/calc-unknown"
    assert unsupported_links.result_path is None
