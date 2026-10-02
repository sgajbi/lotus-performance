import os
import shutil
from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.models.contribution_requests import ContributionRequest
from app.observability_contracts import PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS
from app.services.async_result_store import async_result_store
from app.services.calculation_engine_version import calculation_engine_version
from app.services.compute_job_store import compute_job_store
from app.services.contribution_calculation_workflow_service import build_contribution_execution_window
from app.services.contribution_mode_service import resolved_contribution_identity_payload
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.stateful_contribution_input_service import _position_row_to_daily_point
from core.repro import generate_canonical_hash
from engine.exceptions import EngineCalculationError
from main import app
from tests.conftest import drain_compute_queue, drain_lineage_queue

settings = get_settings()
_EXPECTED_SUPPORTABILITY_METRIC_LABELS = list(PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS)


@pytest.fixture()
def client():
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    os.makedirs(settings.LINEAGE_STORAGE_PATH, exist_ok=True)
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    compute_job_store.create_schema()
    compute_job_store.clear_all_records()
    async_result_store.create_schema()
    async_result_store.clear_all_records()
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()

    with TestClient(app, headers={"X-Tenant-Id": "tenant-a"}) as c:
        yield c

    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    compute_job_store.clear_all_records()
    async_result_store.clear_all_records()
    execution_registry.clear_all_records()
    lineage_metadata_store.clear_all_records()


def test_contribution_endpoint_happy_path_and_envelope(client, happy_path_payload):
    """Tests the /performance/contribution endpoint and verifies the shared response envelope."""
    response = client.post("/performance/contribution", json=happy_path_payload)

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["portfolio_id"] == "CONTRIB_TEST_01"
    assert "results_by_period" in response_data
    assert "SI" in response_data["results_by_period"]
    assert response_data["calculation_supportability"] == {
        "state": "ready",
        "reason": "calculation_complete",
        "freshness_bucket": "current",
        "input_row_count": 4,
        "resolved_period_count": 1,
        "benchmark_row_count": 0,
        "source_quality_evidence": None,
        "history_coverage": None,
        "metric_labels": _EXPECTED_SUPPORTABILITY_METRIC_LABELS,
    }
    smoothing_evidence = response_data["results_by_period"]["SI"]["smoothing_evidence"]
    assert smoothing_evidence["smoothing_method"] == "CARINO"
    assert smoothing_evidence["status"] == "APPLIED"
    assert "CARINO_FACTOR_APPLIED" in smoothing_evidence["reason_codes"]
    assert smoothing_evidence["linked_return"] == pytest.approx(
        response_data["results_by_period"]["SI"]["total_portfolio_return"]
    )
    assert smoothing_evidence["final_contribution"] == pytest.approx(
        response_data["results_by_period"]["SI"]["total_contribution"]
    )
    assert smoothing_evidence["carino_factor_min"] is not None
    assert smoothing_evidence["carino_factor_max"] is not None
    source_economics = response_data["source_economics_evidence"]
    assert source_economics["status"] == "CALLER_SUPPLIED"
    assert source_economics["source_owner"] == "caller"
    assert "ContributionRequest" in source_economics["source_contracts"]


@pytest.mark.parametrize("end_mv,expected_total", [(1100, 10.0), (900, -10.0), (1000, 0.0)])
@pytest.mark.parametrize("currency_mode", [None, "BASE_ONLY", "LOCAL_ONLY", "BOTH"])
@pytest.mark.parametrize("with_hierarchy", [False, True])
@pytest.mark.parametrize("precision_mode", ["FLOAT64", "DECIMAL_STRICT"])
def test_contribution_currency_explanation_requires_both_mode(
    client, end_mv, expected_total, currency_mode, with_hierarchy, precision_mode
):
    payload = {
        "portfolio_id": "SYNTHETIC_CURRENCY_CONTRIBUTION",
        "currency": "USD",
        "precision_mode": precision_mode,
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": end_mv}],
        },
        "positions_data": [
            {
                "position_id": "USD_STOCK",
                "meta": {"currency": "USD", "position_currency": "USD", "sector": "ONE"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": end_mv}],
            }
        ],
    }
    if currency_mode is not None:
        payload["currency_mode"] = currency_mode
    if with_hierarchy:
        payload["hierarchy"] = ["sector"]

    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200, response.text
    period = response.json()["results_by_period"]["SI"]
    position = period["position_contributions"][0]
    assert period["total_portfolio_return"] == pytest.approx(expected_total)
    assert position["total_contribution"] == pytest.approx(expected_total)
    if currency_mode == "BOTH":
        assert position["local_contribution"] == pytest.approx(expected_total)
        assert position["fx_contribution"] == pytest.approx(0.0, abs=1e-10)
    else:
        assert position["local_contribution"] is None
        assert position["fx_contribution"] is None
    if with_hierarchy:
        summary = period["summary"]
        row = period["levels"][0]["rows"][0]
        assert summary["portfolio_contribution"] == pytest.approx(expected_total)
        assert row["contribution"] == pytest.approx(expected_total)
        if currency_mode == "BOTH":
            assert summary["local_contribution"] == pytest.approx(expected_total)
            assert summary["fx_contribution"] == pytest.approx(0.0, abs=1e-10)
        else:
            assert summary["local_contribution"] is None
            assert summary["fx_contribution"] is None
        # Hierarchy rows are grouped from adjusted total series, not a dated local/FX series.
        assert row["local_contribution"] is None
        assert row["fx_contribution"] is None


def test_contribution_openapi_describes_nullable_currency_decomposition():
    schemas = app.openapi()["components"]["schemas"]
    valuation_properties = schemas["PositionDailyData"]["properties"]
    assert "after market movement and booked management fees" in valuation_properties["end_mv"]["description"]
    assert "Negative values are fee debits" in valuation_properties["mgmt_fees"]["description"]
    assert "after-fee ending values" in schemas["PortfolioData"]["properties"]["metric_basis"]["description"]
    for field_name in ("local_contribution", "fx_contribution"):
        position_field = schemas["PositionContribution"]["properties"][field_name]
        assert {variant["type"] for variant in position_field["anyOf"]} == {"number", "null"}
        assert "currency_mode=BOTH" in position_field["description"]
        assert "null" in position_field["description"]
        hierarchy_field = schemas["ContributionRow"]["properties"][field_name]
        assert "null" in hierarchy_field["description"]


@pytest.mark.parametrize("with_hierarchy", [False, True])
@pytest.mark.parametrize("with_known_peer", [False, True])
def test_contribution_both_without_position_currency_does_not_fabricate_fx(client, with_hierarchy, with_known_peer):
    position_begin_mv = 500 if with_known_peer else 1000
    position_end_mv = 550 if with_known_peer else 1100
    payload = {
        "portfolio_id": "SYNTHETIC_UNKNOWN_POSITION_CURRENCY",
        "currency": "USD",
        "report_ccy": "USD",
        "currency_mode": "BOTH",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1100}],
        },
        "positions_data": [
            {
                "position_id": "UNKNOWN_CCY_STOCK",
                "meta": {"sector": "ONE"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": position_begin_mv, "end_mv": position_end_mv}
                ],
            }
        ],
    }
    if with_known_peer:
        payload["positions_data"].append(
            {
                "position_id": "KNOWN_USD_STOCK",
                "meta": {"currency": "USD", "sector": "ONE"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 500, "end_mv": 550}],
            }
        )
    if with_hierarchy:
        payload["hierarchy"] = ["sector"]

    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200, response.text
    period = response.json()["results_by_period"]["SI"]
    assert period["total_portfolio_return"] == pytest.approx(10.0)
    assert sum(position["total_contribution"] for position in period["position_contributions"]) == pytest.approx(10.0)
    for position in period["position_contributions"]:
        assert position["local_contribution"] is None
        assert position["fx_contribution"] is None
    if with_hierarchy:
        assert period["summary"]["local_contribution"] is None
        assert period["summary"]["fx_contribution"] is None


@pytest.mark.parametrize("with_hierarchy", [False, True])
def test_contribution_both_ignores_unpriced_position_for_currency_evidence(client, with_hierarchy):
    payload = {
        "portfolio_id": "SYNTHETIC_UNPRICED_POSITION",
        "currency": "USD",
        "report_ccy": "USD",
        "currency_mode": "BOTH",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1100}],
        },
        "positions_data": [
            {
                "position_id": "PRICED_USD_STOCK",
                "meta": {"currency": "USD", "sector": "ONE"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1100}],
            },
            {"position_id": "UNPRICED_STOCK", "meta": {}, "valuation_points": []},
        ],
    }
    if with_hierarchy:
        payload["hierarchy"] = ["sector"]

    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200, response.text
    period = response.json()["results_by_period"]["SI"]
    assert period["total_portfolio_return"] == pytest.approx(10.0)
    assert len(period["position_contributions"]) == 1
    position = period["position_contributions"][0]
    assert position["position_id"] == "PRICED_USD_STOCK"
    assert position["total_contribution"] == pytest.approx(10.0)
    assert position["local_contribution"] == pytest.approx(10.0)
    assert position["fx_contribution"] == pytest.approx(0.0)
    if with_hierarchy:
        assert period["summary"]["local_contribution"] == pytest.approx(10.0)
        assert period["summary"]["fx_contribution"] == pytest.approx(0.0)


@pytest.mark.parametrize("hierarchy_mode", ["flat", "classified", "excluded"])
def test_contribution_same_currency_carino_residual_does_not_become_fx(client, hierarchy_mode):
    payload = {
        "portfolio_id": "SYNTHETIC_LOCAL_RESIDUAL",
        "currency": "USD",
        "report_ccy": "USD",
        "currency_mode": "BOTH",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1100}],
        },
        "positions_data": [
            {
                "position_id": "USD_STOCK",
                "meta": {"currency": "USD", **({"sector": "ONE"} if hierarchy_mode != "excluded" else {})},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1090}],
            }
        ],
    }
    if hierarchy_mode != "flat":
        payload["hierarchy"] = ["sector"]
    if hierarchy_mode == "excluded":
        payload["emit"] = {"include_unclassified": False}

    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200, response.text
    period = response.json()["results_by_period"]["SI"]
    position = period["position_contributions"][0]
    assert position["total_return"] == pytest.approx(9.0)
    assert period["total_portfolio_return"] == pytest.approx(10.0)
    assert position["total_contribution"] == pytest.approx(10.0)
    assert position["local_contribution"] == pytest.approx(10.0)
    assert position["fx_contribution"] == pytest.approx(0.0, abs=1e-10)
    if hierarchy_mode == "classified":
        assert period["summary"]["local_contribution"] == pytest.approx(10.0)
        assert period["summary"]["fx_contribution"] == pytest.approx(0.0, abs=1e-10)
    if hierarchy_mode == "excluded":
        assert period["summary"]["portfolio_contribution"] == pytest.approx(0.0)
        assert period["summary"]["local_contribution"] == pytest.approx(0.0)
        assert period["summary"]["fx_contribution"] == pytest.approx(0.0)
        assert period["levels"] == []


