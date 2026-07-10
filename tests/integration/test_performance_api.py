# tests/integration/test_performance_api.py
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest

from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import PerformanceRequest
from app.models.twr_requests import TWRAnalyticsRequest, TWRResolvedExecutionRequest
from app.observability_contracts import (
    PERFORMANCE_ANALYTICS_FRESHNESS_METRIC_LABELS,
    PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS,
)
from app.services.calculation_engine_version import calculation_engine_version
from app.services.twr_calculation_service import generate_twr_request_hashes
from app.services.twr_mode_service import ResolvedTWRRequest
from core.repro import generate_canonical_hash_from_value
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from main import app

_EXPECTED_SUPPORTABILITY_METRIC_LABELS = list(PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS)
_FORBIDDEN_METRIC_LABELS = {
    "portfolio_id",
    "account_id",
    "client_id",
    "correlation_id",
    "trace_id",
    "transaction_id",
    "security_id",
    "benchmark_id",
    "calculation_id",
    "request_body",
    "response_body",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_twr_reports_reset_events_when_requested(client):
    """
    Tests that when a reset occurs and the policy is enabled,
    the reset_events list is correctly populated in the response.
    """
    # This payload is based on the 'long_flip_scenario' which triggers an NCTRL_1 reset
    payload = {
        "portfolio_id": "RESET_SCENARIO_TEST",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "metric_basis": "GROSS",
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
            {"perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
            {"perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
            {"perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
        ],
        "reset_policy": {"emit": True},
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_results = data["results_by_period"]["SI"]

    assert "reset_events" in itd_results
    assert itd_results["reset_events"] is not None
    assert len(itd_results["reset_events"]) == 2

    reset_reasons_by_date = {event["date"]: event["reason"] for event in itd_results["reset_events"]}
    assert "NCTRL_1" in reset_reasons_by_date["2025-01-02"]
    assert "NCTRL_4" in reset_reasons_by_date["2025-01-03"]
    assert data["calculation_supportability"] == {
        "state": "ready",
        "reason": "calculation_complete",
        "freshness_bucket": "current",
        "input_row_count": 4,
        "resolved_period_count": 1,
        "benchmark_row_count": 0,
        "source_quality_evidence": None,
        "metric_labels": _EXPECTED_SUPPORTABILITY_METRIC_LABELS,
    }

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "lotus_performance_calculation_supportability_total" in metrics.text
    assert 'operation="twr"' in metrics.text
    assert 'supportability_state="ready"' in metrics.text
    assert 'reason="calculation_complete"' in metrics.text
    assert 'freshness_bucket="current"' in metrics.text
    assert "lotus_analytics_freshness_bucket_total" in metrics.text
    assert (
        'lotus_analytics_freshness_bucket_total{freshness_bucket="current",'
        'operation="twr",service="lotus-performance",supportability_state="ready"}'
    ) in metrics.text


def test_twr_supportability_metric_labels_are_bounded_and_support_safe(client):
    payload = {
        "portfolio_id": "TWR_LABEL_BOUNDARY_TEST",
        "performance_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "metric_basis": "NET",
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    assert response.json()["calculation_supportability"]["metric_labels"] == _EXPECTED_SUPPORTABILITY_METRIC_LABELS
    metrics_text = generate_latest(REGISTRY).decode("utf-8")
    supportability_lines = [
        line
        for line in metrics_text.splitlines()
        if line.startswith("lotus_performance_calculation_supportability_total{") and 'operation="twr"' in line
    ]
    freshness_lines = [
        line
        for line in metrics_text.splitlines()
        if line.startswith("lotus_analytics_freshness_bucket_total{") and 'operation="twr"' in line
    ]

    assert supportability_lines
    assert freshness_lines
    for label in PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS:
        assert f"{label}=" in supportability_lines[-1]
    for label in PERFORMANCE_ANALYTICS_FRESHNESS_METRIC_LABELS:
        assert f"{label}=" in freshness_lines[-1]
    for label in _FORBIDDEN_METRIC_LABELS:
        assert f"{label}=" not in supportability_lines[-1]
        assert f"{label}=" not in freshness_lines[-1]


def test_workspace_summary_endpoint_returns_multi_horizon_summary_blocks(client):
    payload = {
        "portfolio_id": "WORKSPACE_SUMMARY_TEST",
        "report_end_date": "2025-01-10",
        "performance_start_date": "2025-01-01",
        "input_mode": "stateless",
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                {"perf_date": "2025-01-10", "begin_mv": 1010.0, "end_mv": 1030.2},
            ]
        },
        "periods": [
            {"period": "1D", "frequencies": ["daily"]},
            {"period": "YTD", "frequencies": ["daily"]},
        ],
        "include_benchmark": True,
        "benchmark": {
            "benchmark_id": "BMK-1",
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.008},
                    {"perf_date": "2025-01-10", "benchmark_return": 0.012},
                ],
            },
        },
    }

    response = client.post("/performance/workspace-summary", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert set(data["results_by_period"]) == {"1D", "YTD"}
    one_day = data["results_by_period"]["1D"]
    assert one_day["portfolio_twr"]["net"]["summary"]["economics"]["begin_market_value"] == pytest.approx(1010.0)
    assert one_day["portfolio_twr"]["net"]["summary"]["period_return"]["base"] == pytest.approx(
        one_day["portfolio_twr"]["net"]["summary"]["cumulative_return"]["base"]
    )
    assert one_day["portfolio_twr"]["net"]["summary"]["annualized_return"]["base"] == pytest.approx(
        one_day["portfolio_twr"]["net"]["summary"]["cumulative_return"]["base"]
    )
    assert one_day["portfolio_twr"]["gross"]["summary"]["cumulative_return"]["base"] == pytest.approx(
        one_day["portfolio_twr"]["net"]["summary"]["cumulative_return"]["base"]
    )
    assert one_day["benchmark"]["benchmark_id"] == "BMK-1"
    assert one_day["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(
        one_day["benchmark"]["summary"]["cumulative_return"]["base"]
    )
    assert one_day["active"]["net"]["period_return"]["base"] == pytest.approx(
        one_day["portfolio_twr"]["net"]["summary"]["period_return"]["base"]
        - one_day["benchmark"]["summary"]["period_return"]["base"]
    )
    assert one_day["active"]["net"]["cumulative_return"]["base"] == pytest.approx(
        one_day["portfolio_twr"]["net"]["summary"]["cumulative_return"]["base"]
        - one_day["benchmark"]["summary"]["cumulative_return"]["base"]
    )
    assert "period_return" in one_day["portfolio_twr"]["net"]["breakdowns"]["daily"][0]
    assert one_day["money_weighted_return"]["annualized_return"] == pytest.approx(
        one_day["money_weighted_return"]["cumulative_return"]
    )
    assert one_day["money_weighted_return"]["period_return"] == pytest.approx(
        one_day["money_weighted_return"]["cumulative_return"]
    )

    ytd = data["results_by_period"]["YTD"]
    assert ytd["portfolio_twr"]["net"]["breakdowns"]["daily"][0]["economics"]["begin_market_value"] == pytest.approx(
        1000.0
    )
    assert "period_return" in ytd["benchmark"]["breakdowns"]["daily"][0]
    assert data["audit"]["counts"]["input_rows"] == 2


def test_workspace_summary_endpoint_reconciles_all_summary_figures(client):
    valuation_points = [
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
    benchmark_return_points = [
        {"perf_date": "2026-01-01", "benchmark_return": 0.005},
        {"perf_date": "2026-01-02", "benchmark_return": 0.004},
        {"perf_date": "2026-01-03", "benchmark_return": -0.002},
    ]
    payload = {
        "portfolio_id": "WORKSPACE_SUMMARY_FIGURE_CERT",
        "report_end_date": "2026-01-03",
        "performance_start_date": "2026-01-01",
        "report_start_date": "2026-01-01",
        "input_mode": "stateless",
        "mwr_method": "DIETZ",
        "annualization": {"enabled": False, "basis": "ACT/365"},
        "periods": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "stateless_input": {"valuation_points": valuation_points},
        "include_benchmark": True,
        "benchmark": {
            "benchmark_id": "BMK_WORKSPACE_FIGURE_CERT",
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": benchmark_return_points,
            },
        },
    }
    direct_twr_payload = {
        "input_mode": "stateless",
        "portfolio_id": "WORKSPACE_SUMMARY_FIGURE_CERT",
        "performance_start_date": "2026-01-01",
        "report_start_date": "2026-01-01",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "stateless_input": {"valuation_points": valuation_points},
        "annualization": {"enabled": False, "basis": "ACT/365"},
    }
    direct_mwr_payload = {
        "input_mode": "stateless",
        "portfolio_id": "WORKSPACE_SUMMARY_FIGURE_CERT",
        "as_of": "2026-01-03",
        "start_date": "2026-01-01",
        "mwr_method": "DIETZ",
        "annualization": {"enabled": False, "basis": "ACT/365"},
        "stateless_input": {
            "begin_mv": 1000.0,
            "end_mv": 1071.0,
            "cash_flows": [
                {"amount": 100.0, "date": "2026-01-02"},
                {"amount": -50.0, "date": "2026-01-03"},
            ],
        },
    }
    direct_benchmark_payload = {
        "benchmark_id": "BMK_WORKSPACE_FIGURE_CERT",
        "benchmark_start_date": "2026-01-01",
        "report_start_date": "2026-01-01",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "vendor_series",
        "annualization": {"enabled": False, "basis": "ACT/365"},
        "stateless_input": {
            "benchmark_currency": "USD",
            "benchmark_return_points": benchmark_return_points,
        },
    }

    direct_net_response = client.post("/performance/twr", json={**direct_twr_payload, "metric_basis": "NET"})
    direct_gross_response = client.post("/performance/twr", json={**direct_twr_payload, "metric_basis": "GROSS"})
    direct_mwr_response = client.post("/performance/mwr", json=direct_mwr_payload)
    direct_benchmark_response = client.post("/performance/benchmark", json=direct_benchmark_payload)
    response = client.post("/performance/workspace-summary", json=payload)

    assert direct_net_response.status_code == 200
    assert direct_gross_response.status_code == 200
    assert direct_mwr_response.status_code == 200
    assert direct_benchmark_response.status_code == 200
    assert response.status_code == 200
    direct_net = direct_net_response.json()["results_by_period"]["EXPLICIT"]["portfolio"]
    direct_gross = direct_gross_response.json()["results_by_period"]["EXPLICIT"]["portfolio"]
    direct_mwr = direct_mwr_response.json()
    direct_benchmark = direct_benchmark_response.json()["results_by_period"]["EXPLICIT"]["benchmark"]
    body = response.json()
    period = body["results_by_period"]["EXPLICIT"]
    net = period["portfolio_twr"]["net"]
    gross = period["portfolio_twr"]["gross"]
    benchmark = period["benchmark"]
    active = period["active"]
    mwr = period["money_weighted_return"]
    economics = net["summary"]["economics"]

    assert economics == {
        "begin_market_value": 1000.0,
        "end_market_value": 1071.0,
        "beginning_cash_flow": 100.0,
        "ending_cash_flow": -50.0,
        "fees": -10.0,
        "net_cash_flow": 50.0,
        "flow_adjusted_end_market_value": 1021.0,
    }
    assert net["summary"]["period_return"]["base"] == pytest.approx(direct_net["summary"]["period_return"]["base"])
    assert net["summary"]["cumulative_return"]["base"] == pytest.approx(
        direct_net["summary"]["cumulative_return"]["base"]
    )
    assert gross["summary"]["period_return"]["base"] == pytest.approx(direct_gross["summary"]["period_return"]["base"])
    assert gross["summary"]["cumulative_return"]["base"] == pytest.approx(
        direct_gross["summary"]["cumulative_return"]["base"]
    )
    assert benchmark["summary"]["period_return"]["base"] == pytest.approx(
        direct_benchmark["summary"]["period_return"]["base"]
    )
    assert benchmark["summary"]["cumulative_return"]["base"] == pytest.approx(
        direct_benchmark["summary"]["cumulative_return"]["base"]
    )
    assert active["net"]["period_return"]["base"] == pytest.approx(
        net["summary"]["period_return"]["base"] - benchmark["summary"]["period_return"]["base"]
    )
    assert active["gross"]["period_return"]["base"] == pytest.approx(
        gross["summary"]["period_return"]["base"] - benchmark["summary"]["period_return"]["base"]
    )
    assert mwr["period_return"] == pytest.approx(direct_mwr["money_weighted_return"])
    assert mwr["cumulative_return"] == pytest.approx(mwr["period_return"])
    assert mwr["annualized_return"] == pytest.approx(mwr["period_return"])
    assert mwr["economics"] == economics
    assert [item["period"] for item in net["breakdowns"]["daily"]] == [
        item["period"] for item in direct_net["breakdowns"]["daily"]
    ]
    for workspace_item, direct_item in zip(net["breakdowns"]["daily"], direct_net["breakdowns"]["daily"]):
        assert workspace_item["period_return"]["base"] == pytest.approx(direct_item["period_return"]["base"])
        assert workspace_item["cumulative_return"]["base"] == pytest.approx(direct_item["cumulative_return"]["base"])
    for workspace_item, direct_item in zip(gross["breakdowns"]["daily"], direct_gross["breakdowns"]["daily"]):
        assert workspace_item["period_return"]["base"] == pytest.approx(direct_item["period_return"]["base"])
        assert workspace_item["cumulative_return"]["base"] == pytest.approx(direct_item["cumulative_return"]["base"])
    for workspace_item, direct_item in zip(benchmark["breakdowns"]["daily"], direct_benchmark["breakdowns"]["daily"]):
        assert workspace_item["period_return"]["base"] == pytest.approx(direct_item["period_return"]["base"])
        assert workspace_item["cumulative_return"]["base"] == pytest.approx(direct_item["cumulative_return"]["base"])
    assert body["audit"]["counts"]["input_rows"] == 3
    assert body["audit"]["counts"]["periods_resolved"] == 1
    assert "Benchmark summary uses stateless benchmark input" in body["diagnostics"]["notes"][-1]


def test_workspace_summary_endpoint_annualizes_periods_longer_than_one_year(client):
    payload = {
        "portfolio_id": "WORKSPACE_SUMMARY_2Y_TEST",
        "report_end_date": "2026-12-31",
        "performance_start_date": "2024-12-31",
        "input_mode": "stateless",
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1000.0},
                {"perf_date": "2026-12-31", "begin_mv": 1000.0, "end_mv": 1210.0},
            ]
        },
        "periods": [{"period": "2Y", "frequencies": ["yearly"]}],
    }

    response = client.post("/performance/workspace-summary", json=payload)
    assert response.status_code == 200
    data = response.json()

    summary = data["results_by_period"]["2Y"]["portfolio_twr"]["net"]["summary"]
    assert summary["period_return"]["base"] == pytest.approx(21.0)
    cumulative = summary["cumulative_return"]["base"]
    annualized = summary["annualized_return"]["base"]

    assert cumulative == pytest.approx(21.0)
    expected_annualized = ((1 + 0.21) ** (365 / 730) - 1) * 100
    assert annualized == pytest.approx(expected_annualized, rel=1e-3)


