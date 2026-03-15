import os
import shutil
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.attribution_requests import AttributionRequest
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from core.periods import ResolvedPeriod
from core.repro import generate_canonical_hash
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
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


def test_attribution_endpoint_by_instrument_happy_path(client):
    """Tests the /performance/attribution endpoint end-to-end with a valid 'by_instrument' payload."""
    payload = {
        "portfolio_id": "ATTRIB_BY_INST_01",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1018.5}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"sector": "Health"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 406.5}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 0.5}],
            },
            {
                "key": {"sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.5}],
            },
        ],
    }

    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    response_data = response.json()["results_by_period"]["ITD"]
    assert response_data["reconciliation"]["total_active_return"] == pytest.approx(0.1)
    level = response_data["levels"][0]
    tech_group = next(g for g in level["groups"] if g["key"]["sector"] == "Tech")
    assert tech_group["selection"] == pytest.approx(0.25)


def test_attribution_lineage_flow(client):
    """Tests that lineage is correctly captured for an attribution request."""
    payload = {
        "portfolio_id": "ATTRIB_LINEAGE_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.02, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    attrib_response = client.post("/performance/attribution", json=payload)
    assert attrib_response.status_code == 200
    calculation_id = attrib_response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()

    assert lineage_data["calculation_type"] == "Attribution"
    assert "aligned_panel.csv" in lineage_data["artifacts"]
    assert "single_period_effects.csv" in lineage_data["artifacts"]


def test_attribution_endpoint_hierarchical(client):
    """Tests multi-level hierarchical attribution, ensuring bottom-up aggregation is correct."""
    payload = {
        "portfolio_id": "HIERARCHY_01",
        "mode": "by_instrument",
        "group_by": ["assetClass", "sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"assetClass": "Equity", "sector": "Tech"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"assetClass": "Equity", "sector": "Health"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 303}],
            },
            {
                "instrument_id": "UST",
                "meta": {"assetClass": "Bond", "sector": "Government"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 309}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"assetClass": "Equity", "sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.4}],
            },
            {
                "key": {"assetClass": "Equity", "sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.3}],
            },
            {
                "key": {"assetClass": "Bond", "sector": "Government"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.3}],
            },
        ],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["ITD"]
    assert len(data["levels"]) == 2
    level_ac = data["levels"][0]
    level_sector = data["levels"][1]
    equity_ac_effects = next(g for g in level_ac["groups"] if g["key"]["assetClass"] == "Equity")
    tech_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Tech")
    health_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Health")
    assert equity_ac_effects["allocation"] == pytest.approx(
        tech_sector_effects["allocation"] + health_sector_effects["allocation"]
    )
    assert equity_ac_effects["selection"] == pytest.approx(
        tech_sector_effects["selection"] + health_sector_effects["selection"]
    )


def test_attribution_endpoint_currency_attribution(client):
    """Tests the Karnosky-Singer currency attribution model end-to-end."""
    payload = {
        "portfolio_id": "FX_ATTRIB_01",
        "mode": "by_instrument",
        "group_by": ["currency"],
        "linking": "none",
        "frequency": "daily",
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 103.02}],
        },
        "instruments_data": [
            {
                "instrument_id": "EUR_ASSET",
                "meta": {"currency": "EUR"},
                "valuation_points": [
                    {"day": 1, "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0}
                ],  # 2% local return
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"currency": "EUR"},
                "observations": [
                    {
                        "date": "2025-01-01",
                        "weight_bop": 1.0,
                        "return_local": 0.015,  # 1.5% local return
                        "return_fx": 0.01,  # 1% fx return
                        "return_base": 0.02515,  # (1.015 * 1.01) - 1
                    }
                ],
            }
        ],
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.00},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.01},  # 1% fx return
            ]
        },
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["ITD"]

    assert "currency_attribution" in data
    assert data["currency_attribution"] is not None
    eur_effects = data["currency_attribution"][0]["effects"]

    assert eur_effects["local_allocation"] == pytest.approx(0.0)
    assert eur_effects["local_selection"] == pytest.approx(0.5)
    assert eur_effects["currency_allocation"] == pytest.approx(0.0)
    assert eur_effects["currency_selection"] == pytest.approx(0.005)
    assert eur_effects["total_effect"] == pytest.approx(0.505)

    calculation_id = response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1
    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()
    assert "ITD_currency_attribution_effects.csv" in lineage_data["artifacts"]


