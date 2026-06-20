from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.services.composite_metadata_store import composite_metadata_store  # noqa: E402
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores  # noqa: E402
from main import app  # noqa: E402
from scripts.seed_composite_performance_fixture import seed_canonical_composite_fixture  # noqa: E402

DEMO_COMPOSITE_FIXTURE_IDS = {"PB_GLOBAL_BALANCED_USD", "PB_GLOBAL_BALANCED_USD_DEGRADED"}


@dataclass(frozen=True)
class CertificationCheck:
    name: str
    endpoints: list[str]
    assertions: dict[str, Any]


def _post_json(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    if response.status_code != 200:
        raise AssertionError(f"{path} returned HTTP {response.status_code}: {response.text}")
    return response.json()


def _get_json(client: TestClient, path: str) -> dict[str, Any]:
    response = client.get(path)
    if response.status_code != 200:
        raise AssertionError(f"{path} returned HTTP {response.status_code}: {response.text}")
    return response.json()


def _close(name: str, actual: float | int | str, expected: float, *, abs_tol: float = 1e-9) -> float:
    actual_float = float(actual)
    if not math.isclose(actual_float, expected, rel_tol=0.0, abs_tol=abs_tol):
        raise AssertionError(f"{name} expected {expected}, got {actual_float}")
    return actual_float


def _cumulative_return(values: list[str]) -> Decimal:
    running = Decimal("1")
    for value in values:
        running *= Decimal("1") + Decimal(value)
    return running - Decimal("1")


def _cumulative_active_difference(portfolio_returns: list[str], benchmark_returns: list[str]) -> str:
    return f"{_cumulative_return(portfolio_returns) - _cumulative_return(benchmark_returns):.12f}"


def _prepare_demo_runtime() -> None:
    Path(get_settings().LINEAGE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    bootstrap_durable_metadata_stores()


def _expected_demo_capability_paths() -> set[str]:
    return {
        "/performance/workspace-summary",
        "/performance/twr",
        "/performance/mwr",
        "/performance/benchmark",
        "/integration/returns/series",
        "/performance/contribution",
        "/performance/attribution",
        "/performance/composites/twr",
        "/performance/mandate-health-context",
    }


def _assert_enabled_demo_surfaces(capabilities: dict[str, Any], expected_paths: set[str]) -> None:
    surfaces_by_path = {surface["path"]: surface for surface in capabilities["analytics_surfaces"]}
    missing_paths = sorted(expected_paths.difference(surfaces_by_path))
    if missing_paths:
        raise AssertionError(f"Capability registry is missing supported demo API paths: {missing_paths}")
    disabled_paths = sorted(path for path in expected_paths if surfaces_by_path[path].get("enabled") is not True)
    if disabled_paths:
        raise AssertionError(f"Capability registry marks demo API paths as disabled: {disabled_paths}")


def _certify_capability_registry(client: TestClient) -> CertificationCheck:
    health = _get_json(client, "/health")
    readiness = _get_json(client, "/health/ready")
    capabilities = _get_json(client, "/integration/capabilities?consumer_system=lotus-gateway&tenant_id=default")
    expected_paths = _expected_demo_capability_paths()
    _assert_enabled_demo_surfaces(capabilities, expected_paths)
    return CertificationCheck(
        name="capability_registry",
        endpoints=["/health", "/health/ready", "/integration/capabilities"],
        assertions={
            "health_status": health["status"],
            "readiness_status": readiness["status"],
            "supported_demo_paths": sorted(expected_paths),
        },
    )


def _certify_twr_contribution_attribution(client: TestClient) -> CertificationCheck:
    portfolio_id = "DEMO_API_CERT_STORY"
    twr = _post_json(
        client,
        "/performance/twr",
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": portfolio_id,
            "performance_start_date": "2024-12-31",
            "report_end_date": "2025-01-01",
            "metric_basis": "NET",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1020.0}],
            "include_benchmark": True,
            "benchmark": {
                "benchmark_id": "BMK_DEMO_API_CERT",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_TECH",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.015,
                        }
                    ],
                },
            },
        },
    )
    contribution = _post_json(
        client,
        "/performance/contribution",
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": portfolio_id,
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1020.0}],
            },
            "positions_data": [
                {
                    "position_id": "AAPL",
                    "meta": {"sector": "technology"},
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1020.0}],
                }
            ],
            "emit": {"timeseries": True},
        },
    )
    attribution = _post_json(
        client,
        "/performance/attribution",
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": portfolio_id,
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_groups_data": [
                {
                    "key": {"sector": "technology"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 1.0}],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "technology"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
                }
            ],
        },
    )
    twr_period = twr["results_by_period"]["YTD"]
    contribution_period = contribution["results_by_period"]["ITD"]
    attribution_period = attribution["results_by_period"]["ITD"]
    portfolio_return = _close("portfolio return", twr_period["portfolio"]["summary"]["period_return"]["base"], 2.0)
    benchmark_return = _close("benchmark return", twr_period["benchmark"]["summary"]["period_return"]["base"], 1.5)
    active_return = _close("active return", twr_period["relative_performance"]["summary"]["period_return"]["base"], 0.5)
    contribution_total = _close("contribution total", contribution_period["total_contribution"], portfolio_return)
    attribution_active = _close(
        "attribution active return",
        attribution_period["reconciliation"]["total_active_return"],
        active_return,
    )
    attribution_effects = _close(
        "attribution effects",
        attribution_period["reconciliation"]["sum_of_effects"],
        active_return,
    )
    return CertificationCheck(
        name="twr_contribution_attribution_story",
        endpoints=["/performance/twr", "/performance/contribution", "/performance/attribution"],
        assertions={
            "portfolio_return_pct": portfolio_return,
            "benchmark_return_pct": benchmark_return,
            "active_return_pct": active_return,
            "contribution_total_pct": contribution_total,
            "attribution_active_return_pct": attribution_active,
            "attribution_sum_of_effects_pct": attribution_effects,
        },
    )