def test_workspace_summary_endpoint_honors_disabled_annualization_for_multi_year_returns(client):
    payload = {
        "portfolio_id": "WORKSPACE_SUMMARY_2Y_ANNUALIZATION_DISABLED",
        "report_end_date": "2026-12-31",
        "performance_start_date": "2024-12-31",
        "input_mode": "stateless",
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1000.0},
                {"perf_date": "2026-12-31", "begin_mv": 1000.0, "end_mv": 1210.0},
            ]
        },
        "periods": [{"period": "2Y", "frequencies": ["yearly"]}],
        "annualization": {"enabled": False, "basis": "ACT/365"},
        "include_benchmark": True,
        "benchmark": {
            "benchmark_id": "BMK_WORKSPACE_ANNUALIZATION_DISABLED",
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.05},
                    {"perf_date": "2026-12-31", "benchmark_return": 0.05},
                ],
            },
        },
    }

    response = client.post("/performance/workspace-summary", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["meta"]["annualization"]["enabled"] is False
    period = data["results_by_period"]["2Y"]
    portfolio_summary = period["portfolio_twr"]["net"]["summary"]
    benchmark_summary = period["benchmark"]["summary"]
    active_summary = period["active"]["net"]

    assert portfolio_summary["annualized_return"]["base"] == pytest.approx(
        portfolio_summary["cumulative_return"]["base"]
    )
    assert benchmark_summary["annualized_return"]["base"] == pytest.approx(
        benchmark_summary["cumulative_return"]["base"]
    )
    assert active_summary["annualized_return"]["base"] == pytest.approx(active_summary["cumulative_return"]["base"])


def test_workspace_summary_endpoint_returns_async_accepted_when_threshold_exceeded(client):
    settings = get_settings()
    original_threshold = settings.WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT
    settings.WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT = 1

    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "WORKSPACE_SUMMARY_ASYNC",
        "report_end_date": "2025-01-10",
        "performance_start_date": "2025-01-01",
        "input_mode": "stateless",
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                {"perf_date": "2025-01-10", "begin_mv": 1010.0, "end_mv": 1030.2},
            ]
        },
        "periods": [{"period": "YTD", "frequencies": ["daily"]}],
    }

    try:
        response = client.post("/performance/workspace-summary", json=payload)
        assert response.status_code == 202
        body = response.json()
        assert body["poll_path"].endswith(payload["calculation_id"])
        pending = client.get(body["result_path"])
        assert pending.status_code == 202
    finally:
        settings.WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT = original_threshold