@pytest.fixture
def identity_control_payload():
    return {
        "portfolio_id": "POSITION_IDENTITY_CONTROL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "currency": "USD",
        "report_ccy": "USD",
        "currency_mode": "BOTH",
        "emit": {"timeseries": True, "by_position_timeseries": True},
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1060}],
        },
        "positions_data": [
            {
                "position_id": "A",
                "meta": {"sector": "GAIN", "security_id": "SHARED_SECURITY"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 660}],
            },
            {
                "position_id": "B",
                "meta": {"sector": "FLAT", "security_id": "SHARED_SECURITY"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 400}],
            },
        ],
    }


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("precision_mode", ["FLOAT64", "DECIMAL_STRICT"])
def test_contribution_unique_position_grains_preserve_independent_economics(
    client, identity_control_payload, reverse, precision_mode
):
    payload = deepcopy(identity_control_payload)
    payload["precision_mode"] = precision_mode
    payload["hierarchy"] = ["sector"]
    if reverse:
        payload["positions_data"].reverse()

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    rows = {row["position_id"]: row for row in period["position_contributions"]}
    assert period["total_portfolio_return"] == pytest.approx(6.0)
    assert period["total_contribution"] == pytest.approx(6.0)
    assert rows["A"]["total_contribution"] == pytest.approx(6.0)
    assert rows["B"]["total_contribution"] == pytest.approx(0.0)
    assert rows["A"]["total_return"] == pytest.approx(10.0)
    assert rows["B"]["total_return"] == pytest.approx(0.0)
    assert rows["A"]["average_weight"] == pytest.approx(60.0)
    assert rows["B"]["average_weight"] == pytest.approx(40.0)
    assert len(period["timeseries"]) == 1
    assert len(period["by_position_timeseries"]) == 2


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("conflicting", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("hierarchy", [False, True])
def test_contribution_rejects_duplicate_identity_before_sync_or_async_registration(
    client, identity_control_payload, nested, conflicting, reverse, hierarchy
):
    payload = deepcopy(identity_control_payload)
    duplicate = deepcopy(payload["positions_data"][0])
    if conflicting:
        duplicate["valuation_points"][0]["end_mv"] = 600
    payload["positions_data"].append(duplicate)
    if reverse:
        payload["positions_data"].reverse()
    if hierarchy:
        payload["hierarchy"] = ["sector"]
    if nested:
        payload["stateless_input"] = {
            "portfolio_data": payload.pop("portfolio_data"),
            "positions_data": payload.pop("positions_data"),
        }

    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    try:
        for threshold in (10_000, 0):
            settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = threshold
            payload["calculation_id"] = str(uuid4())
            response = client.post(
                "/performance/contribution", json=payload, headers={"X-Correlation-Id": "position-identity-probe"}
            )
            assert response.status_code == 422
            body = response.json()
            assert body["error_code"] == "VALIDATION_ERROR"
            assert body["message"] == "Request validation failed."
            assert any("duplicate position_id" in error["msg"] for error in body["validation_errors"])
            assert body["correlation_id"] == "position-identity-probe"
            assert all("input" not in error for error in body["validation_errors"])
            assert response.headers["X-Correlation-Id"] == "position-identity-probe"
            assert response.headers["X-Request-Id"]
            assert response.headers["X-Trace-Id"]
            assert client.get(f"/performance/executions/{payload['calculation_id']}").status_code == 404
            assert client.get(f"/performance/contribution/results/{payload['calculation_id']}").status_code == 404
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_duplicate_position_refusal_counts_as_bounded_client_error(client, identity_control_payload):
    def contribution_client_errors() -> float:
        metrics = client.get("/metrics").text
        matching = [
            line
            for line in metrics.splitlines()
            if line.startswith('http_requests_total{handler="/performance/contribution",method="POST",status="4xx"}')
        ]
        return float(matching[0].rsplit(" ", 1)[-1]) if matching else 0.0

    payload = deepcopy(identity_control_payload)
    payload["positions_data"].append(deepcopy(payload["positions_data"][0]))
    before = contribution_client_errors()

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 422
    assert contribution_client_errors() == before + 1.0


def test_contribution_endpoint_reports_zero_grouped_return_alignment_drift_for_simple_aligned_case(client):
    payload = {
        "portfolio_id": "CONTRIB_ALIGNED_RESETS",
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

    assert response.status_code == 200
    body = response.json()
    period_status = body["results_by_period"]["SI"]["average_weight_methodology_status"]
    assert period_status["status"] == "NO_MATERIAL_SHADOW"
    assert period_status["is_material_shadow"] is False
    assert period_status["blocker_reason_codes"] == []
    assert body["audit"]["counts"]["portfolio_reset_days"] == 0
    assert body["audit"]["counts"]["position_reset_days"] == 0
    assert body["audit"]["counts"]["portfolio_reset_without_position_reset_days"] == 0
    assert body["audit"]["counts"]["position_reset_without_portfolio_reset_days"] == 0
    assert not any(
        "grouped-return alignment remains under characterization" in note for note in body["diagnostics"]["notes"]
    )


def test_contribution_endpoint_multi_period(client):
    """Tests a multi-period request for MTD and YTD contribution."""
    payload = {
        "portfolio_id": "MULTI_PERIOD_CONTRIB",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-02-15",
        "analyses": [{"period": "MTD", "frequencies": ["monthly"]}, {"period": "YTD", "frequencies": ["monthly"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-10", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-02-10", "begin_mv": 1010, "end_mv": 1030.2},
            ],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "valuation_points": [
                    {"perf_date": "2025-01-10", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-02-10", "begin_mv": 1010, "end_mv": 1030.2},
                ],
            }
        ],
    }
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "results_by_period" in data
    results = data["results_by_period"]
    assert "MTD" in results
    assert "YTD" in results


def test_contribution_endpoint_supports_explicit_period_windows(client):
    payload = {
        "portfolio_id": "CONTRIB_EXPLICIT_WINDOW",
        "report_start_date": "2025-01-02",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1100},
                {"perf_date": "2025-01-02", "begin_mv": 1100, "end_mv": 1111},
                {"perf_date": "2025-01-03", "begin_mv": 1111, "end_mv": 1122.11},
            ],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1100},
                    {"perf_date": "2025-01-02", "begin_mv": 1100, "end_mv": 1111},
                    {"perf_date": "2025-01-03", "begin_mv": 1111, "end_mv": 1122.11},
                ],
            }
        ],
        "emit": {"timeseries": True, "by_position_timeseries": True},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    explicit_result = body["results_by_period"]["EXPLICIT"]
    assert explicit_result["total_portfolio_return"] == pytest.approx(2.01)
    assert explicit_result["total_contribution"] == pytest.approx(2.01)
    assert [point["date"] for point in explicit_result["timeseries"]] == [
        "2025-01-02",
        "2025-01-03",
    ]
    assert [point["date"] for point in explicit_result["by_position_timeseries"][0]["series"]] == [
        "2025-01-02",
        "2025-01-03",
    ]


def test_contribution_endpoint_multi_currency(client):
    """Tests an end-to-end multi-currency contribution request."""
    payload = {
        "portfolio_id": "MULTI_CCY_CONTRIB_01",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 105.0, "end_mv": 110.16}],
        },
        "positions_data": [
            {
                "position_id": "EUR_STOCK",
                "meta": {"currency": "EUR"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0}],
            }
        ],
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.05},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.08},
            ]
        },
    }
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["SI"]
    assert data["total_contribution"] == pytest.approx(4.91429, abs=1e-5)
    evidence = response.json()["currency_evidence"]
    assert evidence["applied_report_ccy"] == "USD"
    assert evidence["applied_pairs"] == ["EUR/USD"]

    payload.pop("report_ccy")
    rejected = client.post("/performance/contribution", json=payload)
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "FX_REPORT_CURRENCY_REQUIRED"
    assert evidence["restated"] is True
    assert evidence["fx_coverage"] == "complete"


def test_contribution_lineage_flow(client, happy_path_payload):
    """Tests that lineage is correctly captured for a single-level contribution request."""
    payload = happy_path_payload.copy()
    payload["emit"] = {"timeseries": True}

    contrib_response = client.post("/performance/contribution", json=payload)
    assert contrib_response.status_code == 200
    calculation_id = contrib_response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200


def test_contribution_endpoint_no_smoothing(client, happy_path_payload):
    """Tests that the endpoint correctly processes a request with smoothing disabled."""
    payload = happy_path_payload.copy()
    payload["smoothing"] = {"method": "NONE"}
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    smoothing_evidence = response.json()["results_by_period"]["SI"]["smoothing_evidence"]
    assert smoothing_evidence["status"] == "NOT_REQUESTED"
    assert "SMOOTHING_NOT_REQUESTED" in smoothing_evidence["reason_codes"]


def test_contribution_endpoint_smoothing_evidence_reports_invalid_carino_domain(client):
    payload = {
        "portfolio_id": "CONTRIB_INVALID_CARINO_EVIDENCE",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 100, "end_mv": -50}],
        },
        "positions_data": [
            {
                "position_id": "BROKEN_CAPITAL",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 100, "end_mv": -50}],
            }
        ],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    smoothing_evidence = response.json()["results_by_period"]["SI"]["smoothing_evidence"]
    assert smoothing_evidence["status"] == "INVALID_DOMAIN_FALLBACK"
    assert smoothing_evidence["invalid_domain_days"] == 1
    assert "CARINO_INVALID_DAILY_LOG_DOMAIN" in smoothing_evidence["reason_codes"]


def test_contribution_endpoint_with_timeseries(client, happy_path_payload):
    """Tests that the endpoint correctly returns time-series data when requested."""
    payload = happy_path_payload.copy()
    payload["emit"] = {"timeseries": True, "by_position_timeseries": True}
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    body = response.json()["results_by_period"]["SI"]
    assert len(body["timeseries"]) == 2
    assert len(body["by_position_timeseries"]) == 1
    assert body["by_position_timeseries"][0]["position_id"] == "Stock_A"
    assert len(body["by_position_timeseries"][0]["series"]) == 2


def test_contribution_endpoint_hierarchy_happy_path(client, happy_path_payload):
    """Tests a hierarchical contribution request aggregates correctly."""
    payload = happy_path_payload.copy()
    payload["hierarchy"] = ["sector", "position_id"]
    payload["positions_data"].append(
        {
            "position_id": "Stock_B",
            "meta": {"sector": "Technology"},
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408},
                {"perf_date": "2025-01-02", "begin_mv": 408, "end_mv": 410},
            ],
        }
    )
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["SI"]
    assert "summary" in data
    assert data["summary"]["portfolio_contribution"] == pytest.approx(2.95327, abs=1e-5)
    sector_row = data["levels"][0]["rows"][0]
    assert sector_row["group_return"]["status"] == "READY"
    assert sector_row["group_return"]["currency"] == "USD"
    assert [point["date"] for point in sector_row["group_return"]["series"]] == [
        "2025-01-01",
        "2025-01-02",
    ]


def test_contribution_endpoint_hierarchy_publishes_contrasting_group_return_series(client):
    payload = {
        "portfolio_id": "CONTRIB_GROUP_RETURN_CONTRAST",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "hierarchy": ["sector"],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020},
                {"perf_date": "2025-01-02", "begin_mv": 1020, "end_mv": 1040.4},
            ],
        },
        "positions_data": [
            {
                "position_id": "EQUITY",
                "meta": {"sector": "Equity"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 606},
                    {"perf_date": "2025-01-02", "begin_mv": 606, "end_mv": 624.18},
                ],
            },
            {
                "position_id": "BONDS",
                "meta": {"sector": "Bonds"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 412},
                    {"perf_date": "2025-01-02", "begin_mv": 412, "end_mv": 416.12},
                ],
            },
        ],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    rows = {row["key"]["sector"]: row for row in response.json()["results_by_period"]["SI"]["levels"][0]["rows"]}
    equity_return = rows["Equity"]["group_return"]
    bonds_return = rows["Bonds"]["group_return"]
    assert equity_return["status"] == bonds_return["status"] == "READY"
    assert equity_return["currency"] == bonds_return["currency"] == "USD"
    assert [point["return_pct"] for point in equity_return["series"]] == pytest.approx([1.0, 3.0])
    assert [point["return_pct"] for point in bonds_return["series"]] == pytest.approx([3.0, 1.0])
    assert [point["portfolio_weight_pct"] for point in equity_return["series"]] == pytest.approx(
        [60.0, 59.411764705882355]
    )
    assert [point["portfolio_weight_pct"] for point in bonds_return["series"]] == pytest.approx(
        [40.0, 40.3921568627451]
    )
    assert equity_return["period_return_pct"] == pytest.approx(4.03)
    assert bonds_return["period_return_pct"] == pytest.approx(4.03)


