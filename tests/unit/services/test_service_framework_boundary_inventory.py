from __future__ import annotations

from pathlib import Path

FASTAPI_SERVICE_BOUNDARY_ALLOWLIST = frozenset(
    {
        "app/services/returns_series_calculation_workflow_service.py",
        "app/services/returns_series_service.py",
        "app/services/stateful_attribution_input_service.py",
        "app/services/stateful_benchmark_input_service.py",
        "app/services/workspace_summary_service.py",
    }
)

MIGRATED_FRAMEWORK_NEUTRAL_MODULES = frozenset(
    {
        "app/services/async_result_service.py",
        "app/services/benchmark_assignment_service.py",
        "app/services/calculation_result_access.py",
        "app/services/execution_polling_service.py",
        "app/services/input_mode_validation.py",
        "app/services/returns_series_calculation_workflow_service.py",
        "app/services/stateful_execution_policy_service.py",
        "app/services/stateful_performance_input_service.py",
        "app/services/stateful_position_currency_support.py",
        "app/services/stateful_position_row_service.py",
        "app/services/stateful_upstream_errors.py",
        "app/services/submission_fencing_service.py",
        "app/services/valuation_points_service.py",
        "app/services/attribution_mode_service.py",
        "app/services/benchmark_mode_service.py",
        "app/services/contribution_mode_service.py",
        "app/services/mwr_mode_service.py",
        "app/services/mwr_fx_evidence_service.py",
        "app/services/offset_pagination.py",
        "app/services/stateless_benchmark_input_service.py",
        "app/services/attribution_calculation_workflow_service.py",
        "app/services/attribution_service.py",
        "app/services/benchmark_calculation_workflow_service.py",
        "app/services/benchmark_exposure_context_service.py",
        "app/services/benchmark_exposure_context_workflow_service.py",
        "app/services/contribution_calculation_workflow_service.py",
        "app/services/contribution_service.py",
        "app/services/error_details.py",
        "app/services/mwr_calculation_service.py",
        "app/services/operator_action_guard_service.py",
        "app/services/operator_action_lease_service.py",
        "app/services/twr_calculation_service.py",
        "app/services/twr_mode_service.py",
        "app/services/twr_service.py",
        "app/workers/compute_executor_worker.py",
    }
)

FASTAPI_BOUNDARY_MARKERS = (
    "from fastapi",
    "import fastapi",
    "HTTPException",
    "JSONResponse",
)


def test_service_framework_boundary_inventory_does_not_grow() -> None:
    offenders = _fastapi_boundary_offenders()

    assert offenders <= FASTAPI_SERVICE_BOUNDARY_ALLOWLIST
    assert offenders.isdisjoint(MIGRATED_FRAMEWORK_NEUTRAL_MODULES)


def _fastapi_boundary_offenders() -> set[str]:
    repo_root = Path(__file__).resolve().parents[3]
    candidate_files = [
        *repo_root.joinpath("app", "services").glob("**/*.py"),
        *repo_root.joinpath("app", "workers").glob("**/*.py"),
    ]

    return {
        _repo_relative(path, repo_root)
        for path in candidate_files
        if any(marker in path.read_text(encoding="utf-8") for marker in FASTAPI_BOUNDARY_MARKERS)
    }


def _repo_relative(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()