def test_calculate_twr_endpoint_with_annualization(client):
    """Tests that a request with annualization enabled correctly returns annualized figures."""
    payload = {
        "portfolio_id": "ANNUALIZATION_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-03-31",
        "analyses": [{"period": "QTD", "frequencies": ["quarterly"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-03-31", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "annualization": {"enabled": True, "basis": "ACT/365"},
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    summary = data["results_by_period"]["QTD"]["portfolio"]["breakdowns"]["quarterly"][0]

    assert summary["annualized_return"] is not None
    assert summary["period_return"]["base"] == pytest.approx(2.01)
    # 90 days in Q1 2025. Expected: (1.0201 ** (365 / 90)) - 1 = 8.40545...%
    assert summary["annualized_return"]["base"] == pytest.approx(8.40545, abs=1e-5)


def test_calculate_twr_endpoint_legacy_path_and_diagnostics(client):
    """Tests the /performance/twr endpoint using the new 'analyses' structure and verifies the shared response footer."""
    payload = {
        "portfolio_id": "PORT_STANDARD_GROWTH",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily", "monthly"]}],
        "calculation_id": str(uuid4()),
        "rounding_precision": 6,
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 100000.0, "end_mv": 101000.0},
            {"perf_date": "2025-01-02", "begin_mv": 101000.0, "end_mv": 102010.0},
            {"perf_date": "2025-01-03", "begin_mv": 102010.0, "end_mv": 100989.9},
            {"perf_date": "2025-01-04", "begin_mv": 100989.9, "bod_cf": 25000.0, "end_mv": 127249.29},
            {"perf_date": "2025-01-05", "begin_mv": 127249.29, "end_mv": 125976.7971},
        ],
    }

    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200

    response_data = response.json()
    assert "calculation_id" in response_data
    assert "results_by_period" in response_data
    assert "YTD" in response_data["results_by_period"]
    ytd_results = response_data["results_by_period"]["YTD"]
    assert "portfolio" in ytd_results
    assert "breakdowns" in ytd_results["portfolio"]

    assert "meta" in response_data
    assert response_data["meta"]["engine_version"] is not None
    assert "diagnostics" in response_data
    assert response_data["diagnostics"]["nip_days"] == 0
    assert "nip_rule_delta_days" in response_data["diagnostics"]
    assert "nctrl4_reset_days" in response_data["diagnostics"]
    assert "nctrl4_exclusive_reset_days" in response_data["diagnostics"]
    assert "account_reset_shadow_days" in response_data["diagnostics"]
    assert "sod_reset_shadow_days" in response_data["diagnostics"]
    assert "shadow_reset_overlap_days" in response_data["diagnostics"]
    assert "shadow_only_candidate_reset_days" in response_data["diagnostics"]
    assert "active_reset_with_shadow_days" in response_data["diagnostics"]
    assert "nip_days_since_last_reset" in response_data["diagnostics"]
    assert "valid_days_since_last_reset" in response_data["diagnostics"]
    assert "methodology_shadows" in response_data["diagnostics"]["samples"]
    assert "audit" in response_data
    assert response_data["audit"]["counts"]["input_rows"] == 5

    daily_breakdown = ytd_results["portfolio"]["breakdowns"]["daily"]
    no_flow_evidence = daily_breakdown[0]["calculation_evidence"]
    assert no_flow_evidence["calculation_method"] == "flow_neutralized_daily_twr"
    assert no_flow_evidence["denominator_basis"] == "absolute_begin_mv_plus_bod_cf"
    assert no_flow_evidence["flow_timing_convention"] == "bod_flows_in_denominator_eod_flows_excluded_from_denominator"
    assert no_flow_evidence["begin_mv"] == 100000.0
    assert no_flow_evidence["end_mv"] == 101000.0
    assert no_flow_evidence["adjusted_capital"] == 100000.0
    assert no_flow_evidence["performance_pnl"] == 1000.0
    assert no_flow_evidence["daily_return"] == pytest.approx(1.0)
    assert no_flow_evidence["status"] == "calculated"
    assert no_flow_evidence["reason_codes"] == ["FLOW_NEUTRALIZED_DAILY_RETURN"]

    deposit_evidence = daily_breakdown[3]["calculation_evidence"]
    assert deposit_evidence["bod_cf"] == 25000.0
    assert deposit_evidence["eod_cf"] == 0.0
    assert deposit_evidence["external_inflows"] == 25000.0
    assert deposit_evidence["external_outflows"] == 0.0
    assert deposit_evidence["adjusted_capital"] == pytest.approx(125989.9)
    assert deposit_evidence["performance_pnl"] == pytest.approx(1259.39)
    assert deposit_evidence["daily_return"] == pytest.approx(0.999596, abs=1e-6)


def test_twr_daily_calculation_evidence_handles_same_day_deposit_and_withdrawal(client):
    payload = {
        "portfolio_id": "TWR_DAILY_EVIDENCE",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {
                "perf_date": "2025-01-01",
                "begin_mv": 1000.0,
                "bod_cf": 200.0,
                "eod_cf": -100.0,
                "mgmt_fees": 2.0,
                "end_mv": 1113.0,
            }
        ],
    }

    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200

    daily_item = response.json()["results_by_period"]["YTD"]["portfolio"]["breakdowns"]["daily"][0]
    evidence = daily_item["calculation_evidence"]
    assert evidence["begin_mv"] == 1000.0
    assert evidence["bod_cf"] == 200.0
    assert evidence["eod_cf"] == -100.0
    assert evidence["external_inflows"] == 200.0
    assert evidence["external_outflows"] == 100.0
    assert evidence["management_fees"] == 2.0
    assert evidence["adjusted_capital"] == 1200.0
    assert evidence["performance_pnl"] == 15.0
    assert evidence["daily_return"] == pytest.approx(1.25)
    assert evidence["status"] == "calculated"
    assert evidence["warnings"] == []


def test_twr_industry_qa_links_daily_returns_instead_of_summing_them(client):
    payload = {
        "portfolio_id": "TWR_INDUSTRY_GEOMETRIC_LINKING",
        "performance_start_date": "2024-12-31",
        "metric_basis": "GROSS",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 110.0},
            {"perf_date": "2025-01-02", "begin_mv": 110.0, "end_mv": 99.0},
        ],
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    ytd = response.json()["results_by_period"]["YTD"]["portfolio"]
    daily_breakdown = ytd["breakdowns"]["daily"]
    day_1_return = daily_breakdown[0]["period_return"]["base"]
    day_2_return = daily_breakdown[1]["period_return"]["base"]
    arithmetic_sum = day_1_return + day_2_return

    assert day_1_return == pytest.approx(10.0)
    assert day_2_return == pytest.approx(-10.0)
    assert arithmetic_sum == pytest.approx(0.0)
    assert ytd["summary"]["period_return"]["base"] == pytest.approx(-1.0)
    assert daily_breakdown[1]["cumulative_return"]["base"] == pytest.approx(-1.0)
    for item in daily_breakdown:
        evidence = item["calculation_evidence"]
        assert evidence["status"] == "calculated"
        assert evidence["linkability_status"] == "linkable"
        assert evidence["reason_codes"] == ["FLOW_NEUTRALIZED_DAILY_RETURN"]


