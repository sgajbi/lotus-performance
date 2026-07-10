from __future__ import annotations

from dataclasses import dataclass

from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_ATTRIBUTION,
    ANALYTICS_WORKFLOW_BENCHMARK,
    ANALYTICS_WORKFLOW_CONTRIBUTION,
    ANALYTICS_WORKFLOW_RETURNS_SERIES,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_TWR_INSPECTION,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)


@dataclass(frozen=True)
class OperatorNavigationLinks:
    execution_path: str
    lineage_path: str
    result_path: str | None


_RESULT_PATH_TEMPLATES = {
    ANALYTICS_WORKFLOW_TWR: "/performance/twr/results/{calculation_id}",
    ANALYTICS_WORKFLOW_BENCHMARK: "/performance/benchmark/results/{calculation_id}",
    ANALYTICS_WORKFLOW_RETURNS_SERIES: "/integration/returns/series/results/{calculation_id}",
    ANALYTICS_WORKFLOW_CONTRIBUTION: "/performance/contribution/results/{calculation_id}",
    ANALYTICS_WORKFLOW_ATTRIBUTION: "/performance/attribution/results/{calculation_id}",
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY: "/performance/workspace-summary/results/{calculation_id}",
    ANALYTICS_WORKFLOW_TWR_INSPECTION: "/performance/inspections/{calculation_id}",
}


def build_operator_navigation_links(calculation_id: str, workflow_type: str | None = None) -> OperatorNavigationLinks:
    lineage_path = f"/performance/lineage/{calculation_id}"
    if workflow_type == ANALYTICS_WORKFLOW_TWR_INSPECTION:
        lineage_path = f"/performance/inspections/{calculation_id}"
    return OperatorNavigationLinks(
        execution_path=f"/performance/executions/{calculation_id}",
        lineage_path=lineage_path,
        result_path=_build_result_path(calculation_id=calculation_id, workflow_type=workflow_type),
    )


def _build_result_path(*, calculation_id: str, workflow_type: str | None) -> str | None:
    if workflow_type is None:
        return None
    result_path_template = _RESULT_PATH_TEMPLATES.get(workflow_type)
    if result_path_template is None:
        return None
    return result_path_template.format(calculation_id=calculation_id)