@pytest.mark.parametrize(
    "error_class, expected_status",
    [
        (InvalidEngineInputError, 400),
        (EngineCalculationError, 500),
        (ValueError, 400),
        (NotImplementedError, 400),
        (Exception, 500),
    ],
)
def test_attribution_endpoint_error_handling(client, mocker, error_class, expected_status):
    """Tests that the attribution endpoint correctly handles engine exceptions."""
    mocker.patch("app.services.attribution_service.run_attribution_calculations", side_effect=error_class("Test Error"))
    payload = {
        "portfolio_id": "ERROR",
        "mode": "by_group",
        "group_by": ["sector"],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_attribution_endpoint_returns_400_when_no_resolved_periods(client, mocker):
    """Tests explicit 400 path when period resolution yields no valid periods."""
    mocker.patch("app.services.attribution_service.resolve_periods", return_value=[])
    payload = {
        "portfolio_id": "ATTRIB_NO_PERIODS",
        "mode": "by_group",
        "group_by": ["sector"],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "No valid periods could be resolved."


def test_attribution_endpoint_skips_empty_period_slice(client, mocker):
    """Tests empty-slice branch where a resolved period has no matching effect rows."""
    mocker.patch(
        "app.services.attribution_service.resolve_periods",
        return_value=[
            ResolvedPeriod(name="ITD", start_date="2025-01-01", end_date="2025-01-31"),
            ResolvedPeriod(name="MTD", start_date="2025-02-01", end_date="2025-02-28"),
        ],
    )
    payload = {
        "portfolio_id": "ATTRIB_EMPTY_SLICE",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [
            {"period": "ITD", "frequencies": ["monthly"]},
            {"period": "MTD", "frequencies": ["monthly"]},
        ],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.02, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    results = response.json()["results_by_period"]
    assert "ITD" in results
    assert "MTD" not in results


def test_attribution_async_result_retrieval(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    payload = {
        "portfolio_id": "ATTRIB_ASYNC_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }

    try:
        accepted = client.post("/performance/attribution", json=payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        pending = client.get(f"/performance/attribution/results/{calculation_id}")
        assert pending.status_code == 202

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/attribution/results/{calculation_id}")
        assert complete.status_code == 200
        assert complete.json()["calculation_id"] == calculation_id
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def test_attribution_supports_stateful_input_mode(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
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

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "1000",
                        "ending_market_value_portfolio_currency": "1010",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "1010",
                        "ending_market_value_portfolio_currency": "1020.1",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_benchmark_market_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_1",
                        "points": [
                            {"series_date": "2025-01-01", "component_weight": "1.0", "index_return": "0.01"},
                            {"series_date": "2025-01-02", "component_weight": "1.0", "index_return": "0.01"},
                        ],
                    }
                ]
            },
        )

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_market_series",
        _mock_get_benchmark_market_series,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "ATTRIB_STATEFUL"
    assert body["input_mode"] == "stateful"
    assert "ITD" in body["results_by_period"]


def test_attribution_stateful_offloads_on_resolved_input_count(client, monkeypatch):
    original_window_threshold = settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = 30
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 2

    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
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

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "600",
                        "ending_market_value_portfolio_currency": "606",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "606",
                        "ending_market_value_portfolio_currency": "612.06",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "400",
                        "ending_market_value_portfolio_currency": "404",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "404",
                        "ending_market_value_portfolio_currency": "408.04",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_benchmark_market_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_1",
                        "points": [
                            {"series_date": "2025-01-01", "component_weight": "0.5", "index_return": "0.01"},
                            {"series_date": "2025-01-02", "component_weight": "0.5", "index_return": "0.01"},
                        ],
                    },
                    {
                        "index_id": "IDX_2",
                        "points": [
                            {"series_date": "2025-01-01", "component_weight": "0.5", "index_return": "0.015"},
                            {"series_date": "2025-01-02", "component_weight": "0.5", "index_return": "0.015"},
                        ],
                    },
                ]
            },
        )

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {"index_id": "IDX_1", "classification_labels": {"sector": "Technology"}},
                    {"index_id": "IDX_2", "classification_labels": {"sector": "Healthcare"}},
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_market_series",
        _mock_get_benchmark_market_series,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_ASYNC",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    try:
        accepted = client.post("/performance/attribution", json=payload)

        assert accepted.status_code == 202
        calculation_id = UUID(accepted.json()["calculation_id"])
        execution = execution_registry.get_execution(calculation_id)
        assert execution is not None
        assert execution.requested_window["input_count"] == 4
        assert execution.requested_window["input_mode"] == "stateful"
        job = compute_job_store.get_job(calculation_id)
        assert job is not None
        assert "stateful_input" not in job.request_payload
        assert "benchmark_groups_data" in job.request_payload

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/attribution/results/{calculation_id}")
        assert complete.status_code == 200
        assert complete.json()["input_mode"] == "stateful"
    finally:
        settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_attribution_stateful_promoted_async_replays_identical_retry(client, monkeypatch):
    original_window_threshold = settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = 30
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 2

    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "600",
                        "ending_market_value_portfolio_currency": "606",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "606",
                        "ending_market_value_portfolio_currency": "612.06",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "400",
                        "ending_market_value_portfolio_currency": "404",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "404",
                        "ending_market_value_portfolio_currency": "408.04",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_benchmark_market_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_1",
                        "points": [
                            {"series_date": "2025-01-01", "component_weight": "0.5", "index_return": "0.01"},
                            {"series_date": "2025-01-02", "component_weight": "0.5", "index_return": "0.01"},
                        ],
                    },
                    {
                        "index_id": "IDX_2",
                        "points": [
                            {"series_date": "2025-01-01", "component_weight": "0.5", "index_return": "0.015"},
                            {"series_date": "2025-01-02", "component_weight": "0.5", "index_return": "0.015"},
                        ],
                    },
                ]
            },
        )

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {"index_id": "IDX_1", "classification_labels": {"sector": "Technology"}},
                    {"index_id": "IDX_2", "classification_labels": {"sector": "Healthcare"}},
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_market_series",
        _mock_get_benchmark_market_series,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "ATTRIB_STATEFUL_ASYNC_REPLAY",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    try:
        first = client.post("/performance/attribution", json=payload)
        second = client.post("/performance/attribution", json=payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["calculation_id"] == payload["calculation_id"]
        assert second.json()["calculation_id"] == payload["calculation_id"]
    finally:
        settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_attribution_stateful_currency_mode_both_rejected(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "1000",
                        "ending_market_value_portfolio_currency": "1010",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    }
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_benchmark_market_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_1",
                        "points": [
                            {"series_date": "2025-01-01", "component_weight": "1.0", "index_return": "0.01"},
                        ],
                    }
                ]
            },
        )

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_market_series",
        _mock_get_benchmark_market_series,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 422
    assert "currency_mode=BASE_ONLY only" in response.json()["detail"]


def test_attribution_stateful_hashes_follow_resolved_inputs(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
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

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "1000",
                        "ending_market_value_portfolio_currency": "1010",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "1010",
                        "ending_market_value_portfolio_currency": "1020.1",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_benchmark_market_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_1",
                        "points": [
                            {"series_date": "2025-01-01", "component_weight": "1.0", "index_return": "0.01"},
                            {"series_date": "2025-01-02", "component_weight": "1.0", "index_return": "0.01"},
                        ],
                    }
                ]
            },
        )

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_market_series",
        _mock_get_benchmark_market_series,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_HASH",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    expected_request = AttributionRequest.model_validate(
        {
            "calculation_id": body["calculation_id"],
            "portfolio_id": "ATTRIB_STATEFUL_HASH",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_instrument",
            "frequency": "daily",
            "group_by": ["sector"],
            "linking": "none",
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"day": 1, "perf_date": "2025-01-01", "begin_mv": "1000", "end_mv": "1010"},
                    {"day": 2, "perf_date": "2025-01-02", "begin_mv": "1010", "end_mv": "1020.1"},
                ],
            },
            "instruments_data": [
                {
                    "instrument_id": "POS_1",
                    "meta": {"security_id": "SEC_1", "sector": "Technology"},
                    "valuation_points": [
                        {
                            "day": 0,
                            "perf_date": "2025-01-01",
                            "begin_mv": "1000",
                            "end_mv": "1010",
                            "bod_cf": "0",
                            "eod_cf": "0",
                        },
                        {
                            "day": 0,
                            "perf_date": "2025-01-02",
                            "begin_mv": "1010",
                            "end_mv": "1020.1",
                            "bod_cf": "0",
                            "eod_cf": "0",
                        },
                    ],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "Technology"},
                    "observations": [
                        {"date": "2025-01-01", "weight_bop": "1.0", "return_base": "0.01"},
                        {"date": "2025-01-02", "weight_bop": "1.0", "return_base": "0.01"},
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


def test_attribution_async_result_not_found_and_failed(client, mocker):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    original_attempts = settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = 1
    payload = {
        "portfolio_id": "ATTRIB_ASYNC_FAIL_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    mocker.patch("app.workers.compute_executor_worker.calculate_attribution", side_effect=RuntimeError("explode"))

    try:
        missing = client.get("/performance/attribution/results/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404

        accepted = client.post("/performance/attribution", json=payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        assert drain_compute_queue() == 1

        failed = client.get(f"/performance/attribution/results/{calculation_id}")
        assert failed.status_code == 409
        assert failed.json()["detail"] == "explode"
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold
        settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = original_attempts


def test_attribution_async_duplicate_submission_replays_same_request(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    calculation_id = str(uuid4())
    payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "ATTRIB_ASYNC_REPLAY_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }

    try:
        first = client.post("/performance/attribution", json=payload)
        second = client.post("/performance/attribution", json=payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["calculation_id"] == calculation_id
        assert second.json()["calculation_id"] == calculation_id
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def test_attribution_async_duplicate_submission_conflicts_on_payload_drift(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    calculation_id = str(uuid4())
    first_payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "ATTRIB_ASYNC_CONFLICT_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    second_payload = {**first_payload, "group_by": ["currency"]}

    try:
        first = client.post("/performance/attribution", json=first_payload)
        second = client.post("/performance/attribution", json=second_payload)

        assert first.status_code == 202
        assert second.status_code == 409
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold
