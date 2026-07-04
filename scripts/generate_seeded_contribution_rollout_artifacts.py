from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

import pandas as pd
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from scripts.contribution_rollout_readiness_report import ContributionRolloutReadinessReport

DEFAULT_OUTPUT_DIR = Path("artifacts/contribution-rollout-readiness/seeded")


def _ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _load_runtime_dependencies() -> dict[str, Any]:
    _ensure_repo_root_on_path()
    from app.core.config import get_settings
    from app.services import contribution_service
    from app.services.async_result_store import async_result_store
    from app.services.compute_job_store import compute_job_store
    from app.services.execution_registry import execution_registry
    from app.services.lineage_metadata_store import lineage_metadata_store
    from main import app

    return {
        "get_settings": get_settings,
        "contribution_service": contribution_service,
        "async_result_store": async_result_store,
        "compute_job_store": compute_job_store,
        "execution_registry": execution_registry,
        "lineage_metadata_store": lineage_metadata_store,
        "app": app,
    }


def _ensure_clean_runtime_state() -> None:
    runtime = _load_runtime_dependencies()
    runtime["execution_registry"].create_schema()
    runtime["execution_registry"].clear_all_records()
    runtime["compute_job_store"].create_schema()
    runtime["compute_job_store"].clear_all_records()
    runtime["async_result_store"].create_schema()
    runtime["async_result_store"].clear_all_records()
    runtime["lineage_metadata_store"].create_schema()
    runtime["lineage_metadata_store"].clear_all_records()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@contextmanager
def _patched_contribution_service(
    *,
    prepare_fn: Callable,
    daily_fn: Callable,
    mode: str,
) -> Iterator[None]:
    runtime = _load_runtime_dependencies()
    contribution_service = runtime["contribution_service"]
    get_settings = runtime["get_settings"]
    original_prepare = contribution_service._prepare_hierarchical_data
    original_daily = contribution_service._calculate_daily_instrument_contributions
    settings = get_settings()
    original_mode = settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE
    contribution_service._prepare_hierarchical_data = prepare_fn  # type: ignore[assignment]
    contribution_service._calculate_daily_instrument_contributions = daily_fn  # type: ignore[assignment]
    settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE = mode
    try:
        yield
    finally:
        contribution_service._prepare_hierarchical_data = original_prepare  # type: ignore[assignment]
        contribution_service._calculate_daily_instrument_contributions = original_daily  # type: ignore[assignment]
        settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE = original_mode


def _seed_no_material_shadow_response(client: TestClient) -> dict:
    payload = {
        "portfolio_id": "SEEDED_NO_MATERIAL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030.2},
            ],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030.2},
                ],
            }
        ],
    }
    response = client.post("/performance/contribution", json=payload)
    response.raise_for_status()
    return response.json()


def _candidate_prepare(_request):
    instruments_df = pd.DataFrame(
        {
            "position_id": ["A", "A", "A", "B", "B", "B"],
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
            ],
            "perf_reset": [0, 1, 0, 0, 1, 0],
            "bod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "eod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
    portfolio_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
            ],
            "begin_mv": [1000.0, 1005.0, 1010.0],
            "bod_cf": [0.0, 0.0, 0.0],
            "daily_ror": [1.0, 1.0, 1.0],
            "perf_reset": [0, 1, 0],
            "nip": [0, 0, 0],
            "nctrl_4": [0, 0, 0],
            "account_reset": [0, 0, 0],
            "sod_reset": [0, 0, 0],
            "nip_rule_v1_shadow": [0, 0, 0],
            "nip_rule_v2_shadow": [0, 0, 0],
        }
    )
    return instruments_df, portfolio_df


def _candidate_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
    return pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
                pd.Timestamp("2025-01-01").date(),
                pd.Timestamp("2025-01-02").date(),
                pd.Timestamp("2025-01-03").date(),
            ],
            "position_id": ["A", "A", "A", "B", "B", "B"],
            "smoothed_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
            "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
            "daily_weight": [0.10, 0.95, 0.95, 0.90, 0.05, 0.05],
            "perf_reset": [0, 1, 0, 0, 1, 0],
        }
    )


def _seed_promoted_candidate_response(client: TestClient) -> dict:
    payload = {
        "portfolio_id": "SEEDED_PROMOTED",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
            ],
        },
        "positions_data": [
            {"position_id": "A", "valuation_points": []},
            {"position_id": "B", "valuation_points": []},
        ],
    }
    with _patched_contribution_service(
        prepare_fn=_candidate_prepare,
        daily_fn=_candidate_daily,
        mode="CANDIDATE_PERIODS",
    ):
        response = client.post("/performance/contribution", json=payload)
    response.raise_for_status()
    return response.json()


