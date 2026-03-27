import os
import shutil
from uuid import UUID, uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.endpoints.contribution import _build_execution_window
from app.core.config import get_settings
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.models.contribution_requests import ContributionRequest
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from core.repro import generate_canonical_hash
from engine.exceptions import EngineCalculationError
from main import app
from tests.conftest import drain_compute_queue, drain_lineage_queue

settings = get_settings()


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

    with TestClient(app) as c:
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
    assert "ITD" in response_data["results_by_period"]


def test_contribution_endpoint_reports_zero_grouped_return_alignment_drift_for_simple_aligned_case(client):
    payload = {
        "portfolio_id": "CONTRIB_ALIGNED_RESETS",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
    period_status = body["results_by_period"]["ITD"]["average_weight_methodology_status"]
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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
    data = response.json()["results_by_period"]["ITD"]
    assert data["total_contribution"] == pytest.approx(4.91429, abs=1e-5)


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


def test_contribution_endpoint_with_timeseries(client, happy_path_payload):
    """Tests that the endpoint correctly returns time-series data when requested."""
    payload = happy_path_payload.copy()
    payload["emit"] = {"timeseries": True, "by_position_timeseries": True}
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    body = response.json()["results_by_period"]["ITD"]
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
    data = response.json()["results_by_period"]["ITD"]
    assert "summary" in data
    assert data["summary"]["portfolio_contribution"] == pytest.approx(2.95327, abs=1e-5)


def test_contribution_endpoint_weight_fields_use_percentage_units_for_position_and_hierarchy_outputs(client):
    base_payload = {
        "portfolio_id": "CONTRIB_WEIGHT_UNITS",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
        row["position_id"]: row
        for row in position_response.json()["results_by_period"]["ITD"]["position_contributions"]
    }
    hierarchy_rows = {
        row["key"]["sector"]: row for row in hierarchy_response.json()["results_by_period"]["ITD"]["levels"][0]["rows"]
    }

    assert position_rows["Stock_A"]["average_weight"] == pytest.approx(60.0)
    assert position_rows["Stock_B"]["average_weight"] == pytest.approx(40.0)
    assert sum(row["average_weight"] for row in position_rows.values()) == pytest.approx(100.0)
    assert hierarchy_rows["Technology"]["weight_avg"] == pytest.approx(60.0)
    assert hierarchy_rows["Healthcare"]["weight_avg"] == pytest.approx(40.0)
    assert sum(row["weight_avg"] for row in hierarchy_rows.values()) == pytest.approx(100.0)


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


def test_contribution_endpoint_error_handling(client, mocker):
    """Tests that a generic server error is raised for calculation failures."""
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data", side_effect=EngineCalculationError("Test Error")
    )
    payload = {
        "portfolio_id": "ERROR",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
    period_status = body["results_by_period"]["ITD"]["average_weight_methodology_status"]
    assert period_status["status"] == "PROMOTED"
    assert period_status["is_material_shadow"] is True
    assert period_status["is_cutover_candidate"] is True
    assert period_status["is_promoted"] is True
    assert period_status["blocker_reason_codes"] == []
    position_contributions = body["results_by_period"]["ITD"]["position_contributions"]
    assert position_contributions[0]["average_weight"] == pytest.approx(95.0)
    assert position_contributions[1]["average_weight"] == pytest.approx(5.0)
    assert any("promotion was applied" in note for note in body["diagnostics"]["notes"])
    assert any(
        "strong candidates for a future denominator cutover study" in note for note in body["diagnostics"]["notes"]
    )


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
        assert "ITD" in body["results_by_period"]
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
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "CONTRIB_STATEFUL"
    assert body["input_mode"] == "stateful"
    assert "ITD" in body["results_by_period"]


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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "emit": {"timeseries": True, "by_position_timeseries": True},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    itd = response.json()["results_by_period"]["ITD"]
    assert itd["total_contribution"] == pytest.approx(0.0)
    assert itd["by_position_timeseries"][0]["series"][0]["contribution"] == pytest.approx(0.0)


def test_contribution_stateful_emit_timeseries_returns_series(client, monkeypatch):
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
                        "ending_market_value": "1030.2",
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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "emit": {"timeseries": True, "by_position_timeseries": True},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    result = response.json()["results_by_period"]["ITD"]
    assert len(result["timeseries"]) == 2
    assert len(result["by_position_timeseries"]) == 1
    assert result["by_position_timeseries"][0]["position_id"] == "SEC_1"
    assert len(result["by_position_timeseries"][0]["series"]) == 2


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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
        assert "portfolio_data" in job.request_payload

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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL_HASH",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
                    "meta": {"security_id": "SEC_1", "sector": "Technology"},
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
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash(
        expected_request, settings.APP_VERSION
    )

    assert body["meta"]["input_fingerprint"] == expected_input_fingerprint
    assert body["meta"]["calculation_hash"] == expected_calculation_hash


def test_contribution_stateful_currency_mode_both_allows_same_currency_positions(client, monkeypatch):
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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    result = body["results_by_period"]["ITD"]
    assert body["input_mode"] == "stateful"
    assert result["position_contributions"][0]["local_contribution"] == pytest.approx(1.0)
    assert result["position_contributions"][0]["fx_contribution"] == pytest.approx(0.0)


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
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
        assert failed.json()["detail"] == "explode"
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
        input_fingerprint, calculation_hash = generate_canonical_hash(request_model, settings.APP_VERSION)
        execution_registry.create_execution(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            portfolio_id=payload["portfolio_id"],
            execution_mode="async",
            requested_window=_build_execution_window(request_model),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
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