@pytest.mark.parametrize(
    ("observation_date", "opening_portfolio_mv", "income"),
    [
        ("2026-03-03", "1301897.108535348", "850"),
        ("2026-03-11", "1344103.059275136", "1187"),
    ],
)
def test_contribution_endpoint_reconciles_core_income_source_rows_to_portfolio_return(
    client, observation_date: str, opening_portfolio_mv: str, income: str
):
    opening_mv = Decimal(opening_portfolio_mv)
    income_amount = Decimal(income)

    def source_position_point(begin_mv: Decimal, end_mv: Decimal, cash_flows: list[dict]) -> dict:
        point = _position_row_to_daily_point(
            row={
                "valuation_date": observation_date,
                "beginning_market_value_portfolio_currency": str(begin_mv),
                "ending_market_value_portfolio_currency": str(end_mv),
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": cash_flows,
            },
            currency_mode="BASE_ONLY",
            reporting_currency=None,
        )
        assert point is not None
        return {key: str(value) if isinstance(value, Decimal) else value for key, value in point.items()}

    positions = [
        (
            "INCOME_ASSET",
            "Fixed Income",
            source_position_point(
                Decimal("100000"),
                Decimal("100000"),
                [
                    {
                        "amount": str(-income_amount),
                        "timing": "eod",
                        "cash_flow_type": "income",
                        "flow_scope": "operational",
                        "source_classification": "INCOME",
                    }
                ],
            ),
        ),
        (
            "CASH",
            "Cash",
            source_position_point(
                Decimal("100000"),
                Decimal("100000") + income_amount,
                [{"amount": income, "timing": "bod", "cash_flow_type": "internal_trade_flow"}],
            ),
        ),
        (
            "OTHER",
            "Other",
            source_position_point(opening_mv - Decimal("200000"), opening_mv - Decimal("200000"), []),
        ),
    ]
    payload = {
        "portfolio_id": "CONTRIB_CORE_INCOME_RECONCILIATION",
        "report_start_date": observation_date,
        "report_end_date": observation_date,
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "hierarchy": ["sector"],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {
                    "perf_date": observation_date,
                    "begin_mv": opening_portfolio_mv,
                    "end_mv": str(opening_mv + income_amount),
                }
            ],
        },
        "positions_data": [
            {"position_id": position_id, "meta": {"sector": sector}, "valuation_points": [point]}
            for position_id, sector, point in positions
        ],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    expected_pp = float(income_amount / opening_mv * 100)
    assert period["total_portfolio_return"] == pytest.approx(expected_pp, abs=1e-6)
    group_rows = period["levels"][0]["rows"]
    weighted_group_pp = sum(
        row["group_return"]["series"][0]["portfolio_weight_pct"] * row["group_return"]["series"][0]["return_pct"] / 100
        for row in group_rows
    )
    assert {row["group_return"]["status"] for row in group_rows} == {"READY"}
    assert weighted_group_pp == pytest.approx(expected_pp, abs=1e-6)
    assert weighted_group_pp == pytest.approx(period["total_portfolio_return"], abs=0.01)


def test_contribution_endpoint_treats_external_deposit_as_non_performance(client):
    payload = {
        "portfolio_id": "CONTRIB_EXTERNAL_DEPOSIT_NO_PERF",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "bod_cf": 100, "end_mv": 1100},
            ],
        },
        "positions_data": [
            {
                "position_id": "CASH_DEPOSIT",
                "meta": {"asset_class": "Cash"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "bod_cf": 100, "end_mv": 1100},
                ],
            }
        ],
        "hierarchy": ["asset_class"],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    assert period["total_portfolio_return"] == pytest.approx(0.0)
    assert period["total_contribution"] == pytest.approx(0.0)
    assert period["summary"]["portfolio_contribution"] == pytest.approx(0.0)
    assert period["levels"][0]["rows"][0]["key"] == {"asset_class": "Cash"}
    assert period["levels"][0]["rows"][0]["contribution"] == pytest.approx(0.0)


def test_contribution_endpoint_assigns_income_to_generating_asset(client):
    payload = {
        "portfolio_id": "CONTRIB_INCOME_GENERATING_ASSET",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "positions_data": [
            {
                "position_id": "BOND_INCOME_ASSET",
                "meta": {"asset_class": "Fixed Income", "income_pnl": 15},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
            }
        ],
        "hierarchy": ["asset_class"],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    period = body["results_by_period"]["SI"]
    row = period["levels"][0]["rows"][0]
    assert row["key"] == {"asset_class": "Fixed Income"}
    assert row["contribution"] == pytest.approx(period["total_contribution"])
    assert period["total_contribution"] == pytest.approx(1.5)
    assert "income_pnl" not in body["source_economics_evidence"]["unsupported_economics"]


def test_contribution_endpoint_assigns_net_fee_drag_to_fee_bucket(client):
    payload = {
        "portfolio_id": "CONTRIB_NET_FEE_BUCKET",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 990, "mgmt_fees": -10},
            ],
        },
        "positions_data": [
            {
                "position_id": "ADVISORY_FEE_BUCKET",
                "meta": {"asset_class": "Fees", "fee_pnl": -10},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 990, "mgmt_fees": -10},
                ],
            }
        ],
        "hierarchy": ["asset_class"],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    period = body["results_by_period"]["SI"]
    row = period["levels"][0]["rows"][0]
    assert row["key"] == {"asset_class": "Fees"}
    assert row["contribution"] == pytest.approx(-1.0)
    assert period["total_contribution"] == pytest.approx(-1.0)
    assert "fee_pnl" not in body["source_economics_evidence"]["unsupported_economics"]


@pytest.mark.parametrize(
    ("metric_basis", "end_mv", "mgmt_fees", "bod_cf", "eod_cf", "expected_return"),
    [
        ("NET", 1090, -10, 0, 0, 9.0),
        ("GROSS", 1090, -10, 0, 0, 10.0),
        ("NET", 1110, 10, 0, 0, 11.0),
        ("GROSS", 1110, 10, 0, 0, 10.0),
        ("NET", 1100, 0, 0, 0, 10.0),
        ("GROSS", 1100, 0, 0, 0, 10.0),
        ("NET", 1200, -10, 100, 0, 100 / 11),
        ("GROSS", 1200, -10, 100, 0, 10.0),
        ("NET", 1190, -10, 0, 100, 9.0),
        ("GROSS", 1190, -10, 0, 100, 10.0),
    ],
)
@pytest.mark.parametrize("precision_mode", ["FLOAT64", "DECIMAL_STRICT"])
def test_contribution_endpoint_uses_after_fee_ending_values(
    client,
    precision_mode,
    metric_basis,
    end_mv,
    mgmt_fees,
    bod_cf,
    eod_cf,
    expected_return,
):
    valuation_point = {
        "perf_date": "2025-01-01",
        "begin_mv": 1000,
        "end_mv": end_mv,
        "mgmt_fees": mgmt_fees,
        "bod_cf": bod_cf,
        "eod_cf": eod_cf,
    }
    payload = {
        "portfolio_id": f"CONTRIB_AFTER_FEE_{metric_basis}_{end_mv}_{bod_cf}_{eod_cf}",
        "precision_mode": precision_mode,
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {"metric_basis": metric_basis, "valuation_points": [valuation_point]},
        "positions_data": [
            {
                "position_id": "USD_ASSET",
                "meta": {"currency": "USD"},
                "valuation_points": [valuation_point],
            }
        ],
        "hierarchy": ["position_id"],
        "smoothing": {"method": "NONE"},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    assert period["total_portfolio_return"] == pytest.approx(expected_return)
    assert period["total_contribution"] == pytest.approx(expected_return)


@pytest.mark.parametrize(
    ("metric_basis", "expected_portfolio_return", "expected_position_return"),
    [("NET", 8.0, 7.0), ("GROSS", 9.0, 8.0)],
)
@pytest.mark.parametrize("precision_mode", ["FLOAT64", "DECIMAL_STRICT"])
def test_contribution_endpoint_applies_after_fee_market_value_overrides_by_entity(
    client,
    metric_basis,
    expected_portfolio_return,
    expected_position_return,
    precision_mode,
):
    valuation_point = {
        "perf_date": "2025-01-01",
        "begin_mv": 1000,
        "end_mv": 1090,
        "mgmt_fees": -10,
    }
    payload = {
        "portfolio_id": f"CONTRIB_AFTER_FEE_OVERRIDE_{metric_basis}",
        "precision_mode": precision_mode,
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {"metric_basis": metric_basis, "valuation_points": [valuation_point]},
        "positions_data": [
            {
                "position_id": "USD_ASSET",
                "meta": {"currency": "USD"},
                "valuation_points": [valuation_point],
            }
        ],
        "data_policy": {
            "overrides": {
                "market_values": [
                    {
                        "perf_date": "2025-01-01",
                        "portfolio_id": f"CONTRIB_AFTER_FEE_OVERRIDE_{metric_basis}",
                        "end_mv": 1080,
                    },
                    {"perf_date": "2025-01-01", "position_id": "USD_ASSET", "end_mv": 1070},
                ]
            }
        },
        "hierarchy": ["position_id"],
        "smoothing": {"method": "NONE"},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    period = body["results_by_period"]["SI"]
    assert period["total_portfolio_return"] == pytest.approx(expected_portfolio_return)
    assert period["position_contributions"][0]["total_return"] == pytest.approx(expected_position_return)
    assert body["diagnostics"]["policy"]["overrides"]["applied_mv_count"] == 2
    assert body["diagnostics"]["notes"] == ["Applied overrides from the data_policy request."]


def test_contribution_endpoint_honors_outlier_scope_and_identifies_each_position(client):
    daily_returns = [1.0, 1.1, 0.9, 1.2, 0.8, 99.0, 1.0, 1.1, 0.9, 1.0]
    valuation_points = [
        {
            "perf_date": str(perf_date.date()),
            "begin_mv": 1000,
            "end_mv": 1000 * (1 + daily_return / 100),
        }
        for perf_date, daily_return in zip(pd.date_range("2025-01-01", periods=10), daily_returns, strict=True)
    ]
    payload = {
        "portfolio_id": "CONTRIB_OUTLIER_SCOPE",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-10",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {"metric_basis": "NET", "valuation_points": valuation_points},
        "positions_data": [
            {"position_id": "OUTLIER_POSITION_1", "valuation_points": valuation_points},
            {"position_id": "OUTLIER_POSITION_2", "valuation_points": valuation_points},
        ],
        "data_policy": {"outliers": {"enabled": True, "action": "FLAG", "params": {"window": 5, "mad_k": 3.0}}},
        "smoothing": {"method": "NONE"},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200, response.text
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["policy"]["outliers"]["flagged_rows"] == 2
    assert [(sample["entity_type"], sample["entity_id"]) for sample in diagnostics["samples"]["outliers"]] == [
        ("POSITION", "OUTLIER_POSITION_1"),
        ("POSITION", "OUTLIER_POSITION_2"),
    ]


def test_contribution_endpoint_allocates_after_fee_position_economics(client):
    payload = {
        "portfolio_id": "CONTRIB_AFTER_FEE_ALLOCATION",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1095, "mgmt_fees": -5}],
        },
        "positions_data": [
            {
                "position_id": "FEE_BEARING",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 500, "end_mv": 545, "mgmt_fees": -5}],
            },
            {
                "position_id": "FEE_FREE",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 500, "end_mv": 550}],
            },
        ],
        "hierarchy": ["position_id"],
        "smoothing": {"method": "NONE"},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    contributions = {row["position_id"]: row for row in period["position_contributions"]}
    assert period["total_portfolio_return"] == pytest.approx(9.5)
    assert period["total_contribution"] == pytest.approx(9.5)
    assert contributions["FEE_BEARING"]["total_return"] == pytest.approx(9.0)
    assert contributions["FEE_BEARING"]["total_contribution"] == pytest.approx(4.5)
    assert contributions["FEE_FREE"]["total_return"] == pytest.approx(10.0)
    assert contributions["FEE_FREE"]["total_contribution"] == pytest.approx(5.0)
    hierarchy_rows = {row["key"]["position_id"]: row for row in period["levels"][0]["rows"]}
    assert hierarchy_rows["FEE_BEARING"]["contribution"] == pytest.approx(4.5)
    assert hierarchy_rows["FEE_FREE"]["contribution"] == pytest.approx(5.0)