def _certify_mwr(client: TestClient) -> CertificationCheck:
    body = _post_json(
        client,
        "/performance/mwr",
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "DEMO_API_CERT_MWR",
            "begin_mv": 100000.0,
            "end_mv": 115000.0,
            "as_of": "2025-12-31",
            "cash_flows": [{"amount": 10000.0, "date": "2025-03-15"}, {"amount": -5000.0, "date": "2025-09-20"}],
            "mwr_method": "XIRR",
            "annualization": {"enabled": True, "basis": "ACT/365"},
        },
    )
    if body["status"] != "CALCULATED" or body["method"] != "XIRR" or body["convergence"]["converged"] is not True:
        raise AssertionError("MWR demo certification expected a converged CALCULATED XIRR response")
    return CertificationCheck(
        name="mwr_xirr",
        endpoints=["/performance/mwr"],
        assertions={
            "money_weighted_return_pct": _close("MWR XIRR", body["money_weighted_return"], 11.71492554, abs_tol=1e-6),
            "method": body["method"],
            "status": body["status"],
            "converged": body["convergence"]["converged"],
        },
    )


def _certify_benchmark(client: TestClient) -> CertificationCheck:
    body = _post_json(
        client,
        "/performance/benchmark",
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_DEMO_API_CERT",
            "benchmark_start_date": "2026-01-02",
            "report_end_date": "2026-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily", "monthly"]}],
            "input_mode": "stateless",
            "return_source": "calculated",
            "output": {"include_timeseries": True},
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "component_return": 0.02},
                    {"component_id": "IDX_B", "perf_date": "2026-01-02", "weight_bop": 0.4, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2026-01-03", "weight_bop": 0.6, "component_return": 0.01},
                    {"component_id": "IDX_B", "perf_date": "2026-01-03", "weight_bop": 0.4, "component_return": 0.005},
                ],
            },
        },
    )
    period = body["results_by_period"]["ITD"]
    component_count = len(period["component_contributions"])
    if component_count != 4:
        raise AssertionError(f"Benchmark certification expected 4 component contribution rows, got {component_count}")
    return CertificationCheck(
        name="benchmark_calculated",
        endpoints=["/performance/benchmark"],
        assertions={
            "benchmark_return_pct": _close(
                "benchmark calculated return",
                period["benchmark"]["summary"]["period_return"]["base"],
                2.4128,
            ),
            "component_contribution_count": component_count,
            "return_source": body["return_source"],
        },
    )