def test_calculate_twr_endpoint_multi_period(client):
    """Tests a multi-period request for MTD and YTD."""
    payload = {
        "portfolio_id": "MULTI_PERIOD_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-02-15",
        "analyses": [
            {"period": "MTD", "frequencies": ["monthly"]},
            {"period": "YTD", "frequencies": ["monthly"]},
        ],
        "valuation_points": [
            {"perf_date": "2025-01-15", "begin_mv": 1000.0, "end_mv": 1010.0},  # +1.0%
            {"perf_date": "2025-02-10", "begin_mv": 1010.0, "end_mv": 1030.2},  # +2.0%
        ],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "results_by_period" in data
    results = data["results_by_period"]
    assert "MTD" in results
    assert "YTD" in results

    mtd_monthly_breakdown = results["MTD"]["portfolio"]["breakdowns"]["monthly"]
    assert len(mtd_monthly_breakdown) == 1
    mtd_return = mtd_monthly_breakdown[0]["period_return"]["base"]
    assert mtd_return == pytest.approx(2.0)

    ytd_monthly_breakdown = results["YTD"]["portfolio"]["breakdowns"]["monthly"]
    assert len(ytd_monthly_breakdown) == 2
    jan_return = ytd_monthly_breakdown[0]["period_return"]["base"]
    feb_return = ytd_monthly_breakdown[1]["period_return"]["base"]

    assert jan_return == pytest.approx(1.0)
    assert feb_return == pytest.approx(2.0)

    compounded_ytd_return = ((1 + jan_return / 100) * (1 + feb_return / 100) - 1) * 100
    assert compounded_ytd_return == pytest.approx(3.02)


def test_calculate_twr_endpoint_multi_currency(client):
    """Tests an end-to-end multi-currency TWR request."""
    payload = {
        "portfolio_id": "MULTI_CCY_API_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "GROSS",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0},
            {"perf_date": "2025-01-02", "begin_mv": 102.0, "end_mv": 103.02},
        ],
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.05},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.08},
                {"date": "2025-01-02", "ccy": "EUR", "rate": 1.07},
            ]
        },
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_result = data["results_by_period"]["SI"]

    assert "portfolio" in itd_result
    assert itd_result["portfolio"]["summary"]["period_return"]["local"] == pytest.approx(3.02)
    assert itd_result["portfolio"]["summary"]["period_return"]["fx"] == pytest.approx(1.90476, abs=1e-5)
    assert itd_result["portfolio"]["summary"]["period_return"]["base"] == pytest.approx(4.98228, abs=1e-5)
    assert data["meta"]["report_ccy"] == "USD"


def test_calculate_twr_endpoint_with_data_policy(client):
    """Tests that a request with data_policy overrides and flagging works end-to-end."""
    payload = {
        "portfolio_id": "POLICY_TEST",
        "performance_start_date": "2024-12-27",
        "metric_basis": "NET",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2024-12-28", "begin_mv": 1000.0, "end_mv": 1001.0},
            {"perf_date": "2024-12-29", "begin_mv": 1001.0, "end_mv": 1002.0},
            {"perf_date": "2024-12-30", "begin_mv": 1002.0, "end_mv": 1003.0},
            {"perf_date": "2024-12-31", "begin_mv": 1003.0, "end_mv": 1004.0},
            {"perf_date": "2025-01-01", "begin_mv": 1004.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1005.0, "end_mv": 2000.0},
            {"perf_date": "2025-01-03", "begin_mv": 2000.0, "end_mv": 2020.0},
        ],
        "data_policy": {
            "overrides": {"market_values": [{"perf_date": "2025-01-01", "end_mv": 1005.0}]},
            "ignore_days": [{"entity_type": "PORTFOLIO", "entity_id": "POLICY_TEST", "dates": ["2025-01-03"]}],
            "outliers": {"enabled": True, "action": "FLAG", "params": {"mad_k": 3.0}},
        },
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_result = data["results_by_period"]["SI"]

    daily_breakdown = itd_result["portfolio"]["breakdowns"]["daily"]
    assert daily_breakdown[4]["period_return"]["base"] == pytest.approx(0.099602, abs=1e-6)
    assert daily_breakdown[6]["period_return"]["base"] == 0.0

    diags = data["diagnostics"]
    assert diags["policy"]["overrides"]["applied_mv_count"] == 1
    assert diags["policy"]["ignored_days_count"] == 1
    assert diags["policy"]["outliers"]["flagged_rows"] == 1