def test_contribution_endpoint_preserves_missing_classification_as_unclassified(client):
    payload = {
        "portfolio_id": "CONTRIB_UNCLASSIFIED",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
        },
        "positions_data": [
            {
                "position_id": "UNCLASSIFIED_ASSET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        ],
        "hierarchy": ["asset_class"],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    assert period["levels"][0]["rows"][0]["key"] == {"asset_class": "Unclassified"}
    assert period["levels"][0]["rows"][0]["contribution"] == pytest.approx(1.0)


def test_contribution_endpoint_preserves_short_position_inverse_sign_behavior(client):
    payload = {
        "portfolio_id": "CONTRIB_SHORT_SIGN",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 990}],
        },
        "positions_data": [
            {
                "position_id": "SHORT_TECH",
                "meta": {"asset_class": "Short Equity"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": -100, "end_mv": -90}],
            },
            {
                "position_id": "LONG_CASH",
                "meta": {"asset_class": "Cash"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1100, "end_mv": 1080}],
            },
        ],
        "hierarchy": ["asset_class"],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    rows_by_asset_class = {row["key"]["asset_class"]: row for row in period["levels"][0]["rows"]}
    assert rows_by_asset_class["Short Equity"]["weight_avg"] == pytest.approx(-10.0)
    assert rows_by_asset_class["Short Equity"]["contribution"] < 0
    assert period["total_contribution"] == pytest.approx(period["total_portfolio_return"])


def test_contribution_endpoint_weight_fields_use_percentage_units_for_position_and_hierarchy_outputs(client):
    base_payload = {
        "portfolio_id": "CONTRIB_WEIGHT_UNITS",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020}],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "meta": {"sector": "Technology"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "position_id": "Stock_B",
                "meta": {"sector": "Healthcare"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408}],
            },
        ],
    }

    position_response = client.post("/performance/contribution", json=base_payload)
    hierarchy_response = client.post(
        "/performance/contribution",
        json={**base_payload, "hierarchy": ["sector"]},
    )

    assert position_response.status_code == 200
    assert hierarchy_response.status_code == 200

    position_rows = {
        row["position_id"]: row for row in position_response.json()["results_by_period"]["SI"]["position_contributions"]
    }
    hierarchy_rows = {
        row["key"]["sector"]: row for row in hierarchy_response.json()["results_by_period"]["SI"]["levels"][0]["rows"]
    }

    assert position_rows["Stock_A"]["average_weight"] == pytest.approx(60.0)
    assert position_rows["Stock_B"]["average_weight"] == pytest.approx(40.0)
    assert sum(row["average_weight"] for row in position_rows.values()) == pytest.approx(100.0)
    assert hierarchy_rows["Technology"]["weight_avg"] == pytest.approx(60.0)
    assert hierarchy_rows["Healthcare"]["weight_avg"] == pytest.approx(40.0)
    assert sum(row["weight_avg"] for row in hierarchy_rows.values()) == pytest.approx(100.0)


def test_contribution_endpoint_hierarchy_keeps_position_contribution_detail(client):
    payload = {
        "portfolio_id": "CONTRIB_HIER_POSITION_DETAIL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "hierarchy": ["sector"],
        "emit": {"timeseries": True, "by_position_timeseries": True, "by_level": True},
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020}],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "meta": {"sector": "Technology"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "position_id": "Stock_B",
                "meta": {"sector": "Healthcare"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408}],
            },
        ],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    result = response.json()["results_by_period"]["SI"]
    position_rows = {row["position_id"]: row for row in result["position_contributions"]}

    assert result["total_portfolio_return"] == pytest.approx(2.0)
    assert result["total_contribution"] == pytest.approx(2.0)
    assert result["summary"]["portfolio_contribution"] == pytest.approx(result["total_contribution"])
    assert sum(row["contribution"] for row in result["levels"][0]["rows"]) == pytest.approx(
        result["total_contribution"]
    )
    assert sum(point["total_contribution"] for point in result["timeseries"]) == pytest.approx(
        result["total_contribution"]
    )
    assert sum(
        point["contribution"] for series in result["by_position_timeseries"] for point in series["series"]
    ) == pytest.approx(result["total_contribution"])
    assert position_rows["Stock_A"]["average_weight"] == pytest.approx(60.0)
    assert position_rows["Stock_A"]["total_return"] == pytest.approx(2.0)
    assert position_rows["Stock_A"]["local_contribution"] is None
    assert position_rows["Stock_A"]["fx_contribution"] is None
    assert position_rows["Stock_B"]["average_weight"] == pytest.approx(40.0)
    assert position_rows["Stock_B"]["total_return"] == pytest.approx(2.0)


def test_contribution_endpoint_hierarchy_respects_multiple_resolved_periods(client):
    payload = {
        "portfolio_id": "HIER_MULTI_PERIOD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-02-15",
        "analyses": [{"period": "MTD", "frequencies": ["monthly"]}, {"period": "YTD", "frequencies": ["monthly"]}],
        "hierarchy": ["sector"],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-31", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-02-15", "begin_mv": 1010, "end_mv": 1030.2},
            ],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "meta": {"sector": "Technology"},
                "valuation_points": [
                    {"perf_date": "2025-01-31", "begin_mv": 600, "end_mv": 606},
                    {"perf_date": "2025-02-15", "begin_mv": 606, "end_mv": 618.12},
                ],
            },
            {
                "position_id": "Stock_B",
                "meta": {"sector": "Healthcare"},
                "valuation_points": [
                    {"perf_date": "2025-01-31", "begin_mv": 400, "end_mv": 404},
                    {"perf_date": "2025-02-15", "begin_mv": 404, "end_mv": 412.08},
                ],
            },
        ],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    results = response.json()["results_by_period"]
    assert set(results) == {"MTD", "YTD"}
    assert results["MTD"]["summary"]["portfolio_contribution"] == pytest.approx(2.0, abs=1e-5)
    assert results["YTD"]["summary"]["portfolio_contribution"] == pytest.approx(3.02, abs=1e-5)


def test_contribution_hierarchy_level_rows_reconcile_after_position_residual_allocation(client):
    payload = {
        "portfolio_id": "HIER_RECONCILES_WITH_RESIDUAL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "hierarchy": ["sector"],
        "emit": {"timeseries": True, "by_position_timeseries": True, "by_level": True},
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
                "meta": {"sector": "Technology"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 606},
                    {"perf_date": "2025-01-02", "begin_mv": 606, "end_mv": 618.12},
                ],
            },
            {
                "position_id": "Stock_B",
                "meta": {"sector": "Healthcare"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 404},
                    {"perf_date": "2025-01-02", "begin_mv": 404, "end_mv": 412.08},
                ],
            },
        ],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    result = response.json()["results_by_period"]["SI"]
    position_total = sum(row["total_contribution"] for row in result["position_contributions"])
    level_total = sum(row["contribution"] for row in result["levels"][0]["rows"])
    level_weight_total = sum(row["weight_avg"] for row in result["levels"][0]["rows"])
    daily_total = sum(point["total_contribution"] for point in result["timeseries"])
    by_position_daily_total = sum(
        point["contribution"] for series in result["by_position_timeseries"] for point in series["series"]
    )

    assert result["total_contribution"] == pytest.approx(result["total_portfolio_return"])
    assert result["summary"]["portfolio_contribution"] == pytest.approx(result["total_contribution"])
    assert position_total == pytest.approx(result["total_contribution"])
    assert level_total == pytest.approx(result["total_contribution"])
    assert level_weight_total == pytest.approx(100.0)
    assert daily_total == pytest.approx(result["total_contribution"])
    assert by_position_daily_total == pytest.approx(result["total_contribution"])


def test_contribution_hierarchy_top_n_rolls_excluded_rows_into_other(client):
    payload = {
        "portfolio_id": "HIER_TOP_N_OTHER",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "hierarchy": ["sector"],
        "emit": {"by_level": True, "top_n_per_level": 2, "threshold_weight": 0, "include_other": True},
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020}],
        },
        "positions_data": [
            {
                "position_id": "Large",
                "meta": {"sector": "Large"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 700, "end_mv": 714}],
            },
            {
                "position_id": "Medium",
                "meta": {"sector": "Medium"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 200, "end_mv": 204}],
            },
            {
                "position_id": "Small",
                "meta": {"sector": "Small"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 100, "end_mv": 102}],
            },
        ],
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    rows = response.json()["results_by_period"]["SI"]["levels"][0]["rows"]
    assert len(rows) == 3
    assert rows[-1]["is_other"] is True
    assert rows[-1]["children_count"] == 1
    assert sum(row["contribution"] for row in rows) == pytest.approx(2.0)
    assert sum(row["weight_avg"] for row in rows) == pytest.approx(100.0)


def test_contribution_endpoint_error_handling(client, mocker):
    """Tests that a generic server error is raised for calculation failures."""
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data", side_effect=EngineCalculationError("Test Error")
    )
    payload = {
        "portfolio_id": "ERROR",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1025}],
        },
        "positions_data": [],
    }
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 500


def test_contribution_endpoint_no_resolved_periods_returns_400(client):
    payload = {
        "portfolio_id": "NO_PERIODS",
        "report_start_date": "2025-01-10",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "MTD", "frequencies": ["monthly"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-10", "begin_mv": 1000, "end_mv": 1010}],
        },
        "positions_data": [],
    }
    from app.services import contribution_service

    original_resolve_periods = contribution_service.resolve_periods
    contribution_service.resolve_periods = (  # type: ignore[assignment]
        lambda periods, end_date, inception_date, **kwargs: []
    )
    try:
        response = client.post("/performance/contribution", json=payload)
    finally:
        contribution_service.resolve_periods = original_resolve_periods  # type: ignore[assignment]

    assert response.status_code == 400
    assert "No valid periods could be resolved." in response.json()["detail"]


def test_contribution_endpoint_skips_empty_period_slice(client):
    payload = {
        "portfolio_id": "EMPTY_SLICE",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["monthly"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        ],
    }
    from app.services import contribution_service

    original_prepare = contribution_service._prepare_hierarchical_data
    original_daily = contribution_service._calculate_daily_instrument_contributions

    def _mock_prepare(_request):
        portfolio_df = pd.DataFrame(
            [{"perf_date": "2025-01-01", "daily_ror": 0.1}],
        )
        return pd.DataFrame(), portfolio_df

    def _mock_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
        return pd.DataFrame(
            [
                {
                    "perf_date": "2024-01-01",
                    "position_id": "Stock_A",
                    "smoothed_contribution": 0.0,
                    "smoothed_local_contribution": 0.0,
                    "daily_weight": 1.0,
                }
            ]
        )

    contribution_service._prepare_hierarchical_data = _mock_prepare  # type: ignore[assignment]
    contribution_service._calculate_daily_instrument_contributions = _mock_daily  # type: ignore[assignment]
    try:
        response = client.post("/performance/contribution", json=payload)
    finally:
        contribution_service._prepare_hierarchical_data = original_prepare  # type: ignore[assignment]
        contribution_service._calculate_daily_instrument_contributions = original_daily  # type: ignore[assignment]

    assert response.status_code == 200
    assert response.json()["results_by_period"] == {}


def test_contribution_endpoint_emits_grouped_return_alignment_note_for_misaligned_reset_days(client):
    payload = {
        "portfolio_id": "MISALIGNED_GROUPED_RETURNS",
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
            {
                "position_id": "Stock_A",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
                ],
            }
        ],
    }
    from app.services import contribution_service

    original_prepare = contribution_service._prepare_hierarchical_data
    original_daily = contribution_service._calculate_daily_instrument_contributions

    def _mock_prepare(_request):
        instruments_df = pd.DataFrame(
            {
                "position_id": ["Stock_A", "Stock_A", "Stock_A"],
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "perf_reset": [0, 0, 1],
            }
        )
        portfolio_df = pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
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

    def _mock_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
        return pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["Stock_A", "Stock_A", "Stock_A"],
                "smoothed_contribution": [0.01, 0.01, 0.01],
                "smoothed_local_contribution": [0.01, 0.01, 0.01],
                "daily_weight": [0.5, 0.5, 0.5],
                "perf_reset": [0, 0, 1],
            }
        )

    contribution_service._prepare_hierarchical_data = _mock_prepare  # type: ignore[assignment]
    contribution_service._calculate_daily_instrument_contributions = _mock_daily  # type: ignore[assignment]
    try:
        response = client.post("/performance/contribution", json=payload)
    finally:
        contribution_service._prepare_hierarchical_data = original_prepare  # type: ignore[assignment]
        contribution_service._calculate_daily_instrument_contributions = original_daily  # type: ignore[assignment]

    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["counts"]["portfolio_reset_days"] == 1
    assert body["audit"]["counts"]["position_reset_days"] == 1
    assert body["audit"]["counts"]["portfolio_reset_without_position_reset_days"] == 1
    assert body["audit"]["counts"]["position_reset_without_portfolio_reset_days"] == 1
    assert any(
        "grouped-return alignment remains under characterization" in note for note in body["diagnostics"]["notes"]
    )