def _certify_returns_series(client: TestClient) -> CertificationCheck:
    body = _post_json(
        client,
        "/integration/returns/series",
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "DEMO_DPM_EUR_001",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "input_mode": "stateless",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                    {"date": "2026-02-24", "return_value": "0.0050"},
                    {"date": "2026-02-25", "return_value": "-0.0025"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-23", "return_value": "0.0010"},
                    {"date": "2026-02-24", "return_value": "0.0012"},
                    {"date": "2026-02-25", "return_value": "0.0014"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-23", "return_value": "0.0001"},
                    {"date": "2026-02-24", "return_value": "0.0001"},
                    {"date": "2026-02-25", "return_value": "0.0001"},
                ],
            },
        },
    )
    active_returns = [point["return_value"] for point in body["series"]["active_returns"]]
    portfolio_returns = [point["return_value"] for point in body["series"]["portfolio_returns"]]
    benchmark_returns = [point["return_value"] for point in body["series"]["benchmark_returns"]]
    expected_active_returns = ["0.009000000000", "0.003800000000", "-0.003900000000"]
    if active_returns != expected_active_returns:
        raise AssertionError(f"Returns-series active returns drifted: {active_returns}")
    cumulative_active = _cumulative_active_difference(portfolio_returns, benchmark_returns)
    if body["series"]["cumulative_active_returns"][-1]["return_value"] != cumulative_active:
        raise AssertionError("Returns-series cumulative active return no longer reconciles portfolio less benchmark")
    return CertificationCheck(
        name="returns_series",
        endpoints=["/integration/returns/series"],
        assertions={
            "active_returns": active_returns,
            "cumulative_active_return_final": cumulative_active,
            "coverage_ratio": body["diagnostics"]["coverage"]["coverage_ratio"],
        },
    )


def _certify_workspace_summary(client: TestClient) -> CertificationCheck:
    body = _post_json(
        client,
        "/performance/workspace-summary",
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "DEMO_API_CERT_WORKSPACE",
            "report_end_date": "2026-01-03",
            "performance_start_date": "2026-01-01",
            "report_start_date": "2026-01-01",
            "input_mode": "stateless",
            "mwr_method": "DIETZ",
            "annualization": {"enabled": False, "basis": "ACT/365"},
            "periods": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "stateless_input": {
                "valuation_points": [
                    {"perf_date": "2026-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                    {"perf_date": "2026-01-02", "begin_mv": 1010.0, "bod_cf": 100.0, "end_mv": 1121.0},
                    {
                        "perf_date": "2026-01-03",
                        "begin_mv": 1121.0,
                        "eod_cf": -50.0,
                        "mgmt_fees": -10.0,
                        "end_mv": 1071.0,
                    },
                ]
            },
            "include_benchmark": True,
            "benchmark": {
                "benchmark_id": "BMK_DEMO_API_CERT_WORKSPACE",
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2026-01-01", "benchmark_return": 0.005},
                        {"perf_date": "2026-01-02", "benchmark_return": 0.004},
                        {"perf_date": "2026-01-03", "benchmark_return": -0.002},
                    ],
                },
            },
        },
    )
    period = body["results_by_period"]["EXPLICIT"]
    net = period["portfolio_twr"]["net"]
    benchmark = period["benchmark"]
    active = period["active"]
    mwr = period["money_weighted_return"]
    expected_economics = {
        "begin_market_value": 1000.0,
        "end_market_value": 1071.0,
        "beginning_cash_flow": 100.0,
        "ending_cash_flow": -50.0,
        "fees": -10.0,
        "net_cash_flow": 50.0,
        "flow_adjusted_end_market_value": 1021.0,
    }
    if net["summary"]["economics"] != expected_economics:
        raise AssertionError(f"Workspace economics drifted: {net['summary']['economics']}")
    return CertificationCheck(
        name="workspace_summary",
        endpoints=["/performance/workspace-summary"],
        assertions={
            "active_net_return_pct": _close(
                "workspace active net",
                active["net"]["period_return"]["base"],
                net["summary"]["period_return"]["base"] - benchmark["summary"]["period_return"]["base"],
            ),
            "mwr_period_return_pct": _close("workspace MWR", mwr["period_return"], mwr["cumulative_return"]),
            "input_rows": body["audit"]["counts"]["input_rows"],
            "periods_resolved": body["audit"]["counts"]["periods_resolved"],
        },
    )