def test_twr_respects_include_timeseries_flag(client):
    """Tests that the include_timeseries flag correctly includes or excludes the daily_data block."""
    base_payload = {
        "portfolio_id": "TIMESERIES_FLAG_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }

    # Case 1: Flag is true
    payload_with = base_payload.copy()
    payload_with["output"] = {"include_timeseries": True}
    response_with = client.post("/performance/twr", json=payload_with)
    assert response_with.status_code == 200
    daily_breakdown_with = response_with.json()["results_by_period"]["YTD"]["portfolio"]["breakdowns"]["daily"][0]
    assert "daily_data" in daily_breakdown_with
    assert daily_breakdown_with["daily_data"] is not None
    assert daily_breakdown_with["calculation_evidence"]["adjusted_capital"] == 1000.0

    # Case 2: Flag is false
    payload_without = base_payload.copy()
    payload_without["output"] = {"include_timeseries": False}
    response_without = client.post("/performance/twr", json=payload_without)
    assert response_without.status_code == 200
    daily_breakdown_without = response_without.json()["results_by_period"]["YTD"]["portfolio"]["breakdowns"]["daily"][0]
    assert daily_breakdown_without.get("daily_data") is None
    assert daily_breakdown_without["calculation_evidence"]["adjusted_capital"] == 1000.0


def test_twr_response_includes_portfolio_summary_block(client):
    """Tests that the portfolio summary block is present for single-currency requests."""
    payload = {
        "portfolio_id": "PORTFOLIO_RETURN_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "report_ccy": "USD",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    ytd_result = data["results_by_period"]["YTD"]

    assert "portfolio" in ytd_result
    assert ytd_result["portfolio"]["summary"]["period_return"]["base"] == pytest.approx(2.01)
    assert ytd_result["portfolio"]["summary"]["period_return"]["fx"] == 0.0


def test_twr_supports_stateful_input_mode(client, monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-12-31",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "STATEFUL_TWR_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["input_mode"] == "stateful"
    source_quality = body["calculation_supportability"]["source_quality_evidence"]
    assert source_quality["source_owner"] == "lotus-core"
    assert source_quality["source_product"] == "PortfolioTimeseriesInput"
    assert source_quality["input_mode"] == "stateful"
    assert source_quality["quality_state"] == "clean"
    assert source_quality["observation_count"] == 2
    assert source_quality["valid_valuation_point_count"] == 2
    assert source_quality["warnings"] == []
    assert body["results_by_period"]["YTD"]["portfolio"]["summary"]["period_return"]["base"] == pytest.approx(2.01)


def test_twr_stateful_supportability_exposes_source_quality_warnings(client, monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-12-31",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                        "source_classification": "official",
                        "cash_flows": [{"cash_flow_type": "dividend", "amount": "5", "timing": "eod"}],
                    },
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1011",
                        "source_classification": "manual_adjustment",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": None,
                        "ending_market_value": "1020",
                        "source_classification": "official",
                    },
                    {"valuation_date": "2025-01-03", "beginning_market_value": "1011", "ending_market_value": "1021"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "STATEFUL_TWR_SOURCE_QUALITY",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    supportability = response.json()["calculation_supportability"]
    assert supportability["state"] == "stale"
    assert supportability["reason"] == "stale_source_observations"
    source_quality = supportability["source_quality_evidence"]
    assert source_quality["quality_state"] == "stale"
    assert source_quality["skipped_observation_count"] == 1
    assert source_quality["unsupported_cashflow_count"] == 1
    assert source_quality["source_conflict_count"] == 1
    assert source_quality["warnings"] == [
        "MISSING_VALUATION_POINTS",
        "UNSUPPORTED_CASHFLOW_LABELS",
        "SOURCE_DATE_CONFLICTS",
        "STALE_SOURCE_OBSERVATIONS",
    ]
    assert source_quality["source_classification_counts"] == {"manual_adjustment": 1, "official": 2}


def test_twr_supports_explicit_period_for_stateful_requests(client, monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-12-31",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1100"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1100", "ending_market_value": "1111"},
                    {
                        "valuation_date": "2025-01-03",
                        "beginning_market_value": "1111",
                        "ending_market_value": "1122.11",
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "STATEFUL_TWR_EXPLICIT",
        "performance_start_date": "2024-12-31",
        "report_start_date": "2025-01-02",
        "report_end_date": "2025-01-03",
        "metric_basis": "NET",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    explicit_result = body["results_by_period"]["EXPLICIT"]["portfolio"]
    assert explicit_result["summary"]["period_return"]["base"] == pytest.approx(2.01)
    assert [row["period"] for row in explicit_result["breakdowns"]["daily"]] == [
        "2025-01-02",
        "2025-01-03",
    ]


def test_twr_generates_calculation_id_when_omitted_for_benchmark_request(client):
    payload = {
        "portfolio_id": "TWR_BENCHMARK_GENERATED_ID",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "include_benchmark": True,
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "benchmark": {
            "benchmark_id": "BMK_GENERATED_ID",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-01-02", "weight_bop": 1.0, "component_return": 0.01},
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    generated_calculation_id = body["calculation_id"]
    assert generated_calculation_id
    assert body["meta"]["calculation_id"] == generated_calculation_id
    assert body["results_by_period"]["YTD"]["benchmark"]["benchmark_id"] == "BMK_GENERATED_ID"
    assert body["results_by_period"]["YTD"]["relative_performance"] is not None


def test_twr_supports_stateless_benchmark_request(client):
    payload = {
        "portfolio_id": "TWR_BENCHMARK_STATELESS",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "report_ccy": "USD",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "include_benchmark": True,
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "benchmark": {
            "benchmark_id": "BMK_STATELESS_1",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-01-02", "weight_bop": 1.0, "component_return": 0.015},
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    benchmark_context = body["benchmark_context"]
    assert benchmark_context["benchmark_id"] == "BMK_STATELESS_1"
    assert benchmark_context["benchmark_currency"] == "USD"
    assert benchmark_context["input_mode"] == "stateless"
    assert benchmark_context["return_source"] == "calculated"
    assert benchmark_context["supportability_evidence"] == {
        "return_source": "calculated",
        "input_mode": "stateless",
        "reporting_currency": "USD",
        "benchmark_currency": "USD",
        "currency_state": "single_currency",
        "calendar_alignment_state": "aligned",
        "portfolio_observation_count": 2,
        "benchmark_observation_count": 2,
        "overlapping_observation_count": 2,
        "missing_benchmark_date_count": 0,
        "missing_benchmark_dates_sample": [],
        "extra_benchmark_date_count": 0,
        "extra_benchmark_dates_sample": [],
        "warning_codes": [],
    }
    benchmark_block = body["results_by_period"]["YTD"]["benchmark"]
    relative_block = body["results_by_period"]["YTD"]["relative_performance"]
    assert benchmark_block["benchmark_id"] == "BMK_STATELESS_1"
    assert benchmark_block["input_mode"] == "stateless"
    assert benchmark_block["benchmark_currency"] == "USD"
    assert benchmark_block["summary"]["period_return"]["base"] == pytest.approx(2.515)
    assert relative_block["summary"]["period_return"]["base"] == pytest.approx(-0.505)
    assert relative_block["summary"]["cumulative_return"]["base"] == pytest.approx(-0.505)


def test_twr_supports_stateful_benchmark_assignment(client, monkeypatch):
    class _StatefulBenchmarkStub:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": "BMK_ASSIGNED"}

        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "benchmark_id": "BMK_ASSIGNED",
                    "benchmark_currency": "USD",
                    "segments": [
                        {
                            "index_id": "IDX_USD",
                            "composition_weight": "1.0",
                            "composition_effective_from": "2024-12-31",
                            "composition_effective_to": "2025-01-31",
                        }
                    ],
                },
            )

        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "points": [
                        {"series_date": "2024-12-31", "index_price": "100", "series_currency": "USD"},
                        {"series_date": "2025-01-01", "index_price": "101", "series_currency": "USD"},
                        {"series_date": "2025-01-02", "index_price": "102.01", "series_currency": "USD"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )

        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            return 200, {"points": []}

        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "unused"}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _StatefulBenchmarkStub(),  # noqa: ARG005
    )

    payload = {
        "portfolio_id": "TWR_BENCHMARK_STATEFUL",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "include_benchmark": True,
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "benchmark": {
            "input_mode": "stateful",
            "return_source": "calculated",
            "stateful_input": {},
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["benchmark_context"]["benchmark_id"] == "BMK_ASSIGNED"
    assert body["benchmark_context"]["benchmark_currency"] == "USD"
    assert body["benchmark_context"]["input_mode"] == "stateful"
    assert body["benchmark_context"]["return_source"] == "calculated"
    assert body["benchmark_context"]["supportability_evidence"]["calendar_alignment_state"] == "aligned"
    benchmark_block = body["results_by_period"]["YTD"]["benchmark"]
    assert benchmark_block["benchmark_id"] == "BMK_ASSIGNED"
    assert benchmark_block["input_mode"] == "stateful"
    assert benchmark_block["summary"]["period_return"]["base"] == pytest.approx(2.01)
    assert body["results_by_period"]["YTD"]["relative_performance"]["summary"]["period_return"][
        "base"
    ] == pytest.approx(0.0)


def test_twr_supports_include_benchmark_without_nested_stateful_benchmark_config(client, monkeypatch):
    class _StatefulBenchmarkStub:
        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 200, {"portfolio_open_date": "2024-12-31"}

        async def get_portfolio_timeseries(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "portfolio_open_date": "2024-12-31",
                    "observations": [
                        {
                            "valuation_date": "2025-01-01",
                            "beginning_market_value": "1000",
                            "ending_market_value": "1010",
                        },
                        {
                            "valuation_date": "2025-01-02",
                            "beginning_market_value": "1010",
                            "ending_market_value": "1020.1",
                        },
                    ],
                },
            )

        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": "BMK_ASSIGNED_DEFAULT"}

        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "benchmark_id": "BMK_ASSIGNED_DEFAULT",
                    "benchmark_currency": "USD",
                    "segments": [
                        {
                            "index_id": "IDX_USD",
                            "composition_weight": "1.0",
                            "composition_effective_from": "2024-12-31",
                            "composition_effective_to": "2025-01-31",
                        }
                    ],
                },
            )

        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "points": [
                        {"series_date": "2024-12-31", "index_price": "100", "series_currency": "USD"},
                        {"series_date": "2025-01-01", "index_price": "101", "series_currency": "USD"},
                        {"series_date": "2025-01-02", "index_price": "102.01", "series_currency": "USD"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )

        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            return 200, {"points": []}

        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "unused"}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _StatefulBenchmarkStub(),  # noqa: ARG005
    )

    payload = {
        "portfolio_id": "TWR_BENCHMARK_STATEFUL_DEFAULT",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
        "include_benchmark": True,
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["benchmark_context"]["benchmark_id"] == "BMK_ASSIGNED_DEFAULT"
    assert body["benchmark_context"]["benchmark_currency"] == "USD"
    assert body["benchmark_context"]["input_mode"] == "stateful"
    assert body["benchmark_context"]["return_source"] == "calculated"
    assert body["benchmark_context"]["supportability_evidence"]["calendar_alignment_state"] == "aligned"
    assert body["results_by_period"]["YTD"]["benchmark"]["benchmark_id"] == "BMK_ASSIGNED_DEFAULT"
    assert body["results_by_period"]["YTD"]["benchmark"]["input_mode"] == "stateful"


def test_twr_supports_explicit_window_with_stateless_benchmark_in_stateful_mode(client, monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-03-16",
                "observations": [
                    {
                        "valuation_date": "2026-03-16",
                        "beginning_market_value": "0",
                        "ending_market_value": "20000",
                        "external_flow": "20000",
                    },
                    {
                        "valuation_date": "2026-03-17",
                        "beginning_market_value": "20000",
                        "ending_market_value": "20100",
                        "external_flow": "0",
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "STATEFUL_TWR_EXPLICIT_BENCHMARK",
        "performance_start_date": "2026-03-16",
        "report_start_date": "2026-03-17",
        "report_end_date": "2026-03-17",
        "metric_basis": "NET",
        "include_benchmark": True,
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
        "benchmark": {
            "benchmark_id": "BMK_EXPLICIT_TWR",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {
                        "component_id": "IDX_A",
                        "perf_date": "2026-03-16",
                        "weight_bop": 1.0,
                        "component_return": 0.0,
                    },
                    {
                        "component_id": "IDX_A",
                        "perf_date": "2026-03-17",
                        "weight_bop": 1.0,
                        "component_return": 0.004,
                    },
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    explicit = body["results_by_period"]["EXPLICIT"]
    assert explicit["portfolio"]["summary"]["period_return"]["base"] == pytest.approx(0.5)
    assert explicit["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(0.4)
    assert explicit["relative_performance"]["summary"]["period_return"]["base"] == pytest.approx(0.1)


def test_twr_records_http_failure_detail_in_execution_status(client, monkeypatch):
    calculation_id = str(uuid4())

    class _FailingStatefulBenchmarkStub:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": "BMK_BAD_WINDOW"}

        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "benchmark_id": "BMK_BAD_WINDOW",
                    "benchmark_currency": "USD",
                    "segments": [
                        {
                            "index_id": "IDX_USD",
                            "composition_weight": "1.0",
                            "composition_effective_from": "2025-01-02",
                            "composition_effective_to": "2025-01-31",
                        }
                    ],
                },
            )

        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "unused"}

        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            return 200, {"points": []}

        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "unused"}

    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-12-31",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _FailingStatefulBenchmarkStub(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "TWR_BENCHMARK_STATEFUL_FAILURE",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
        "include_benchmark": True,
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 422
    assert "does not cover requested date 2025-01-01" in response.json()["detail"]

    execution_response = client.get(f"/performance/executions/{calculation_id}")
    assert execution_response.status_code == 200
    body = execution_response.json()
    assert body["status"] == "failed"
    assert "does not cover requested date 2025-01-01" in body["error_message"]
    retrieval_stage = {stage["stage_name"]: stage for stage in body["stages"]}["retrieval"]
    assert retrieval_stage["status"] == "failed"
    assert "does not cover requested date 2025-01-01" in retrieval_stage["error_message"]


def test_twr_supports_stateless_benchmark_price_points(client):
    payload = {
        "portfolio_id": "TWR_BENCHMARK_PRICE_POINTS",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "include_benchmark": True,
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "benchmark": {
            "benchmark_id": "BMK_PRICE_1",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_price_points": [
                    {"component_id": "IDX_A", "perf_date": "2024-12-31", "weight_bop": 1.0, "index_price": 100.0},
                    {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "index_price": 101.0},
                    {"component_id": "IDX_A", "perf_date": "2025-01-02", "weight_bop": 1.0, "index_price": 102.01},
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["results_by_period"]["YTD"]["benchmark"]["benchmark_id"] == "BMK_PRICE_1"
    assert body["results_by_period"]["YTD"]["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(2.01)
    assert body["results_by_period"]["YTD"]["relative_performance"]["summary"]["period_return"][
        "base"
    ] == pytest.approx(0.0)


def test_twr_relative_performance_uses_cumulative_to_date_for_non_itd_periods(client):
    payload = {
        "portfolio_id": "TWR_BENCHMARK_RELATIVE_MTD",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-02-15",
        "analyses": [
            {"period": "MTD", "frequencies": ["monthly"]},
            {"period": "YTD", "frequencies": ["monthly"]},
        ],
        "include_benchmark": True,
        "valuation_points": [
            {"perf_date": "2025-01-15", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-02-10", "begin_mv": 1010.0, "end_mv": 1030.2},
        ],
        "benchmark": {
            "benchmark_id": "BMK_RELATIVE_1",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2025-01-15", "weight_bop": 1.0, "component_return": 0.005},
                    {"component_id": "IDX_A", "perf_date": "2025-02-10", "weight_bop": 1.0, "component_return": 0.015},
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    mtd_relative = body["results_by_period"]["MTD"]["relative_performance"]["summary"]
    ytd_relative = body["results_by_period"]["YTD"]["relative_performance"]["summary"]

    assert mtd_relative["period_return"]["base"] == pytest.approx(0.5)
    assert mtd_relative["cumulative_return"]["base"] == pytest.approx(1.0125)
    assert ytd_relative["period_return"]["base"] == pytest.approx(1.0125)
    assert ytd_relative["cumulative_return"]["base"] == pytest.approx(1.0125)


def test_twr_endpoint_returns_async_paths_for_stateful_benchmark_request(client, monkeypatch):
    settings = get_settings()
    original_window_threshold = settings.TWR_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.TWR_EXECUTOR_INPUT_COUNT
    settings.TWR_EXECUTOR_WINDOW_DAYS = 365
    settings.TWR_EXECUTOR_INPUT_COUNT = 5

    async def _mock_resolve_twr_request(request, *, settings):  # noqa: ARG001
        return ResolvedTWRRequest(
            performance_request=PerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "portfolio_id": request.portfolio_id,
                    "performance_start_date": "2024-12-31",
                    "report_end_date": "2025-01-03",
                    "metric_basis": "NET",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                        {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
                        {"perf_date": "2025-01-03", "begin_mv": 1020.1, "end_mv": 1030.301},
                        {"perf_date": "2025-01-04", "begin_mv": 1030.301, "end_mv": 1040.60401},
                    ],
                }
            ),
            input_mode=request.input_mode,
            benchmark_request=BenchmarkPerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "benchmark_id": "BMK_ASYNC_TWR",
                    "benchmark_start_date": "2025-01-01",
                    "report_end_date": "2025-01-03",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "return_source": "calculated",
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-02",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                    ],
                }
            ),
            benchmark_input_mode=BenchmarkInputMode.STATEFUL,
            resolved_benchmark_id="BMK_ASYNC_TWR",
        )

    monkeypatch.setattr("app.services.twr_calculation_service.resolve_twr_request", _mock_resolve_twr_request)

    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "TWR_ASYNC_ACCEPTED",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-03",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "include_benchmark": True,
        "stateful_input": {},
    }

    try:
        response = client.post("/performance/twr", json=payload)

        assert response.status_code == 202
        body = response.json()
        assert body["poll_path"].endswith(payload["calculation_id"])
        pending = client.get(body["result_path"])
        assert pending.status_code == 202
    finally:
        settings.TWR_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.TWR_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_twr_endpoint_generates_calculation_id_for_async_stateful_benchmark_request(client, monkeypatch):
    settings = get_settings()
    original_window_threshold = settings.TWR_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.TWR_EXECUTOR_INPUT_COUNT
    settings.TWR_EXECUTOR_WINDOW_DAYS = 365
    settings.TWR_EXECUTOR_INPUT_COUNT = 5

    async def _mock_resolve_twr_request(request, *, settings):  # noqa: ARG001
        return ResolvedTWRRequest(
            performance_request=PerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "portfolio_id": request.portfolio_id,
                    "performance_start_date": "2024-12-31",
                    "report_end_date": "2025-01-03",
                    "metric_basis": "NET",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                        {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
                        {"perf_date": "2025-01-03", "begin_mv": 1020.1, "end_mv": 1030.301},
                        {"perf_date": "2025-01-04", "begin_mv": 1030.301, "end_mv": 1040.60401},
                    ],
                }
            ),
            input_mode=request.input_mode,
            benchmark_request=BenchmarkPerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "benchmark_id": "BMK_ASYNC_TWR",
                    "benchmark_start_date": "2025-01-01",
                    "report_end_date": "2025-01-03",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "return_source": "calculated",
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-02",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                    ],
                }
            ),
            benchmark_input_mode=BenchmarkInputMode.STATEFUL,
            resolved_benchmark_id="BMK_ASYNC_TWR",
        )

    monkeypatch.setattr("app.services.twr_calculation_service.resolve_twr_request", _mock_resolve_twr_request)

    payload = {
        "portfolio_id": "TWR_GENERATED_ASYNC",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-03",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "include_benchmark": True,
        "stateful_input": {},
    }

    try:
        response = client.post("/performance/twr", json=payload)

        assert response.status_code == 202
        body = response.json()
        generated_calculation_id = body["calculation_id"]
        assert generated_calculation_id
        assert body["poll_path"].endswith(generated_calculation_id)
        assert body["result_path"].endswith(generated_calculation_id)
    finally:
        settings.TWR_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.TWR_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_twr_async_result_missing_and_failed_contracts(client, monkeypatch):
    settings = get_settings()
    original_window_threshold = settings.TWR_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.TWR_EXECUTOR_INPUT_COUNT
    settings.TWR_EXECUTOR_WINDOW_DAYS = 365
    settings.TWR_EXECUTOR_INPUT_COUNT = 5

    async def _mock_resolve_twr_request(request, *, settings):  # noqa: ARG001
        return ResolvedTWRRequest(
            performance_request=PerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "portfolio_id": request.portfolio_id,
                    "performance_start_date": "2024-12-31",
                    "report_end_date": "2025-01-03",
                    "metric_basis": "NET",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                        {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
                        {"perf_date": "2025-01-03", "begin_mv": 1020.1, "end_mv": 1030.301},
                        {"perf_date": "2025-01-04", "begin_mv": 1030.301, "end_mv": 1040.60401},
                    ],
                }
            ),
            input_mode=request.input_mode,
            benchmark_request=BenchmarkPerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "benchmark_id": "BMK_ASYNC_TWR_FAIL",
                    "benchmark_start_date": "2025-01-01",
                    "report_end_date": "2025-01-03",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "return_source": "calculated",
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-02",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                    ],
                }
            ),
            benchmark_input_mode=BenchmarkInputMode.STATEFUL,
            resolved_benchmark_id="BMK_ASYNC_TWR_FAIL",
        )

    monkeypatch.setattr("app.services.twr_calculation_service.resolve_twr_request", _mock_resolve_twr_request)

    payload = {
        "portfolio_id": "TWR_ASYNC_FAIL",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-03",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "include_benchmark": True,
        "stateful_input": {},
    }

    try:
        missing = client.get(f"/performance/twr/results/{uuid4()}")
        assert missing.status_code == 404

        accepted = client.post("/performance/twr", json=payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        from app.services.compute_job_store import compute_job_store

        compute_job_store.mark_failed(UUID(calculation_id), error_message="explode")
        failed = client.get(f"/performance/twr/results/{calculation_id}")
        assert failed.status_code == 409
        assert failed.json()["detail"] == "explode"
    finally:
        settings.TWR_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.TWR_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_twr_hashes_include_resolved_benchmark_request(client):
    payload = {
        "portfolio_id": "TWR_BENCHMARK_HASH",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "include_benchmark": True,
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "benchmark": {
            "benchmark_id": "BMK_STATELESS_1",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-01-02", "weight_bop": 1.0, "component_return": 0.015},
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash_from_value(
        TWRResolvedExecutionRequest(
            portfolio=PerformanceRequest.model_validate(
                {
                    "calculation_id": body["calculation_id"],
                    "portfolio_id": "TWR_BENCHMARK_HASH",
                    "performance_start_date": "2024-12-31",
                    "metric_basis": "NET",
                    "report_end_date": "2025-01-02",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                        {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
                    ],
                }
            ),
            benchmark=BenchmarkPerformanceRequest.model_validate(
                {
                    "calculation_id": body["calculation_id"],
                    "benchmark_id": "BMK_STATELESS_1",
                    "benchmark_start_date": "2025-01-01",
                    "report_end_date": "2025-01-02",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "return_source": "calculated",
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-02",
                            "weight_bop": 1.0,
                            "component_return": 0.015,
                        },
                    ],
                    "benchmark_return_points": [],
                }
            ),
        ),
        calculation_engine_version(get_settings()),
    )
    assert body["meta"]["input_fingerprint"] == expected_input_fingerprint
    assert body["meta"]["calculation_hash"] == expected_calculation_hash


def test_twr_benchmark_cumulative_return_tracks_reporting_horizon(client):
    payload = {
        "portfolio_id": "TWR_BENCHMARK_CUMULATIVE",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-02-28",
        "analyses": [{"period": "YTD", "frequencies": ["monthly"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-31", "begin_mv": 1010.0, "end_mv": 1020.1},
            {"perf_date": "2025-02-01", "begin_mv": 1020.1, "end_mv": 1030.301},
            {"perf_date": "2025-02-28", "begin_mv": 1030.301, "end_mv": 1040.60401},
        ],
        "include_benchmark": True,
        "benchmark": {
            "benchmark_id": "BMK_STATELESS_CUMULATIVE",
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-01-31", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-02-01", "weight_bop": 1.0, "component_return": 0.01},
                    {"component_id": "IDX_A", "perf_date": "2025-02-28", "weight_bop": 1.0, "component_return": 0.01},
                ],
            },
        },
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    result = response.json()["results_by_period"]["YTD"]

    assert result["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(
        result["benchmark"]["summary"]["cumulative_return"]["base"]
    )
    assert result["relative_performance"]["summary"]["cumulative_return"]["base"] == pytest.approx(
        result["relative_performance"]["summary"]["period_return"]["base"]
    )


def test_twr_stateful_hashes_follow_resolved_inputs(client, monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-01-15",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    base_payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "STATEFUL_TWR_HASH_TEST",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    first_payload = {**base_payload, "performance_start_date": "2024-12-31"}
    second_payload = {**base_payload, "performance_start_date": "2023-01-01"}

    first_request = TWRAnalyticsRequest.model_validate(first_payload)
    second_request = TWRAnalyticsRequest.model_validate(second_payload)
    first_pre_resolution_hashes = generate_twr_request_hashes(
        first_request,
        engine_version=calculation_engine_version(get_settings()),
    )
    second_pre_resolution_hashes = generate_twr_request_hashes(
        second_request,
        engine_version=calculation_engine_version(get_settings()),
    )

    assert first_pre_resolution_hashes == second_pre_resolution_hashes

    first = client.post(
        "/performance/twr",
        json=first_payload,
    )

    assert first.status_code == 200

    expected_request = PerformanceRequest.model_validate(
        {
            "calculation_id": first.json()["calculation_id"],
            "portfolio_id": "STATEFUL_TWR_HASH_TEST",
            "performance_start_date": "2024-01-15",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1},
            ],
            "source_quality_evidence": {
                "source_product": "PortfolioTimeseriesInput",
                "source_owner": "lotus-core",
                "input_mode": "stateful",
                "quality_state": "clean",
                "observation_count": 2,
                "valid_valuation_point_count": 2,
                "skipped_observation_count": 0,
                "unsupported_cashflow_count": 0,
                "source_conflict_count": 0,
                "latest_observation_date": "2025-01-02",
                "report_end_date": "2025-01-02",
                "warnings": [],
                "source_classification_counts": {},
            },
        }
    )
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash_from_value(
        TWRResolvedExecutionRequest(portfolio=expected_request, benchmark=None),
        calculation_engine_version(get_settings()),
    )

    assert first.json()["meta"]["input_fingerprint"] == expected_input_fingerprint
    assert first.json()["meta"]["calculation_hash"] == expected_calculation_hash