def test_contribution_endpoint_promotes_reset_aware_average_weight_for_clean_candidate_periods(
    client,
):
    """Proves the runtime rollout mode changes emitted average weights at the API surface."""
    payload = {
        "portfolio_id": "RESET_AWARE_WEIGHT_PROMOTION",
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
    from app.services import contribution_service

    original_prepare = contribution_service._prepare_hierarchical_data
    original_daily = contribution_service._calculate_daily_instrument_contributions

    def _mock_prepare(_request):
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

    def _mock_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
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

    original_mode = settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE
    settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE = "CANDIDATE_PERIODS"
    contribution_service._prepare_hierarchical_data = _mock_prepare  # type: ignore[assignment]
    contribution_service._calculate_daily_instrument_contributions = _mock_daily  # type: ignore[assignment]
    try:
        response = client.post("/performance/contribution", json=payload)
    finally:
        contribution_service._prepare_hierarchical_data = original_prepare  # type: ignore[assignment]
        contribution_service._calculate_daily_instrument_contributions = original_daily  # type: ignore[assignment]
        settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE = original_mode

    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["counts"]["average_weight_shadow_cutover_candidate_periods"] == 1
    assert body["audit"]["counts"]["average_weight_shadow_promoted_periods"] == 1
    period_status = body["results_by_period"]["SI"]["average_weight_methodology_status"]
    assert period_status["status"] == "PROMOTED"
    assert period_status["is_material_shadow"] is True
    assert period_status["is_cutover_candidate"] is True
    assert period_status["is_promoted"] is True
    assert period_status["blocker_reason_codes"] == []
    position_contributions = body["results_by_period"]["SI"]["position_contributions"]
    position_contributions_by_id = {
        position_contribution["position_id"]: position_contribution for position_contribution in position_contributions
    }
    assert position_contributions_by_id["A"]["average_weight"] == pytest.approx(95.0)
    assert position_contributions_by_id["B"]["average_weight"] == pytest.approx(5.0)
    assert any("promotion was applied" in note for note in body["diagnostics"]["notes"])
    assert any(
        "strong candidates for a future denominator cutover study" in note for note in body["diagnostics"]["notes"]
    )


def test_contribution_endpoint_promotes_reset_aware_average_weight_for_hierarchy_candidate_periods(
    client,
):
    """Proves hierarchy rows use the same promoted denominator as position contribution details."""
    payload = {
        "portfolio_id": "RESET_AWARE_WEIGHT_HIERARCHY_PROMOTION",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "hierarchy": ["sector"],
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
        "emit": {"threshold_weight": 0.0},
    }
    from app.services import contribution_service

    original_prepare = contribution_service._prepare_hierarchical_data
    original_daily = contribution_service._calculate_daily_instrument_contributions

    def _mock_prepare(_request):
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
                "sector": ["Legacy", "Technology", "Technology", "Health Care", "Health Care", "Health Care"],
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

    def _mock_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
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
                "sector": ["Legacy", "Technology", "Technology", "Health Care", "Health Care", "Health Care"],
                "smoothed_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "daily_weight": [0.10, 0.95, 0.95, 0.90, 0.05, 0.05],
                "perf_reset": [0, 1, 0, 0, 1, 0],
            }
        )

    original_mode = settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE
    settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE = "CANDIDATE_PERIODS"
    contribution_service._prepare_hierarchical_data = _mock_prepare  # type: ignore[assignment]
    contribution_service._calculate_daily_instrument_contributions = _mock_daily  # type: ignore[assignment]
    try:
        response = client.post("/performance/contribution", json=payload)
    finally:
        contribution_service._prepare_hierarchical_data = original_prepare  # type: ignore[assignment]
        contribution_service._calculate_daily_instrument_contributions = original_daily  # type: ignore[assignment]
        settings.CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE = original_mode

    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["counts"]["average_weight_shadow_cutover_candidate_periods"] == 1
    assert body["audit"]["counts"]["average_weight_shadow_promoted_periods"] == 1
    period = body["results_by_period"]["SI"]
    assert period["average_weight_methodology_status"]["status"] == "PROMOTED"
    assert period["average_weight_methodology_status"]["is_promoted"] is True
    positions_by_id = {row["position_id"]: row for row in period["position_contributions"]}
    assert positions_by_id["A"]["average_weight"] == pytest.approx(95.0)
    assert positions_by_id["B"]["average_weight"] == pytest.approx(5.0)
    hierarchy_rows = period["levels"][0]["rows"]
    hierarchy_rows_by_sector = {row["key"]["sector"]: row for row in hierarchy_rows}
    assert hierarchy_rows_by_sector["Technology"]["weight_avg"] == pytest.approx(95.0)
    assert hierarchy_rows_by_sector["Health Care"]["weight_avg"] == pytest.approx(5.0)
    assert hierarchy_rows_by_sector["Legacy"]["weight_avg"] == pytest.approx(0.0)


def test_contribution_async_result_retrieval(client, happy_path_payload):
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0

    try:
        accepted = client.post("/performance/contribution", json=happy_path_payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        pending = client.get(f"/performance/contribution/results/{calculation_id}")
        assert pending.status_code == 202

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/contribution/results/{calculation_id}")
        assert complete.status_code == 200
        body = complete.json()
        assert body["calculation_id"] == calculation_id
        assert "SI" in body["results_by_period"]
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_contribution_supports_stateful_input_mode(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
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
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "position_currency": "USD",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "position_currency": "USD",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "1010",
                    "ending_market_value_portfolio_currency": "1020.1",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload, headers={"X-Tenant-Id": "tenant-a"})

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "CONTRIB_STATEFUL"
    assert body["input_mode"] == "stateful"
    assert "SI" in body["results_by_period"]
    source_economics = body["source_economics_evidence"]
    assert source_economics["source_owner"] == "lotus-core"
    assert source_economics["status"] == "SOURCE_LIMITED"
    assert source_economics["component_detail_status"] == "LIMITED"
    assert "PortfolioTimeseriesInput:v1" in source_economics["source_contracts"]
    assert "PositionTimeseriesInput:v1" in source_economics["source_contracts"]
    assert "sector" in source_economics["classification_dimensions"]

    payload.update({"currency_mode": "BOTH", "report_ccy": "EUR", "fx": {}})
    rejected = client.post("/performance/contribution", json=payload, headers={"X-Tenant-Id": "tenant-a"})
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "FX_RATES_REQUIRED"
    assert "fx.rates" in rejected.json()["detail"]

    payload["fx"] = {"rates": [{"date": "2024-12-31", "ccy": "USD", "rate": 0.92}]}
    partial = client.post("/performance/contribution", json=payload, headers={"X-Tenant-Id": "tenant-a"})
    assert partial.status_code == 422
    assert "USD/EUR dates 2025-01-01, 2025-01-02" in partial.json()["detail"]


@pytest.mark.parametrize(("metric_basis", "expected_return"), [("NET", 9.0), ("GROSS", 10.0)])
@pytest.mark.parametrize("precision_mode", ["FLOAT64", "DECIMAL_STRICT"])
def test_stateful_contribution_normalizes_core_after_fee_ending_values(
    client,
    monkeypatch,
    metric_basis,
    expected_return,
    precision_mode,
):
    async def _source(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        fee = {"amount": "-10", "timing": "eod", "cash_flow_type": "fee"}
        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1090",
                        "cash_flows": [fee],
                    }
                ],
                portfolio_currency="USD",
                reporting_currency="USD",
            ),
            position_rows=[
                {
                    "position_id": "USD_ASSET",
                    "security_id": "USD_ASSET",
                    "position_currency": "USD",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1090",
                    "cash_flows": [fee],
                    "dimensions": {"sector": "Equity"},
                }
            ],
            position_source_rows_complete=True,
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _source,
    )
    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": f"CONTRIB_STATEFUL_AFTER_FEE_{metric_basis}",
            "precision_mode": precision_mode,
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": metric_basis},
            "smoothing": {"method": "NONE"},
        },
    )

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    assert period["total_portfolio_return"] == pytest.approx(expected_return)
    assert period["total_contribution"] == pytest.approx(expected_return)


