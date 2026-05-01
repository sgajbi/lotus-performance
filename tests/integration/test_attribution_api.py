import asyncio
import os
import shutil
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest
from app.models.benchmark_requests import BenchmarkComponentObservation
from app.observability_contracts import PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS
from app.services.async_result_store import async_result_store
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from core.periods import ResolvedPeriod
from core.repro import generate_canonical_hash
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from main import app
from tests.conftest import drain_compute_queue, drain_lineage_queue

settings = get_settings()
_EXPECTED_SUPPORTABILITY_METRIC_LABELS = list(PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS)


def _stateful_benchmark_input(*observations: BenchmarkComponentObservation) -> StatefulBenchmarkNormalizedInput:
    component_ids = {observation.component_id for observation in observations}
    return StatefulBenchmarkNormalizedInput(
        benchmark_currency="USD",
        component_observations=list(observations),
        benchmark_return_points=[],
        source_details={
            "benchmark_components": len(component_ids),
            "component_observations": len(observations),
            "benchmark_chunk_count": 1,
            "benchmark_page_count": 1,
            "fx_pair_count": 0,
            "fx_chunk_count": 0,
            "fx_page_count": 0,
        },
    )


def _patch_stateful_attribution_benchmark_input(monkeypatch, *observations: BenchmarkComponentObservation) -> None:
    async def _mock_build_stateful_benchmark_input(**kwargs):  # noqa: ARG001
        return _stateful_benchmark_input(*observations)

    monkeypatch.setattr(
        "app.services.stateful_attribution_input_service.build_stateful_benchmark_input",
        _mock_build_stateful_benchmark_input,
    )


def _assert_authoritative_level_totals(level: dict) -> None:
    totals = level["totals"]
    assert level["allocation_total_pct"] == pytest.approx(totals["allocation"])
    assert level["selection_total_pct"] == pytest.approx(totals["selection"])
    assert level["interaction_total_pct"] == pytest.approx(totals["interaction"])
    assert level["total_effect_pct"] == pytest.approx(totals["total_effect"])
    assert level["allocation_total_pct"] == pytest.approx(sum(group["allocation"] for group in level["groups"]))
    assert level["selection_total_pct"] == pytest.approx(sum(group["selection"] for group in level["groups"]))
    assert level["interaction_total_pct"] == pytest.approx(sum(group["interaction"] for group in level["groups"]))
    assert level["total_effect_pct"] == pytest.approx(sum(group["total_effect"] for group in level["groups"]))
    assert level["total_effect_pct"] == pytest.approx(
        level["allocation_total_pct"] + level["selection_total_pct"] + level["interaction_total_pct"]
    )


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
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1018.5}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"sector": "Health"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 406.5}],
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
    body = response.json()
    assert body["calculation_supportability"] == {
        "state": "ready",
        "reason": "calculation_complete",
        "freshness_bucket": "current",
        "input_row_count": 5,
        "resolved_period_count": 1,
        "benchmark_row_count": 2,
        "metric_labels": _EXPECTED_SUPPORTABILITY_METRIC_LABELS,
    }
    response_data = body["results_by_period"]["ITD"]
    assert response_data["reconciliation"]["total_active_return"] == pytest.approx(0.1)
    level = response_data["levels"][0]
    _assert_authoritative_level_totals(level)
    assert response_data["reconciliation"]["sum_of_effects"] == pytest.approx(level["total_effect_pct"])
    tech_group = next(g for g in level["groups"] if g["key"]["sector"] == "Tech")
    assert tech_group["portfolio_weight_avg"] == pytest.approx(60.0)
    assert tech_group["benchmark_weight_avg"] == pytest.approx(50.0)
    assert tech_group["portfolio_return"] == pytest.approx(2.0)
    assert tech_group["benchmark_return"] == pytest.approx(1.5)
    assert tech_group["selection"] == pytest.approx(0.25)
    assert tech_group["total_effect"] == pytest.approx(
        tech_group["allocation"] + tech_group["selection"] + tech_group["interaction"]
    )


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
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"assetClass": "Equity", "sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"assetClass": "Equity", "sector": "Health"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 303}],
            },
            {
                "instrument_id": "UST",
                "meta": {"assetClass": "Bond", "sector": "Government"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 309}],
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
    _assert_authoritative_level_totals(level_ac)
    _assert_authoritative_level_totals(level_sector)
    equity_ac_effects = next(g for g in level_ac["groups"] if g["key"]["assetClass"] == "Equity")
    tech_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Tech")
    health_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Health")
    assert equity_ac_effects["allocation"] == pytest.approx(
        tech_sector_effects["allocation"] + health_sector_effects["allocation"]
    )
    assert equity_ac_effects["selection"] == pytest.approx(
        tech_sector_effects["selection"] + health_sector_effects["selection"]
    )