def test_twr_reset_scenario_has_correct_summary(client):
    """
    Tests that for a period that includes a performance reset, the top-level
    portfolio_return summary uses the correct final cumulative return from the engine.
    """
    payload = {
        "portfolio_id": "TWR_STRESS_TEST_03",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "metric_basis": "GROSS",
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
            {"perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
            {"perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
            {"perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
        ],
        "reset_policy": {"emit": True},
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_result = data["results_by_period"]["SI"]

    assert "portfolio" in itd_result
    assert itd_result["portfolio"]["summary"]["period_return"]["base"] == pytest.approx(21.578947, abs=1e-6)


@pytest.mark.parametrize(
    "error_class, expected_status",
    [(InvalidEngineInputError, 400), (EngineCalculationError, 500), (Exception, 500)],
)
def test_calculate_twr_endpoint_error_handling(client, mocker, error_class, expected_status):
    """Tests that the TWR endpoint correctly handles engine exceptions."""
    mocker.patch("app.services.twr_service.run_calculations", side_effect=error_class("Test Error"))
    payload = {
        "portfolio_id": "ERROR_TEST",
        "performance_start_date": "2023-12-31",
        "metric_basis": "NET",
        "report_end_date": "2024-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2024-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_twr_returns_400_when_no_periods_resolve(client, mocker):
    mocker.patch("app.services.twr_service.resolve_periods", return_value=[])
    payload = {
        "portfolio_id": "NO_PERIODS",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 400
    assert "No valid periods could be resolved" in response.json()["detail"]


def test_twr_returns_empty_results_when_resolved_period_has_no_data(client):
    payload = {
        "portfolio_id": "NO_PERIOD_DATA",
        "performance_start_date": "2024-01-01",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2024-12-30", "begin_mv": 1000.0, "end_mv": 1005.0},
            {"perf_date": "2024-12-31", "begin_mv": 1005.0, "end_mv": 1010.0},
        ],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    assert response.json()["results_by_period"] == {}


def test_twr_http_exception_passthrough_branch(client, mocker):
    mocker.patch(
        "app.services.twr_service.resolve_periods",
        side_effect=HTTPException(status_code=418, detail="teapot"),
    )
    payload = {
        "portfolio_id": "HTTP_EXCEPTION",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 418
    assert response.json()["detail"] == "teapot"


def test_mwr_http_exception_passthrough_branch(client, mocker):
    mocker.patch(
        "app.services.mwr_calculation_service.calculate_mwr_result",
        side_effect=HTTPException(status_code=409, detail="conflict"),
    )
    payload = {
        "portfolio_id": "MWR_HTTP",
        "begin_mv": 1000.0,
        "end_mv": 1001.0,
        "cash_flows": [],
        "as_of": "2026-01-15",
    }
    response = client.post("/performance/mwr", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "conflict"