def test_contribution_registered_api_degrades_rejected_component_scope_without_using_rows(
    client,
    monkeypatch,
):
    from datetime import date

    from app.services.stateful_input_service import StatefulInputService
    from app.services.stateful_performance_input_service import StatefulPortfolioInput

    class _ControlledComponentCoreService:
        foreign_scope = True

        async def get_position_analytics_timeseries(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "rows": [
                        {
                            "position_id": "SEC_1",
                            "security_id": "SEC_1",
                            "position_currency": "USD",
                            "valuation_date": "2025-01-01",
                            "beginning_market_value_portfolio_currency": "1000",
                            "ending_market_value_portfolio_currency": "1010",
                            "cash_flows": [],
                            "dimensions": {"sector": "Technology"},
                        },
                        {
                            "position_id": "SEC_1",
                            "security_id": "SEC_1",
                            "position_currency": "USD",
                            "valuation_date": "2025-01-02",
                            "beginning_market_value_portfolio_currency": "1010",
                            "ending_market_value_portfolio_currency": "1020.1",
                            "cash_flows": [],
                            "dimensions": {"sector": "Technology"},
                        },
                    ]
                },
            )

        async def get_performance_component_economics(self, **kwargs):
            source_portfolio_id = "FOREIGN-PORTFOLIO" if self.foreign_scope else kwargs["portfolio_id"]
            return (
                200,
                {
                    "portfolio_id": source_portfolio_id,
                    "as_of_date": str(kwargs["as_of_date"]),
                    "window": {
                        "start_date": str(kwargs["start_date"]),
                        "end_date": str(kwargs["end_date"]),
                    },
                    "rows": [
                        {
                            "portfolio_id": source_portfolio_id,
                            "security_id": "SEC_1",
                            "transaction_id": "FOREIGN-TXN" if self.foreign_scope else "SOURCE-TXN",
                            "transaction_date": "2025-01-01",
                            "trade_fee_components": [{"currency": "USD", "amount": "99", "evidence_count": 1}],
                        }
                    ],
                    "supportability": {
                        "state": "READY",
                        "reason": "PERFORMANCE_COMPONENT_ECONOMICS_READY",
                        "source_row_count": 1,
                        "observed_component_families": ["fee"],
                        "supported_component_families": ["fee"],
                        "missing_component_families": [],
                    },
                },
            )

    core_service = _ControlledComponentCoreService()
    stateful_input_service = StatefulInputService(core_service=core_service)

    async def _portfolio_input(**kwargs):  # noqa: ARG001
        return StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="USD",
            reporting_currency="USD",
            observations=[
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
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.build_stateful_input_service",
        lambda **kwargs: stateful_input_service,
    )
    monkeypatch.setattr(
        "app.services.stateful_contribution_input_service.retrieve_stateful_portfolio_input",
        _portfolio_input,
    )

    request_payload = {
        "portfolio_id": "CONTRIB_STATEFUL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"dimensions": ["sector"]},
    }
    response = client.post(
        "/performance/contribution",
        json=request_payload,
        headers={"X-Tenant-Id": "tenant-a"},
    )

    assert response.status_code == 200
    body = response.json()
    source_economics = body["source_economics_evidence"]
    assert source_economics["status"] == "SOURCE_LIMITED"
    assert source_economics["component_detail_status"] == "LIMITED"
    assert "performance_component_economics_unavailable" in source_economics["degraded_economics"]
    assert "source_component_fees" not in source_economics["available_economics"]
    assert "fee_pnl" in source_economics["unsupported_economics"]
    assert "FOREIGN-TXN" not in response.text

    snapshots = [
        snapshot
        for snapshot in execution_registry.list_upstream_snapshots(UUID(body["calculation_id"]))
        if snapshot.upstream_endpoint == "performance_component_economics"
    ]
    assert len(snapshots) == 1
    assert snapshots[0].retrieval_status == "502"

    core_service.foreign_scope = False
    valid_response = client.post(
        "/performance/contribution",
        json=request_payload,
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert valid_response.status_code == 200
    valid_body = valid_response.json()
    valid_source_economics = valid_body["source_economics_evidence"]
    assert valid_source_economics["status"] == "SOURCE_BACKED"
    assert "source_component_fees" in valid_source_economics["available_economics"]
    assert "performance_component_economics_unavailable" not in valid_source_economics["degraded_economics"]
    assert valid_body["results_by_period"] == body["results_by_period"]
    valid_snapshots = [
        snapshot
        for snapshot in execution_registry.list_upstream_snapshots(UUID(valid_body["calculation_id"]))
        if snapshot.upstream_endpoint == "performance_component_economics"
    ]
    assert len(valid_snapshots) == 1
    assert valid_snapshots[0].retrieval_status == "200"


@pytest.mark.parametrize(
    ("observation_date", "opening_portfolio_mv", "income"),
    [
        ("2026-03-03", "1301897.108535348", "850"),
        ("2026-03-11", "1344103.059275136", "1187"),
    ],
)
def test_stateful_contribution_reconciles_core_income_to_dated_group_returns(
    client, monkeypatch, observation_date: str, opening_portfolio_mv: str, income: str
):
    from types import SimpleNamespace

    opening_mv = Decimal(opening_portfolio_mv)
    income_amount = Decimal(income)

    def position_row(position_id: str, sector: str, begin_mv: Decimal, end_mv: Decimal, flows: list[dict]) -> dict:
        return {
            "position_id": position_id,
            "security_id": position_id,
            "valuation_date": observation_date,
            "position_currency": "USD",
            "cash_flow_currency": "USD",
            "beginning_market_value_portfolio_currency": str(begin_mv),
            "ending_market_value_portfolio_currency": str(end_mv),
            "cash_flows": flows,
            "dimensions": {"sector": sector},
        }

    async def source_input(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            position_source_rows_complete=True,
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": observation_date,
                        "beginning_market_value": opening_portfolio_mv,
                        "ending_market_value": str(opening_mv + income_amount),
                    }
                ]
            ),
            position_rows=[
                position_row(
                    "INCOME_ASSET",
                    "Fixed Income",
                    Decimal("100000"),
                    Decimal("100000"),
                    [
                        {
                            "amount": str(-income_amount),
                            "timing": "eod",
                            "cash_flow_type": "income",
                            "flow_scope": "operational",
                            "source_classification": "INCOME",
                        }
                    ],
                ),
                position_row(
                    "CASH",
                    "Cash",
                    Decimal("100000"),
                    Decimal("100000") + income_amount,
                    [
                        {
                            "amount": income,
                            "timing": "bod",
                            "cash_flow_type": "internal_trade_flow",
                        }
                    ],
                ),
                position_row("OTHER", "Other", opening_mv - Decimal("200000"), opening_mv - Decimal("200000"), []),
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input", source_input
    )
    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_CORE_INCOME_RECONCILIATION",
            "report_start_date": observation_date,
            "report_end_date": observation_date,
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": "NET", "dimensions": ["sector"], "include_cash_flows": True},
        },
        headers={"X-Tenant-Id": "tenant-sg"},
    )

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    expected_pp = float(income_amount / opening_mv * 100)
    weighted_group_pp = sum(
        row["group_return"]["series"][0]["portfolio_weight_pct"] * row["group_return"]["series"][0]["return_pct"] / 100
        for row in period["levels"][0]["rows"]
    )
    assert weighted_group_pp == pytest.approx(expected_pp, abs=1e-6)
    assert weighted_group_pp == pytest.approx(period["total_portfolio_return"], abs=0.01)


@pytest.mark.parametrize(
    ("position_row", "expected_sector", "expected_contribution"),
    [
        (
            {
                "position_id": "DROPPED_PRIVATE_CREDIT",
                "security_id": "DROPPED_PRIVATE_CREDIT",
                "valuation_date": "2025-01-01",
                "position_currency": "USD",
                "beginning_market_value_portfolio_currency": None,
                "ending_market_value_portfolio_currency": "100",
                "cash_flows": [],
                "dimensions": {"sector": "Private Credit"},
            },
            "Private Credit",
            0.0,
        ),
        (
            {
                "position_id": "MALFORMED_CASH_FLOW",
                "security_id": "MALFORMED_CASH_FLOW",
                "valuation_date": "2025-01-01",
                "position_currency": "USD",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "105",
                "cash_flows": [{"amount": "5", "timing": "mid"}],
                "dimensions": {"sector": "Infrastructure"},
            },
            "Infrastructure",
            1.0,
        ),
        (
            {
                "position_id": "LOSSY_FX_CASH_FLOW",
                "security_id": "LOSSY_FX_CASH_FLOW",
                "valuation_date": "2025-01-01",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "position_to_portfolio_fx_rate": "NaN",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "105",
                "cash_flows": [{"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"}],
                "dimensions": {"sector": "Real Assets"},
            },
            "Real Assets",
            1.0,
        ),
        (
            {
                "position_id": "MISSING_CROSS_CURRENCY_FX",
                "security_id": "MISSING_CROSS_CURRENCY_FX",
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "cash_flow_currency": "EUR",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "105",
                "cash_flows": [{"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"}],
                "dimensions": {"sector": "Global Credit"},
            },
            "Global Credit",
            1.0,
        ),
        (
            {
                "position_id": "MISSING_POSITION_CURRENCY",
                "security_id": "MISSING_POSITION_CURRENCY",
                "valuation_date": "2025-01-01",
                "cash_flow_currency": "EUR",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "105",
                "cash_flows": [{"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"}],
                "dimensions": {"sector": "Private Markets"},
            },
            "Private Markets",
            1.0,
        ),
        (
            {
                "position_id": "MISSING_CASH_FLOW_CURRENCY",
                "security_id": "MISSING_CASH_FLOW_CURRENCY",
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "position_to_portfolio_fx_rate": "1.2",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "105",
                "cash_flows": [{"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"}],
                "dimensions": {"sector": "Emerging Markets"},
            },
            "Emerging Markets",
            1.0,
        ),
    ],
    ids=[
        "dropped-valuation",
        "discarded-cash-flow",
        "discarded-after-fx-conversion",
        "missing-cross-currency-fx",
        "missing-position-currency-identity",
        "missing-cash-flow-currency-identity",
    ],
)
def test_stateful_contribution_retains_membership_and_refuses_incomplete_economics(
    client,
    monkeypatch,
    position_row,
    expected_sector,
    expected_contribution,
):
    from types import SimpleNamespace

    async def source_input(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            position_source_rows_complete=True,
            portfolio_input=SimpleNamespace(
                portfolio_currency="USD",
                reporting_currency=None,
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    }
                ],
            ),
            position_rows=[position_row],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        source_input,
    )

    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_DROPPED_MEMBERSHIP",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": "NET", "dimensions": ["sector"]},
        },
        headers={"X-Tenant-Id": "tenant-sg"},
    )

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    row = period["levels"][0]["rows"][0]
    assert row["key"] == {"sector": expected_sector}
    assert row["contribution"] == pytest.approx(expected_contribution)
    assert row["group_return"] == {
        "status": "UNAVAILABLE",
        "period_return_pct": None,
        "currency": None,
        "series": [],
        "reason": "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE",
        "return_basis": "SOURCE_POSITION_VALUATION_TWR",
        "weight_basis": "BEGINNING_CAPITAL_RATIO",
    }


def test_stateful_contribution_applies_effective_membership_before_hierarchy_aggregation(client, monkeypatch):
    from types import SimpleNamespace

    async def source_input(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            position_source_rows_complete=True,
            portfolio_input=SimpleNamespace(
                portfolio_currency="USD",
                reporting_currency=None,
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "100",
                        "ending_market_value": "101",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "101",
                        "ending_market_value": "103.02",
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "RECLASSIFIED_POSITION",
                    "security_id": "RECLASSIFIED_POSITION",
                    "valuation_date": "2025-01-01",
                    "position_currency": "USD",
                    "beginning_market_value_portfolio_currency": "100",
                    "ending_market_value_portfolio_currency": "101",
                    "cash_flows": [],
                    "dimensions": {"sector": "Sector A"},
                },
                {
                    "position_id": "RECLASSIFIED_POSITION",
                    "security_id": "RECLASSIFIED_POSITION",
                    "valuation_date": "2025-01-02",
                    "position_currency": "USD",
                    "beginning_market_value_portfolio_currency": "101",
                    "ending_market_value_portfolio_currency": "103.02",
                    "cash_flows": [],
                    "dimensions": {"sector": "Sector B"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        source_input,
    )

    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_RECLASSIFICATION",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": "NET", "dimensions": ["sector"]},
            "emit": {"threshold_weight": 0},
        },
        headers={"X-Tenant-Id": "tenant-sg"},
    )

    assert response.status_code == 200
    rows = {row["key"]["sector"]: row for row in response.json()["results_by_period"]["SI"]["levels"][0]["rows"]}
    assert rows["Sector A"]["contribution"] > 0
    assert rows["Sector B"]["contribution"] > 0
    assert rows["Sector A"]["weight_avg"] == pytest.approx(50.0)
    assert rows["Sector B"]["weight_avg"] == pytest.approx(50.0)
    assert sum(row["weight_avg"] for row in rows.values()) == pytest.approx(100.0)
    assert rows["Sector A"]["group_return"]["series"] == [
        {"date": "2025-01-01", "return_pct": 1.0, "portfolio_weight_pct": 100.0},
        {"date": "2025-01-02", "return_pct": 0.0, "portfolio_weight_pct": 0.0},
    ]
    assert rows["Sector B"]["group_return"]["series"] == [
        {"date": "2025-01-01", "return_pct": 0.0, "portfolio_weight_pct": 0.0},
        {"date": "2025-01-02", "return_pct": 2.0, "portfolio_weight_pct": 100.0},
    ]