def test_attribution_endpoint_supports_explicit_period_windows(client):
    payload = {
        "portfolio_id": "ATTRIB_EXPLICIT_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-02",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [
                    {"date": "2025-01-01", "return_base": 0.10, "weight_bop": 1.0},
                    {"date": "2025-01-02", "return_base": 0.01, "weight_bop": 1.0},
                    {"date": "2025-01-03", "return_base": 0.01, "weight_bop": 1.0},
                ],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [
                    {"date": "2025-01-01", "return_base": 0.10, "weight_bop": 1.0},
                    {"date": "2025-01-02", "return_base": 0.01, "weight_bop": 1.0},
                    {"date": "2025-01-03", "return_base": 0.01, "weight_bop": 1.0},
                ],
            }
        ],
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    assert set(response.json()["results_by_period"]) == {"EXPLICIT"}


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
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 103.02}],
        },
        "instruments_data": [
            {
                "instrument_id": "EUR_ASSET",
                "meta": {"currency": "EUR"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0}
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
                        "ending_market_value": "1018.5",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1018.5",
                        "ending_market_value": "1028.67",
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
                        "ending_market_value_portfolio_currency": "612",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "400",
                        "ending_market_value_portfolio_currency": "406.5",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "612",
                        "ending_market_value_portfolio_currency": "618.12",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "406.5",
                        "ending_market_value_portfolio_currency": "410.55",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    },
                    {
                        "index_id": "IDX_2",
                        "classification_labels": {"sector": "Healthcare"},
                    },
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
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.015,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.02,
        ),
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
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "ATTRIB_STATEFUL"
    assert body["input_mode"] == "stateful"
    assert body["benchmark_context"] == {
        "benchmark_id": "BMK_1",
        "return_source": "calculated",
    }
    itd = body["results_by_period"]["ITD"]
    assert itd["reconciliation"]["total_active_return"] == pytest.approx(1.0985232695139984)
    assert itd["reconciliation"]["sum_of_effects"] == pytest.approx(1.0985232695139984)
    level = itd["levels"][0]
    tech_group = next(group for group in level["groups"] if group["key"]["sector"] == "technology")
    assert tech_group["selection"] == pytest.approx(0.25)


def test_attribution_stateful_converts_non_base_cash_flows_using_explicit_fx_metadata(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "132",
                        "ending_market_value": "145.2",
                        "cash_flows": [{"amount": "13.2", "timing": "bod", "cash_flow_type": "external_flow"}],
                    }
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_EUR_1",
                        "security_id": "SEC_EUR_1",
                        "valuation_date": "2025-01-01",
                        "position_currency": "EUR",
                        "cash_flow_currency": "EUR",
                        "position_to_portfolio_fx_rate": "1.20",
                        "portfolio_to_reporting_fx_rate": "1.10",
                        "beginning_market_value_reporting_currency": "132",
                        "ending_market_value_reporting_currency": "145.2",
                        "beginning_market_value_portfolio_currency": "120",
                        "ending_market_value_portfolio_currency": "132",
                        "beginning_market_value_position_currency": "100",
                        "ending_market_value_position_currency": "110",
                        "cash_flows": [{"amount": "10", "timing": "bod", "cash_flow_type": "external_flow"}],
                        "dimensions": {"sector": "Technology"},
                    }
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

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
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.0,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_FX_CF",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    itd = response.json()["results_by_period"]["ITD"]
    assert itd["reconciliation"]["total_active_return"] == pytest.approx(0.0)
    assert itd["reconciliation"]["sum_of_effects"] == pytest.approx(0.0)