def _seed_ready_candidate_shadow_only_response(client: TestClient) -> dict:
    payload = {
        "portfolio_id": "SEEDED_READY_CANDIDATE",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
            ],
        },
        "positions_data": [
            {"position_id": "A", "valuation_points": []},
            {"position_id": "B", "valuation_points": []},
        ],
    }
    with _patched_contribution_service(
        prepare_fn=_candidate_prepare,
        daily_fn=_candidate_daily,
        mode="OFF",
    ):
        response = client.post("/performance/contribution", json=payload)
    response.raise_for_status()
    return response.json()


def _blocked_flow_prepare(_request):
    instruments_df, portfolio_df = _candidate_prepare(_request)
    instruments_df = instruments_df.copy()
    instruments_df["bod_cf"] = [-50.0, 0.0, 0.0, 40.0, 0.0, 0.0]
    return instruments_df, portfolio_df


def _blocked_flow_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
    daily_df = _candidate_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing).copy()
    daily_df["bod_cf"] = [-50.0, 0.0, 0.0, 40.0, 0.0, 0.0]
    daily_df["eod_cf"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return daily_df


def _seed_blocked_flow_response(client: TestClient) -> dict:
    payload = {
        "portfolio_id": "SEEDED_BLOCKED_FLOW",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
            ],
        },
        "positions_data": [
            {"position_id": "A", "valuation_points": []},
            {"position_id": "B", "valuation_points": []},
        ],
    }
    with _patched_contribution_service(
        prepare_fn=_blocked_flow_prepare,
        daily_fn=_blocked_flow_daily,
        mode="OFF",
    ):
        response = client.post("/performance/contribution", json=payload)
    response.raise_for_status()
    return response.json()


def _blocked_reset_alignment_prepare(_request):
    instruments_df, portfolio_df = _candidate_prepare(_request)
    instruments_df = instruments_df.copy()
    instruments_df["perf_reset"] = [0, 0, 1, 0, 0, 1]
    return instruments_df, portfolio_df


def _blocked_reset_alignment_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
    daily_df = _candidate_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing).copy()
    daily_df["perf_reset"] = [0, 0, 1, 0, 0, 1]
    return daily_df


def _seed_blocked_reset_alignment_response(client: TestClient) -> dict:
    payload = {
        "portfolio_id": "SEEDED_BLOCKED_RESET_ALIGNMENT",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
            ],
        },
        "positions_data": [
            {"position_id": "A", "valuation_points": []},
            {"position_id": "B", "valuation_points": []},
        ],
    }
    with _patched_contribution_service(
        prepare_fn=_blocked_reset_alignment_prepare,
        daily_fn=_blocked_reset_alignment_daily,
        mode="OFF",
    ):
        response = client.post("/performance/contribution", json=payload)
    response.raise_for_status()
    return response.json()


def generate_seeded_contribution_rollout_artifacts(output_dir: Path) -> ContributionRolloutReadinessReport:
    _ensure_repo_root_on_path()
    from scripts.contribution_rollout_readiness_report import build_contribution_rollout_readiness_report

    _ensure_clean_runtime_state()
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime = _load_runtime_dependencies()
    with TestClient(runtime["app"]) as client:
        no_material_response = _seed_no_material_shadow_response(client)
        ready_candidate_response = _seed_ready_candidate_shadow_only_response(client)
        promoted_response = _seed_promoted_candidate_response(client)
        blocked_response = _seed_blocked_flow_response(client)
        blocked_reset_alignment_response = _seed_blocked_reset_alignment_response(client)

    no_material_path = output_dir / "no_material_shadow.json"
    ready_candidate_path = output_dir / "ready_candidate_shadow_only.json"
    promoted_path = output_dir / "promoted_candidate.json"
    blocked_path = output_dir / "blocked_flow_balance.json"
    blocked_reset_alignment_path = output_dir / "blocked_reset_alignment.json"
    _write_json(no_material_path, no_material_response)
    _write_json(ready_candidate_path, ready_candidate_response)
    _write_json(promoted_path, promoted_response)
    _write_json(blocked_path, blocked_response)
    _write_json(blocked_reset_alignment_path, blocked_reset_alignment_response)

    report = build_contribution_rollout_readiness_report(
        [no_material_path, ready_candidate_path, promoted_path, blocked_path, blocked_reset_alignment_path]
    )
    _write_json(output_dir / "latest.json", asdict(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate seeded contribution rollout-readiness response artifacts and summary report."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where seeded contribution responses and latest.json should be written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = generate_seeded_contribution_rollout_artifacts(args.output_dir)
    print(json.dumps(asdict(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