@pytest.mark.parametrize(
    ("portfolio_currency", "reporting_currency", "position_currencies"),
    [
        ("EUR", "USD", ("EUR", "USD")),
        ("USD", "USD", ("USD", "USD")),
    ],
)
def test_contribution_stateful_base_only_keeps_core_reporting_currency_on_group_evidence(
    client,
    monkeypatch,
    portfolio_currency,
    reporting_currency,
    position_currencies,
):
    """Exercise the HTTP workflow with Core-selected reporting-currency valuation rows."""

    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            position_source_rows_complete=True,
            portfolio_input=SimpleNamespace(
                portfolio_currency=portfolio_currency,
                reporting_currency=reporting_currency,
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1100",
                    }
                ],
            ),
            position_rows=[
                {
                    "position_id": "CORE_EQUITY",
                    "security_id": "CORE_EQUITY",
                    "position_currency": position_currencies[0],
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_reporting_currency": "600",
                    "ending_market_value_reporting_currency": "660",
                    "cash_flows": [],
                    "dimensions": {"sector": "Equity"},
                },
                {
                    "position_id": "CORE_BOND",
                    "security_id": "CORE_BOND",
                    "position_currency": position_currencies[1],
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_reporting_currency": "400",
                    "ending_market_value_reporting_currency": "440",
                    "cash_flows": [],
                    "dimensions": {"sector": "Fixed Income"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )
    payload = {
        "portfolio_id": "CONTRIB_CORE_REPORTING_CURRENCY",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "currency": portfolio_currency,
        "currency_mode": "BASE_ONLY",
        "report_ccy": reporting_currency,
        "hierarchy": ["sector"],
        "input_mode": "stateful",
        "stateful_input": {"metric_basis": "NET"},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    rows = body["results_by_period"]["SI"]["levels"][0]["rows"]
    assert body["input_mode"] == "stateful"
    assert body["results_by_period"]["SI"]["total_portfolio_return"] == pytest.approx(10.0)
    assert {row["group_return"]["currency"] for row in rows} == {reporting_currency}
    assert [row["group_return"]["period_return_pct"] for row in rows] == pytest.approx([10.0, 10.0])
    evidence = body["currency_evidence"]
    assert evidence["portfolio_base_currency"] == portfolio_currency
    assert evidence["applied_report_ccy"] == reporting_currency
    assert evidence["reason"] == (
        "SOURCE_REPORTING_CURRENCY_VALUATIONS_APPLIED"
        if portfolio_currency != reporting_currency
        else "PORTFOLIO_BASE_CURRENCY_APPLIED"
    )


def test_contribution_stateful_base_only_refuses_incomplete_core_reporting_value_pairs(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                portfolio_currency="EUR",
                reporting_currency="USD",
                observations=[
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1100"}
                ],
            ),
            position_rows=[
                {
                    "position_id": "CORE_REPORTING",
                    "security_id": "CORE_REPORTING",
                    "position_currency": "EUR",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_reporting_currency": "600",
                    "ending_market_value_reporting_currency": "660",
                    "cash_flows": [],
                    "dimensions": {"sector": "Equity"},
                },
                {
                    "position_id": "CORE_FALLBACK",
                    "security_id": "CORE_FALLBACK",
                    "position_currency": "EUR",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "400",
                    "ending_market_value_portfolio_currency": "440",
                    "cash_flows": [],
                    "dimensions": {"sector": "Fixed Income"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )
    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_CORE_INCOMPLETE_REPORTING",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "currency": "EUR",
            "currency_mode": "BASE_ONLY",
            "report_ccy": "USD",
            "hierarchy": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": "NET"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "REPORTING_CURRENCY_VALUATIONS_INCOMPLETE"
    assert "CORE_FALLBACK" in response.json()["detail"]


def test_contribution_stateful_base_only_uses_portfolio_values_without_core_reporting_currency(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            position_source_rows_complete=True,
            portfolio_input=SimpleNamespace(
                portfolio_currency="EUR",
                reporting_currency=None,
                observations=[
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1100"}
                ],
            ),
            position_rows=[
                {
                    "position_id": "CORE_UNDECLARED_REPORTING",
                    "security_id": "CORE_UNDECLARED_REPORTING",
                    "position_currency": "EUR",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1100",
                    "beginning_market_value_reporting_currency": "2000",
                    "ending_market_value_reporting_currency": "2600",
                    "cash_flows": [],
                    "dimensions": {"sector": "Equity"},
                }
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )
    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_CORE_UNDECLARED_REPORTING",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "currency": "EUR",
            "currency_mode": "BASE_ONLY",
            "report_ccy": "USD",
            "hierarchy": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": "NET"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    row = body["results_by_period"]["SI"]["levels"][0]["rows"][0]
    assert row["group_return"]["currency"] == "EUR"
    assert row["group_return"]["period_return_pct"] == pytest.approx(10.0)
    assert body["currency_evidence"]["applied_report_ccy"] == "EUR"


def test_contribution_stateful_base_only_refuses_cross_currency_cash_flows_without_source_fx(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                portfolio_currency="EUR",
                reporting_currency="USD",
                observations=[
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1100"}
                ],
            ),
            position_rows=[
                {
                    "position_id": "CORE_CASH_FLOW",
                    "security_id": "CORE_CASH_FLOW",
                    "cash_flow_currency": "EUR",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_reporting_currency": "600",
                    "ending_market_value_reporting_currency": "660",
                    "cash_flows": [{"amount": "5", "timing": "bod"}],
                    "dimensions": {"sector": "Equity"},
                }
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )
    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_CORE_CASH_FLOW_FX_INCOMPLETE",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "currency": "EUR",
            "currency_mode": "BASE_ONLY",
            "report_ccy": "USD",
            "hierarchy": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": "NET"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "REPORTING_CURRENCY_CASH_FLOW_FX_INCOMPLETE"
    assert "CORE_CASH_FLOW" in response.json()["detail"]


def test_contribution_stateful_base_only_reports_core_cash_flow_fx_pairs(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                portfolio_currency="EUR",
                reporting_currency="USD",
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "132",
                        "ending_market_value": "145.2",
                        "cash_flows": [{"amount": "13.2", "timing": "bod"}],
                    }
                ],
            ),
            position_rows=[
                {
                    "position_id": "CORE_CASH_FLOW",
                    "security_id": "CORE_CASH_FLOW",
                    "position_currency": "EUR",
                    "cash_flow_currency": "EUR",
                    "position_to_portfolio_fx_rate": "1",
                    "portfolio_to_reporting_fx_rate": "1.1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_reporting_currency": "132",
                    "ending_market_value_reporting_currency": "145.2",
                    "cash_flows": [{"amount": "12", "timing": "bod"}],
                    "dimensions": {"sector": "Equity"},
                }
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )
    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_CORE_CASH_FLOW_FX_EVIDENCE",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "currency": "EUR",
            "currency_mode": "BASE_ONLY",
            "report_ccy": "USD",
            "hierarchy": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {"metric_basis": "NET"},
        },
    )

    assert response.status_code == 200
    evidence = response.json()["currency_evidence"]
    assert evidence["fixing_policy"] == "SOURCE_PRECONVERTED_POSITION_VALUATIONS_AND_CASH_FLOWS"
    assert evidence["applied_pairs"] == ["EUR/USD"]


def test_contribution_stateful_cash_only_external_flows_do_not_create_position_flow_residuals(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": "2025-01-17",
                        "beginning_market_value": "10000",
                        "ending_market_value": "10000",
                        "cash_flows": [],
                    },
                    {
                        "valuation_date": "2025-01-18",
                        "beginning_market_value": "10000",
                        "ending_market_value": "15000",
                        "cash_flows": [{"amount": "5000", "timing": "bod", "cash_flow_type": "external_flow"}],
                    },
                    {
                        "valuation_date": "2025-01-19",
                        "beginning_market_value": "15000",
                        "ending_market_value": "13000",
                        "cash_flows": [{"amount": "-2000", "timing": "eod", "cash_flow_type": "external_flow"}],
                    },
                    {
                        "valuation_date": "2025-01-20",
                        "beginning_market_value": "13000",
                        "ending_market_value": "13000",
                        "cash_flows": [],
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "CASH_USD_1",
                    "security_id": "CASH_USD_1",
                    "valuation_date": "2025-01-17",
                    "beginning_market_value_portfolio_currency": "10000",
                    "ending_market_value_portfolio_currency": "10000",
                    "cash_flows": [],
                    "dimensions": {"sector": "Cash"},
                },
                {
                    "position_id": "CASH_USD_1",
                    "security_id": "CASH_USD_1",
                    "valuation_date": "2025-01-18",
                    "beginning_market_value_portfolio_currency": "10000",
                    "ending_market_value_portfolio_currency": "15000",
                    "cash_flows": [{"amount": "5000", "timing": "bod", "cash_flow_type": "external_flow"}],
                    "dimensions": {"sector": "Cash"},
                },
                {
                    "position_id": "CASH_USD_1",
                    "security_id": "CASH_USD_1",
                    "valuation_date": "2025-01-19",
                    "beginning_market_value_portfolio_currency": "15000",
                    "ending_market_value_portfolio_currency": "13000",
                    "cash_flows": [{"amount": "-2000", "timing": "eod", "cash_flow_type": "external_flow"}],
                    "dimensions": {"sector": "Cash"},
                },
                {
                    "position_id": "CASH_USD_1",
                    "security_id": "CASH_USD_1",
                    "valuation_date": "2025-01-20",
                    "beginning_market_value_portfolio_currency": "13000",
                    "ending_market_value_portfolio_currency": "13000",
                    "cash_flows": [],
                    "dimensions": {"sector": "Cash"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL_CASH_ONLY",
        "report_start_date": "2025-01-17",
        "report_end_date": "2025-01-20",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "emit": {"timeseries": True},
        "input_mode": "stateful",
        "stateful_input": {"metric_basis": "NET"},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    explicit = body["results_by_period"]["EXPLICIT"]
    assert explicit["total_portfolio_return"] == pytest.approx(0.0)
    assert explicit["total_contribution"] == pytest.approx(0.0)
    assert body["audit"]["counts"]["position_flow_residual_days"] == 0
    assert body["audit"]["counts"]["position_flow_residual_max_bp"] == 0
    assert body["audit"]["counts"]["position_flow_residual_sum_bp"] == 0
    assert not any("non-flow-neutral scoped slice" in note for note in body["diagnostics"]["notes"])


def test_contribution_stateful_converts_non_base_cash_flows_using_explicit_fx_metadata(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                portfolio_currency="EUR",
                reporting_currency="USD",
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "132",
                        "ending_market_value": "145.2",
                        "cash_flows": [{"amount": "13.2", "timing": "bod", "cash_flow_type": "external_flow"}],
                    }
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_EUR_1",
                    "security_id": "SEC_EUR_1",
                    "position_currency": "EUR",
                    "cash_flow_currency": "EUR",
                    "position_to_portfolio_fx_rate": "1.20",
                    "portfolio_to_reporting_fx_rate": "1.10",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_reporting_currency": "132",
                    "ending_market_value_reporting_currency": "145.2",
                    "cash_flows": [{"amount": "10", "timing": "bod", "cash_flow_type": "external_flow"}],
                    "dimensions": {"sector": "Technology"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL_FX_CF",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "report_ccy": "USD",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "emit": {"timeseries": True, "by_position_timeseries": True},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    itd = response.json()["results_by_period"]["SI"]
    assert itd["total_contribution"] == pytest.approx(0.0)
    assert itd["by_position_timeseries"][0]["series"][0]["contribution"] == pytest.approx(0.0)


def test_contribution_stateful_emit_timeseries_returns_series(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                portfolio_currency="USD",
                reporting_currency="USD",
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1030.2",
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "position_currency": "EUR",
                    "cash_flow_currency": "EUR",
                    "position_to_portfolio_fx_rate": "1.20",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                    "cash_flows": [
                        {"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"},
                        {"amount": "-5", "timing": "bod", "cash_flow_type": "external_flow"},
                    ],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "1010",
                    "ending_market_value_portfolio_currency": "1030.2",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL_SERIES",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "currency": "USD",
        "currency_mode": "BASE_ONLY",
        "report_ccy": "USD",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "emit": {"timeseries": True, "by_position_timeseries": True},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    result = response.json()["results_by_period"]["SI"]
    assert len(result["timeseries"]) == 2
    assert len(result["by_position_timeseries"]) == 1
    assert result["by_position_timeseries"][0]["position_id"] == "SEC_1"
    assert len(result["by_position_timeseries"][0]["series"]) == 2
    evidence = response.json()["currency_evidence"]
    assert evidence["fixing_policy"] == "SOURCE_PRECONVERTED_POSITION_VALUATIONS_AND_CASH_FLOWS"
    assert evidence["applied_pairs"] == ["EUR/USD"]

    default_currency_payload = {
        key: value for key, value in payload.items() if key not in {"currency", "currency_mode", "report_ccy"}
    }
    default_currency_response = client.post("/performance/contribution", json=default_currency_payload)
    assert default_currency_response.status_code == 200
    assert default_currency_response.json()["currency_evidence"]["fx_source"] == "none"


def test_contribution_stateful_offloads_on_resolved_position_count(client, monkeypatch):
    original_window_threshold = settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS
    original_position_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS = 30
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 2

    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
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
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "600",
                    "ending_market_value_portfolio_currency": "606",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "606",
                    "ending_market_value_portfolio_currency": "612.06",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_2",
                    "security_id": "SEC_2",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "400",
                    "ending_market_value_portfolio_currency": "404",
                    "cash_flows": [],
                    "dimensions": {"sector": "Healthcare"},
                },
                {
                    "position_id": "SEC_2",
                    "security_id": "SEC_2",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "404",
                    "ending_market_value_portfolio_currency": "408.04",
                    "cash_flows": [],
                    "dimensions": {"sector": "Healthcare"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL_ASYNC",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        accepted = client.post("/performance/contribution", json=payload)

        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]
        execution = execution_registry.get_execution(UUID(calculation_id))
        assert execution is not None
        assert execution.requested_window["position_count"] == 2
        assert execution.requested_window["input_mode"] == "stateful"
        job = compute_job_store.get_job(calculation_id)
        assert job is not None
        assert "stateful_input" not in job.request_payload
        assert "portfolio_data" in job.request_payload["resolved_request"]
        assert job.request_payload["source_input_mode"] == "stateful"

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/contribution/results/{calculation_id}")
        assert complete.status_code == 200
        assert complete.json()["input_mode"] == "stateful"
    finally:
        settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_position_threshold


def test_contribution_stateful_promoted_async_replays_identical_retry(client, monkeypatch):
    original_window_threshold = settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS
    original_position_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS = 30
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 2

    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "600",
                    "ending_market_value_portfolio_currency": "606",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "606",
                    "ending_market_value_portfolio_currency": "612.06",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_2",
                    "security_id": "SEC_2",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "400",
                    "ending_market_value_portfolio_currency": "404",
                    "cash_flows": [],
                    "dimensions": {"sector": "Healthcare"},
                },
                {
                    "position_id": "SEC_2",
                    "security_id": "SEC_2",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "404",
                    "ending_market_value_portfolio_currency": "408.04",
                    "cash_flows": [],
                    "dimensions": {"sector": "Healthcare"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "CONTRIB_STATEFUL_ASYNC_REPLAY",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        first = client.post("/performance/contribution", json=payload)
        second = client.post("/performance/contribution", json=payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["calculation_id"] == payload["calculation_id"]
        assert second.json()["calculation_id"] == payload["calculation_id"]
    finally:
        settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_position_threshold


def test_contribution_stateful_hashes_follow_resolved_inputs(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
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
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "1010",
                    "ending_market_value_portfolio_currency": "1020.1",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
            ],
            position_source_rows_complete=True,
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL_HASH",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    expected_request = ContributionRequest.model_validate(
        {
            "calculation_id": body["calculation_id"],
            "portfolio_id": "CONTRIB_STATEFUL_HASH",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {
                        "perf_date": "2025-01-01",
                        "begin_mv": "1000",
                        "end_mv": "1010",
                        "bod_cf": "0",
                        "eod_cf": "0",
                    },
                    {
                        "perf_date": "2025-01-02",
                        "begin_mv": "1010",
                        "end_mv": "1020.1",
                        "bod_cf": "0",
                        "eod_cf": "0",
                    },
                ],
            },
            "positions_data": [
                {
                    "position_id": "SEC_1",
                    "meta": {
                        "security_id": "SEC_1",
                        "sector": "Technology",
                        "_source_economics": {
                            "cash_flow_type_counts": {},
                            "source_contract": "PositionTimeseriesInput:v1",
                            "valuation_status": None,
                        },
                        "_source_hierarchy_memberships": [
                            {"perf_date": "2025-01-01", "sector": "Technology"},
                            {"perf_date": "2025-01-02", "sector": "Technology"},
                        ],
                    },
                    "valuation_points": [
                        {
                            "perf_date": "2025-01-01",
                            "begin_mv": "1000",
                            "end_mv": "1010",
                            "bod_cf": "0",
                            "eod_cf": "0",
                        },
                        {
                            "perf_date": "2025-01-02",
                            "begin_mv": "1010",
                            "end_mv": "1020.1",
                            "bod_cf": "0",
                            "eod_cf": "0",
                        },
                    ],
                }
            ],
        }
    )
    expected_input_fingerprint, expected_calculation_hash = generate_request_fingerprint(
        resolved_contribution_identity_payload(
            expected_request,
            portfolio_base_currency=expected_request.currency,
            source_preconverted_reporting_currency=None,
            source_position_window_complete=True,
        ),
        calculation_engine_version(settings),
    )

    assert body["meta"]["input_fingerprint"] == expected_input_fingerprint
    assert body["meta"]["calculation_hash"] == expected_calculation_hash


@pytest.mark.parametrize("currency_mode", ["BASE_ONLY", "BOTH"])
def test_contribution_stateful_same_currency_decomposition_availability(client, monkeypatch, currency_mode):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "position_currency": "USD",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                    "beginning_market_value_position_currency": "1000",
                    "ending_market_value_position_currency": "1010",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                }
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "currency_mode": currency_mode,
        "report_ccy": "USD",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    result = body["results_by_period"]["SI"]
    assert body["input_mode"] == "stateful"
    position = result["position_contributions"][0]
    assert position["total_contribution"] == pytest.approx(1.0)
    if currency_mode == "BOTH":
        assert position["local_contribution"] == pytest.approx(1.0)
        assert position["fx_contribution"] == pytest.approx(0.0)
    else:
        assert position["local_contribution"] is None
        assert position["fx_contribution"] is None
    assert body["currency_evidence"]["applied_report_ccy"] == "USD"
    assert body["currency_evidence"]["restated"] is False
    assert body["currency_evidence"]["fx_coverage"] == "none"


@pytest.mark.parametrize(
    ("first_currency", "expected_error"),
    [(None, "POSITION_CURRENCY_INCOMPLETE"), ("EUR", "POSITION_CURRENCY_CONFLICT")],
)
@pytest.mark.parametrize("reverse_rows", [False, True])
def test_contribution_stateful_both_rejects_dated_position_currency_gap(
    client, monkeypatch, first_currency, expected_error, reverse_rows
):
    from types import SimpleNamespace

    async def _source(**kwargs):  # noqa: ARG001
        position_rows = [
            {
                "position_id": "SEC_1",
                "valuation_date": "2025-01-01",
                **({"position_currency": first_currency} if first_currency else {}),
                "beginning_market_value_portfolio_currency": "1000",
                "ending_market_value_portfolio_currency": "1010",
                "cash_flows": [],
            },
            {
                "position_id": "SEC_1",
                "valuation_date": "2025-01-02",
                "position_currency": "USD",
                "beginning_market_value_portfolio_currency": "1010",
                "ending_market_value_portfolio_currency": "1020",
                "cash_flows": [],
            },
        ]
        if reverse_rows:
            position_rows.reverse()
        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                portfolio_currency="USD",
                observations=[
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020"},
                ],
            ),
            position_rows=position_rows,
        )

    monkeypatch.setattr("app.services.contribution_mode_service.retrieve_stateful_contribution_source_input", _source)
    response = client.post(
        "/performance/contribution",
        json={
            "portfolio_id": "CONTRIB_DATED_CURRENCY_GAP",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "currency_mode": "BOTH",
            "report_ccy": "USD",
            "fx": {
                "rates": [
                    {"ccy": "EUR", "date": "2024-12-31", "rate": 1.1},
                    {"ccy": "EUR", "date": "2025-01-01", "rate": 1.1},
                ]
            },
            "input_mode": "stateful",
            "stateful_input": {},
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == expected_error


def test_contribution_stateful_currency_mode_both_requires_fx_for_mixed_currency_positions(client, monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        from types import SimpleNamespace

        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "position_currency": "EUR",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                    "beginning_market_value_position_currency": "900",
                    "ending_market_value_position_currency": "909",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                }
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 422
    assert "requires fx.rates" in response.json()["detail"]


def test_contribution_async_result_not_found_and_failed(client, happy_path_payload, mocker):
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    original_attempts = settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = 1

    mocker.patch("app.workers.compute_executor_worker.calculate_contribution", side_effect=RuntimeError("explode"))

    try:
        missing = client.get("/performance/contribution/results/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404

        accepted = client.post("/performance/contribution", json=happy_path_payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        assert drain_compute_queue() == 1

        failed = client.get(f"/performance/contribution/results/{calculation_id}")
        assert failed.status_code == 409
        assert (
            failed.json()["detail"] == "Compute job execution failed unexpectedly. Use the correlation_id for support."
        )
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold
        settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = original_attempts


def test_contribution_async_duplicate_submission_replays_same_request(client, happy_path_payload):
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    payload = {**happy_path_payload, "calculation_id": str(uuid4())}

    try:
        first = client.post("/performance/contribution", json=payload)
        second = client.post("/performance/contribution", json=payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["calculation_id"] == payload["calculation_id"]
        assert second.json()["calculation_id"] == payload["calculation_id"]
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_contribution_async_duplicate_submission_conflicts_on_payload_drift(client, happy_path_payload):
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    calculation_id = str(uuid4())
    first_payload = {**happy_path_payload, "calculation_id": calculation_id}
    second_payload = {**first_payload, "hierarchy": ["sector"]}

    try:
        first = client.post("/performance/contribution", json=first_payload)
        second = client.post("/performance/contribution", json=second_payload)

        assert first.status_code == 202
        assert second.status_code == 409
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_contribution_async_replay_self_heals_missing_compute_job(client, happy_path_payload):
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    calculation_id = uuid4()
    payload = {**happy_path_payload, "calculation_id": str(calculation_id)}

    try:
        request_model = ContributionAnalyticsRequest.model_validate(payload)
        input_fingerprint, calculation_hash = generate_canonical_hash(
            request_model,
            calculation_engine_version(settings),
        )
        execution_registry.create_execution(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            portfolio_id=payload["portfolio_id"],
            execution_mode="async",
            requested_window=build_contribution_execution_window(request_model),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            tenant_id="tenant-a",
        )

        response = client.post("/performance/contribution", json=payload)

        assert response.status_code == 202
        assert response.json()["calculation_id"] == str(calculation_id)
        execution = execution_registry.get_execution(calculation_id)
        assert execution is not None
        stages = {stage.stage_name: stage for stage in execution.stages}
        assert stages["submission"].status.value == "complete"
        job = compute_job_store.get_job(calculation_id)
        assert job is not None
        assert job.job_status.value == "pending"
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_contribution_async_conflict_does_not_leave_orphan_execution(client, happy_path_payload):
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    calculation_id = uuid4()
    payload = {**happy_path_payload, "calculation_id": str(calculation_id)}
    drifted_job_payload = {**payload, "hierarchy": ["sector"]}

    try:
        compute_job_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            tenant_id="tenant-test",
            request_payload=drifted_job_payload,
        )

        response = client.post("/performance/contribution", json=payload)

        assert response.status_code == 409
        assert execution_registry.get_execution(calculation_id) is None
        job = compute_job_store.get_job(calculation_id)
        assert job is not None
        assert job.request_payload["hierarchy"] == ["sector"]
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_admission_persists_the_presented_tenant_on_the_route_the_api_actually_uses(client, happy_path_payload):
    """A job's authority is captured at admission, from the header the caller sent.

    Asserted against the stored row rather than a response field, because the failure
    this guards against is invisible in the response: the API returned 202 for every
    offloaded job while writing no tenant at all, and nothing surfaced until the
    worker tried to run one.

    Deliberately through the HTTP route. The unit suite covered `enqueue_job`, which
    only the recovery drill calls, and reported an invariant that was false for every
    real submission. A test of the guarded path is not a test of the path.
    """

    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    try:
        accepted = client.post(
            "/performance/contribution",
            json=happy_path_payload,
            headers={"X-Tenant-Id": "tenant-sg"},
        )
        assert accepted.status_code == 202
        calculation_id = UUID(accepted.json()["calculation_id"])

        stored = compute_job_store.get_job(calculation_id)
        assert stored is not None
        assert stored.tenant_id == "tenant-sg"
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_admission_records_an_absent_tenant_as_absent_rather_than_as_unknown(client, happy_path_payload):
    """Nothing presented is stored as nothing presented -- not as NULL.

    The distinction carries the whole slice. `""` means the caller presented no
    tenant, which the worker replays faithfully so that stateless work succeeds
    offloaded exactly as it does inline, and Core-bound work is refused at the
    boundary exactly as it is inline. `NULL` means the row predates the column and
    what was presented was never recorded, which cannot be replayed at all and is
    refused.

    Collapse the two and every legacy row becomes indistinguishable from a live
    tenantless submission, which is the point at which "refuse, do not default"
    stops being implementable.
    """

    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    try:
        accepted = client.post(
            "/performance/contribution",
            json=happy_path_payload,
            headers={"X-Tenant-Id": ""},
        )
        assert accepted.status_code == 202
        calculation_id = UUID(accepted.json()["calculation_id"])

        stored = compute_job_store.get_job(calculation_id)
        assert stored is not None
        assert stored.tenant_id == "", "an absent tenant was not distinguished from an unrecorded one"
        assert stored.tenant_id is not None
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold
