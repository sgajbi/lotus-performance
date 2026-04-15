from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorNavigationLinks:
    execution_path: str
    lineage_path: str
    result_path: str | None


def build_operator_navigation_links(calculation_id: str, workflow_type: str | None = None) -> OperatorNavigationLinks:
    lineage_path = f"/performance/lineage/{calculation_id}"
    if workflow_type == "TWR_INSPECTION":
        lineage_path = f"/performance/inspections/{calculation_id}"
    return OperatorNavigationLinks(
        execution_path=f"/performance/executions/{calculation_id}",
        lineage_path=lineage_path,
        result_path=_build_result_path(calculation_id=calculation_id, workflow_type=workflow_type),
    )


def _build_result_path(*, calculation_id: str, workflow_type: str | None) -> str | None:
    if workflow_type == "TWR":
        return f"/performance/twr/results/{calculation_id}"
    if workflow_type == "BENCHMARK":
        return f"/performance/benchmark/results/{calculation_id}"
    if workflow_type == "ReturnsSeries":
        return f"/integration/returns/series/results/{calculation_id}"
    if workflow_type == "Contribution":
        return f"/performance/contribution/results/{calculation_id}"
    if workflow_type == "Attribution":
        return f"/performance/attribution/results/{calculation_id}"
    if workflow_type == "TWR_INSPECTION":
        return f"/performance/inspections/{calculation_id}"
    return None