def test_attribution_stateful_rejects_acquisition_day_rows_without_cash_flow_semantics(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1018.5",
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
                        "beginning_market_value_portfolio_currency": "0",
                        "ending_market_value_portfolio_currency": "600",
                        "cash_flows": [],
                        "dimensions": {"asset_class": "Equity"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "600",
                        "ending_market_value_portfolio_currency": "606",
                        "cash_flows": [],
                        "dimensions": {"asset_class": "Equity"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {"index_id": "IDX_1", "classification_labels": {"asset_class": "Equity"}},
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
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=1.0,
            component_return=0.01,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_GAP",
        "mode": "by_instrument",
        "group_by": ["asset_class"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 422
    assert "cannot safely compute acquisition-day position returns" in response.json()["detail"]


def test_attribution_stateful_rejects_portfolio_position_alignment_mismatch(client, monkeypatch):
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
                        "beginning_market_value_portfolio_currency": "900",
                        "ending_market_value_portfolio_currency": "909",
                        "cash_flows": [],
                        "dimensions": {"asset_class": "Equity"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (200, {"records": [{"index_id": "IDX_1", "classification_labels": {"asset_class": "Equity"}}]})

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
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.01,
        ),
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_MISMATCH",
        "mode": "by_instrument",
        "group_by": ["asset_class"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 503
    assert "portfolio timeseries does not align with summed position timeseries" in response.json()["detail"]


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
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.015,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.015,
        ),
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
        "stateful_input": {},
    }

    try:
        accepted = client.post("/performance/attribution", json=payload)

        assert accepted.status_code == 202
        calculation_id = UUID(accepted.json()["calculation_id"])
        execution = execution_registry.get_execution(calculation_id)
        assert execution is not None
        assert execution.requested_window["input_count"] == 4
        assert execution.requested_window["input_mode"] == "stateful"
        assert execution.requested_window["benchmark_id"] == "BMK_1"
        assert execution.requested_window["benchmark_return_source"] == "calculated"
        job = compute_job_store.get_job(calculation_id)
        assert job is not None
        assert "stateful_input" not in job.request_payload["resolved_request"]
        assert "benchmark_groups_data" in job.request_payload["resolved_request"]
        assert job.request_payload["resolved_benchmark_id"] == "BMK_1"
        assert job.request_payload["resolved_benchmark_return_source"] == "calculated"

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/attribution/results/{calculation_id}")
        assert complete.status_code == 200
        body = complete.json()
        assert body["input_mode"] == "stateful"
        assert body["benchmark_context"] == {
            "benchmark_id": "BMK_1",
            "return_source": "calculated",
        }
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
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.015,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.015,
        ),
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
        "stateful_input": {},
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


def test_attribution_stateful_currency_mode_both_supports_mixed_currency_decomposition(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "200",
                        "ending_market_value": "205.111",
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
                        "position_id": "POS_EUR",
                        "security_id": "SEC_EUR",
                        "position_currency": "EUR",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_reporting_currency": "110",
                        "ending_market_value_reporting_currency": "113.311",
                        "beginning_market_value_position_currency": "100",
                        "ending_market_value_position_currency": "101",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology", "country": "DE"},
                    },
                    {
                        "position_id": "POS_USD",
                        "security_id": "SEC_USD",
                        "position_currency": "USD",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_reporting_currency": "90",
                        "ending_market_value_reporting_currency": "91.8",
                        "beginning_market_value_position_currency": "90",
                        "ending_market_value_position_currency": "91.8",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology", "country": "US"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    },
                    {
                        "index_id": "IDX_2",
                        "classification_labels": {"sector": "Technology"},
                    },
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
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            component_currency="EUR",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.0302,
            component_return_local=0.02,
            component_return_fx=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            component_currency="USD",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.02,
            component_return_local=0.02,
            component_return_fx=0.0,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL",
        "mode": "by_instrument",
        "group_by": ["currency"],
        "linking": "none",
        "frequency": "daily",
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.10},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.111},
            ]
        },
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["input_mode"] == "stateful"
    currency_results = body["results_by_period"]["ITD"]["currency_attribution"]
    assert currency_results is not None
    by_currency = {entry["currency"]: entry for entry in currency_results}
    assert by_currency["eur"]["weight_portfolio_avg"] == pytest.approx(55.0)
    assert by_currency["usd"]["weight_portfolio_avg"] == pytest.approx(45.0)


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
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=1.0,
            component_return=0.01,
        ),
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
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    resolved = asyncio.run(
        resolve_attribution_request(
            AttributionAnalyticsRequest.model_validate(
                {
                    **payload,
                    "calculation_id": body["calculation_id"],
                }
            ),
            settings=settings,
        )
    )
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash(
        resolved.attribution_request, settings.APP_VERSION
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
