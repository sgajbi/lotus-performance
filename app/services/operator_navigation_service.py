from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorNavigationLinks:
    execution_path: str
    lineage_path: str


def build_operator_navigation_links(calculation_id: str) -> OperatorNavigationLinks:
    return OperatorNavigationLinks(
        execution_path=f"/performance/executions/{calculation_id}",
        lineage_path=f"/performance/lineage/{calculation_id}",
    )