def _certify_mandate_health_context(client: TestClient) -> CertificationCheck:
    body = _post_json(
        client,
        "/performance/mandate-health-context",
        {
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "as_of_date": "2026-02-27",
            "period_name": "YTD",
            "portfolio_period_return": "0.20",
            "benchmark_period_return": "1.50",
            "active_return_attention_threshold": "-1.00",
        },
    )
    if body["health_state"] != "attention" or body["threshold_breached"] is not True:
        raise AssertionError("Mandate health context should flag active-return attention")
    return CertificationCheck(
        name="mandate_health_context",
        endpoints=["/performance/mandate-health-context"],
        assertions={
            "health_state": body["health_state"],
            "threshold_breached": body["threshold_breached"],
            "active_return_pct": _close("mandate active return", body["source_metric"]["active_return"], -1.30),
            "source_metrics_product": body["methodology_posture"]["source_metrics_product"],
        },
    )


def _certify_composite_twr(client: TestClient) -> CertificationCheck:
    bootstrap_durable_metadata_stores()
    composite_metadata_store.clear_records_for_composites(DEMO_COMPOSITE_FIXTURE_IDS)
    seed_canonical_composite_fixture()
    body = _post_json(
        client,
        "/performance/composites/twr",
        {
            "calculation_id": str(uuid4()),
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "period_start": "2026-01-01",
            "period_end": "2026-02-28",
        },
    )
    if body["status"] != "READY":
        raise AssertionError(f"Composite TWR expected READY, got {body['status']}")
    if [period["member_count"] for period in body["periods"]] != [2, 2]:
        raise AssertionError("Composite seed should produce two ready members in each certified period")
    return CertificationCheck(
        name="composite_twr",
        endpoints=["/performance/composites/twr"],
        assertions={
            "status": body["status"],
            "cumulative_return": f"{_close('composite cumulative return', body['cumulative_return'], 0.0455):.12f}",
            "period_count": len(body["periods"]),
            "methodology": body["methodology"],
        },
    )


def certify_demo_apis() -> dict[str, Any]:
    _prepare_demo_runtime()
    with TestClient(app) as client:
        checks = [
            _certify_capability_registry(client),
            _certify_twr_contribution_attribution(client),
            _certify_mwr(client),
            _certify_benchmark(client),
            _certify_returns_series(client),
            _certify_workspace_summary(client),
            _certify_mandate_health_context(client),
            _certify_composite_twr(client),
        ]
    api_call_count = sum(len(check.endpoints) for check in checks)
    return {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "status": "passed",
        "api_call_count": api_call_count,
        "feature_families": [
            "capabilities",
            "twr",
            "mwr",
            "benchmark",
            "returns_series",
            "contribution",
            "attribution",
            "workspace_summary",
            "mandate_health_context",
            "composite_twr",
        ],
        "checks": [asdict(check) for check in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one deterministic request-level certification for demo-critical Lotus Performance APIs."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/demo-api-certification/latest.json"),
        help="Path for machine-readable certification evidence.",
    )
    args = parser.parse_args()
    report = certify_demo_apis()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Demo API certification passed: checks={len(report['checks'])}, api_calls={report['api_call_count']}")
    print(f"Evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
