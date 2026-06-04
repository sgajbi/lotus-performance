import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.benchmark_requests import BenchmarkComponentObservation
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from main import app
from tests.conftest import drain_compute_queue, drain_lineage_queue

settings = get_settings()


def _patch_stateful_attribution_benchmark_input(monkeypatch, *observations: BenchmarkComponentObservation) -> None:
    async def _mock_build_stateful_benchmark_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=list(observations),
            benchmark_return_points=[],
            source_details={
                "benchmark_components": len({observation.component_id for observation in observations}),
                "component_observations": len(observations),
                "benchmark_chunk_count": 1,
                "benchmark_page_count": 1,
                "fx_pair_count": 0,
                "fx_chunk_count": 0,
                "fx_page_count": 0,
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_attribution_input_service.build_stateful_benchmark_input",
        _mock_build_stateful_benchmark_input,
    )


def _patch_shared_stateful_benchmark_sources(monkeypatch) -> None:
    async def _mock_get_portfolio_reference(self, **kwargs):  # noqa: ARG001
        return 200, {"portfolio_open_date": "2026-02-20"}

    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-20",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                    {
                        "valuation_date": "2026-02-25",
                        "beginning_market_value": "1020.1",
                        "ending_market_value": "1030.301",
                    },
                ],
            },
        )

    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-20",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                    {
                        "valuation_date": "2026-02-25",
                        "beginning_market_value": "1020.1",
                        "ending_market_value": "1030.301",
                    },
                ],
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_SHARED_1"}

    async def _mock_get_benchmark_composition_window(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "benchmark_id": "BMK_SHARED_1",
                "benchmark_currency": "USD",
                "segments": [
                    {
                        "index_id": "IDX_SHARED_1",
                        "composition_weight": "1.0",
                        "composition_effective_from": "2026-02-01",
                        "composition_effective_to": "2026-02-28",
                    }
                ],
            },
        )

    async def _mock_get_index_price_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-02-22", "index_price": "100", "series_currency": "USD"},
                    {"series_date": "2026-02-23", "index_price": "100", "series_currency": "USD"},
                    {"series_date": "2026-02-24", "index_price": "101", "series_currency": "USD"},
                    {"series_date": "2026-02-25", "index_price": "102.01", "series_currency": "USD"},
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )

    async def _mock_get_fx_rates(self, **kwargs):  # noqa: ARG001
        return 200, {"points": [], "retrieval_metadata": {"chunk_count": 0, "page_count": 0}}

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_reference",
        _mock_get_portfolio_reference,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_composition_window",
        _mock_get_benchmark_composition_window,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_benchmark_composition_window",
        _mock_get_benchmark_composition_window,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_price_series",
        _mock_get_index_price_series,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_index_price_series",
        _mock_get_index_price_series,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_fx_rates",
        _mock_get_fx_rates,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_fx_rates",
        _mock_get_fx_rates,
    )


def _link_return_points(points: list[dict[str, str]]) -> float:
    running = Decimal("1")
    for point in points:
        running *= Decimal("1") + Decimal(point["return_value"])
    return float(running - Decimal("1"))


def test_e2e_platform_readiness_and_capabilities_contract() -> None:
    os.makedirs(settings.LINEAGE_STORAGE_PATH, exist_ok=True)

    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/health/ready")
        capabilities = client.get("/integration/capabilities?consumer_system=lotus-gateway&tenant_id=default")

    assert health.status_code == 200
    assert ready.status_code == 200
    assert capabilities.status_code == 200

    body = capabilities.json()
    assert body["contract_version"] == "v1"
    assert body["source_service"] == "lotus-performance"
    assert "stateful" in body["supported_input_modes"]
    assert "stateless" in body["supported_input_modes"]
    surfaces = {item["key"]: item for item in body["analytics_surfaces"]}
    assert surfaces["workspace_summary"]["path"] == "/performance/workspace-summary"
    assert surfaces["workspace_summary"]["poll_path_template"] == "/performance/executions/{calculation_id}"
    assert (
        surfaces["workspace_summary"]["result_path_template"]
        == "/performance/workspace-summary/results/{calculation_id}"
    )
    assert surfaces["workspace_summary"]["stateful_restrictions"] == []
    workspace_options = {item["key"]: item for item in surfaces["workspace_summary"]["options"]}
    assert workspace_options["benchmark_mode"]["supported_values"] == ["user_input_stateless", "linked_stateful"]
    assert surfaces["contribution"]["supports_async"] is True
    assert surfaces["attribution"]["stateful_restrictions"] == [
        "mode=by_instrument only",
        "group_by limited to asset_class, sector, country, currency",
        "currency_mode=BOTH requires report_ccy and fx.rates for mixed-currency positions",
    ]


def test_e2e_performance_twr_and_mwr_workflow() -> None:
    twr_payload = {
        "portfolio_id": "E2E_WORKFLOW_001",
        "performance_start_date": "2025-01-01",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "metric_basis": "NET",
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
            {"perf_date": "2025-01-03", "begin_mv": 1020.1, "end_mv": 1030.301},
        ],
    }
    mwr_payload = {
        "portfolio_id": "E2E_WORKFLOW_001",
        "begin_mv": 1000.0,
        "end_mv": 1030.301,
        "cash_flows": [],
        "as_of": "2025-01-03",
    }

    with TestClient(app) as client:
        twr_response = client.post("/performance/twr", json=twr_payload)
        mwr_response = client.post("/performance/mwr", json=mwr_payload)

    assert twr_response.status_code == 200
    assert mwr_response.status_code == 200

    twr_body = twr_response.json()
    assert "ITD" in twr_body["results_by_period"]
    assert twr_body["results_by_period"]["ITD"]["portfolio"]["summary"]["period_return"]["base"] > 0

    mwr_body = mwr_response.json()
    assert mwr_body["portfolio_id"] == "E2E_WORKFLOW_001"


def test_e2e_stateful_analytics_workflow(monkeypatch) -> None:
    async def _mock_get_portfolio_reference(self, **kwargs):  # noqa: ARG001
        return 200, {"portfolio_open_date": "2024-12-31"}

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
                        "cash_flows": [],
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1020.1",
                        "cash_flows": [],
                    },
                ],
            },
        )

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
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_reference",
        _mock_get_portfolio_reference,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
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
    twr_payload = {
        "portfolio_id": "E2E_STATEFUL_001",
        "report_end_date": "2025-01-02",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }
    mwr_payload = {
        "portfolio_id": "E2E_STATEFUL_001",
        "as_of": "2025-01-02",
        "mwr_method": "DIETZ",
        "input_mode": "stateful",
        "stateful_input": {
            "window_start_date": "2025-01-01",
        },
    }
    contribution_payload = {
        "portfolio_id": "E2E_STATEFUL_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }
    attribution_payload = {
        "portfolio_id": "E2E_STATEFUL_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "mode": "by_instrument",
        "group_by": ["sector"],
        "frequency": "daily",
        "currency_mode": "BASE_ONLY",
        "linking": "none",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    with TestClient(app) as client:
        twr_response = client.post("/performance/twr", json=twr_payload)
        mwr_response = client.post("/performance/mwr", json=mwr_payload)
        contribution_response = client.post("/performance/contribution", json=contribution_payload)
        attribution_response = client.post("/performance/attribution", json=attribution_payload)

        twr_execution = client.get(f"/performance/executions/{twr_response.json()['calculation_id']}")
        mwr_execution = client.get(f"/performance/executions/{mwr_response.json()['calculation_id']}")
        contribution_execution = client.get(f"/performance/executions/{contribution_response.json()['calculation_id']}")
        attribution_execution = client.get(f"/performance/executions/{attribution_response.json()['calculation_id']}")

    assert twr_response.status_code == 200
    assert mwr_response.status_code == 200
    assert contribution_response.status_code == 200
    assert attribution_response.status_code == 200

    assert twr_response.json()["input_mode"] == "stateful"
    assert mwr_response.json()["input_mode"] == "stateful"
    assert contribution_response.json()["input_mode"] == "stateful"
    assert attribution_response.json()["input_mode"] == "stateful"
    assert attribution_response.json()["benchmark_context"] == {
        "benchmark_id": "BMK_1",
        "return_source": "calculated",
    }

    for execution in (
        twr_execution,
        mwr_execution,
        contribution_execution,
        attribution_execution,
    ):
        assert execution.status_code == 200
        execution_body = execution.json()
        stage_names = {stage["stage_name"] for stage in execution_body["stages"]}
        assert "retrieval" in stage_names
        assert "normalization" in stage_names

    assert "YTD" in twr_response.json()["results_by_period"]
    assert mwr_response.json()["method"] == "DIETZ"
    assert "ITD" in contribution_response.json()["results_by_period"]
    assert "ITD" in attribution_response.json()["results_by_period"]


def test_e2e_shared_stateful_benchmark_engine_stays_consistent_across_surfaces(monkeypatch) -> None:
    _patch_shared_stateful_benchmark_sources(monkeypatch)

    benchmark_payload = {
        "benchmark_id": "BMK_SHARED_1",
        "benchmark_start_date": "2026-02-23",
        "report_end_date": "2026-02-25",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "stateful_input": {},
    }
    twr_payload = {
        "portfolio_id": "E2E_BENCHMARK_SHARED",
        "report_end_date": "2026-02-25",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "include_benchmark": True,
        "stateful_input": {},
    }
    returns_series_payload = {
        "portfolio_id": "E2E_BENCHMARK_SHARED",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    with TestClient(app) as client:
        benchmark_response = client.post("/performance/benchmark", json=benchmark_payload)
        twr_response = client.post("/performance/twr", json=twr_payload)
        returns_series_response = client.post("/integration/returns/series", json=returns_series_payload)

    assert benchmark_response.status_code == 200
    assert twr_response.status_code == 200
    assert returns_series_response.status_code == 200

    benchmark_body = benchmark_response.json()
    twr_body = twr_response.json()
    returns_series_body = returns_series_response.json()

    benchmark_return = benchmark_body["results_by_period"]["YTD"]["benchmark"]["summary"]["period_return"]["base"]
    twr_benchmark_return = twr_body["results_by_period"]["YTD"]["benchmark"]["summary"]["period_return"]["base"]
    linked_returns_series_benchmark_return = _link_return_points(returns_series_body["series"]["benchmark_returns"])
    benchmark_cumulative_return = benchmark_body["results_by_period"]["YTD"]["benchmark"]["breakdowns"]["daily"][-1][
        "cumulative_return"
    ]["base"]
    returns_series_cumulative_benchmark_return = Decimal(
        returns_series_body["series"]["cumulative_benchmark_returns"][-1]["return_value"]
    )
    twr_cumulative_relative_return = Decimal(
        str(
            twr_body["results_by_period"]["YTD"]["relative_performance"]["breakdowns"]["daily"][-1][
                "cumulative_return"
            ]["base"]
        )
    ) / Decimal("100")
    returns_series_cumulative_active_return = Decimal(
        returns_series_body["series"]["cumulative_active_returns"][-1]["return_value"]
    )

    assert benchmark_return == pytest.approx(2.01)
    assert twr_benchmark_return == pytest.approx(benchmark_return)
    assert linked_returns_series_benchmark_return == pytest.approx(benchmark_return / 100)
    assert float(returns_series_cumulative_benchmark_return) == pytest.approx(benchmark_cumulative_return / 100)
    assert float(returns_series_cumulative_active_return) == pytest.approx(float(twr_cumulative_relative_return))
    assert [point["return_value"] for point in returns_series_body["series"]["active_returns"]] == [
        "0.010000000000",
        "0E-12",
        "0E-12",
    ]


def test_e2e_stateful_twr_returns_series_and_contribution_stay_consistent(monkeypatch) -> None:
    from types import SimpleNamespace

    _patch_shared_stateful_benchmark_sources(monkeypatch)

    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": "2026-02-23",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                    {
                        "valuation_date": "2026-02-24",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1020.1",
                    },
                    {
                        "valuation_date": "2026-02-25",
                        "beginning_market_value": "1020.1",
                        "ending_market_value": "1030.301",
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_SHARED_1",
                    "security_id": "SEC_SHARED_1",
                    "valuation_date": "2026-02-23",
                    "position_currency": "USD",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                    "beginning_market_value_position_currency": "1000",
                    "ending_market_value_position_currency": "1010",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_SHARED_1",
                    "security_id": "SEC_SHARED_1",
                    "valuation_date": "2026-02-24",
                    "position_currency": "USD",
                    "beginning_market_value_portfolio_currency": "1010",
                    "ending_market_value_portfolio_currency": "1020.1",
                    "beginning_market_value_position_currency": "1010",
                    "ending_market_value_position_currency": "1020.1",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_SHARED_1",
                    "security_id": "SEC_SHARED_1",
                    "valuation_date": "2026-02-25",
                    "position_currency": "USD",
                    "beginning_market_value_portfolio_currency": "1020.1",
                    "ending_market_value_portfolio_currency": "1030.301",
                    "beginning_market_value_position_currency": "1020.1",
                    "ending_market_value_position_currency": "1030.301",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    twr_payload = {
        "portfolio_id": "E2E_SHARED_STORY",
        "report_end_date": "2026-02-25",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "include_benchmark": True,
        "stateful_input": {},
    }
    returns_series_payload = {
        "portfolio_id": "E2E_SHARED_STORY",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
        "input_mode": "stateful",
        "stateful_input": {},
    }
    contribution_payload = {
        "portfolio_id": "E2E_SHARED_STORY",
        "report_start_date": "2026-02-23",
        "report_end_date": "2026-02-25",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "emit": {"timeseries": True, "by_position_timeseries": True},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    with TestClient(app) as client:
        twr_response = client.post("/performance/twr", json=twr_payload)
        returns_series_response = client.post("/integration/returns/series", json=returns_series_payload)
        contribution_response = client.post("/performance/contribution", json=contribution_payload)

    assert twr_response.status_code == 200
    assert returns_series_response.status_code == 200
    assert contribution_response.status_code == 200

    twr_body = twr_response.json()
    returns_series_body = returns_series_response.json()
    contribution_body = contribution_response.json()

    twr_ytd = twr_body["results_by_period"]["YTD"]
    contribution_itd = contribution_body["results_by_period"]["ITD"]
    twr_portfolio_return = Decimal(str(twr_ytd["portfolio"]["summary"]["period_return"]["base"]))
    twr_benchmark_return = Decimal(str(twr_ytd["benchmark"]["summary"]["period_return"]["base"]))
    twr_relative_return = Decimal(str(twr_ytd["relative_performance"]["summary"]["period_return"]["base"]))
    contribution_total = Decimal(str(contribution_itd["total_contribution"]))
    contribution_total_portfolio_return = Decimal(str(contribution_itd["total_portfolio_return"]))
    returns_series_cumulative_portfolio = Decimal(
        str(returns_series_body["series"]["cumulative_portfolio_returns"][-1]["return_value"])
    ) * Decimal("100")
    returns_series_cumulative_benchmark = Decimal(
        str(returns_series_body["series"]["cumulative_benchmark_returns"][-1]["return_value"])
    ) * Decimal("100")
    returns_series_cumulative_active = Decimal(
        str(returns_series_body["series"]["cumulative_active_returns"][-1]["return_value"])
    ) * Decimal("100")

    assert contribution_body["input_mode"] == "stateful"
    assert returns_series_body["benchmark_context"] == {
        "benchmark_id": "BMK_SHARED_1",
        "return_source": "calculated",
    }

    assert float(contribution_total) == pytest.approx(float(twr_portfolio_return))
    assert float(contribution_total_portfolio_return) == pytest.approx(float(twr_portfolio_return))
    assert float(returns_series_cumulative_portfolio) == pytest.approx(float(twr_portfolio_return))
    assert float(returns_series_cumulative_benchmark) == pytest.approx(float(twr_benchmark_return))
    assert float(returns_series_cumulative_active) == pytest.approx(float(twr_relative_return))

    assert contribution_itd["position_contributions"][0]["total_contribution"] == pytest.approx(
        float(contribution_total)
    )
    contribution_daily_totals = [point["total_contribution"] for point in contribution_itd["timeseries"]]
    by_position_daily = [point["contribution"] for point in contribution_itd["by_position_timeseries"][0]["series"]]
    assert contribution_daily_totals == pytest.approx(by_position_daily)


def test_e2e_contribution_attribution_and_lineage() -> None:
    contribution_payload = {
        "portfolio_id": "E2E_CONTRIB_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
            }
        ],
        "emit": {"timeseries": True},
    }
    attribution_payload = {
        "portfolio_id": "E2E_ATTRIB_001",
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

    with TestClient(app) as client:
        contribution_response = client.post("/performance/contribution", json=contribution_payload)
        attribution_response = client.post("/performance/attribution", json=attribution_payload)
        assert drain_lineage_queue() >= 2

        contribution_lineage = client.get(f"/performance/lineage/{contribution_response.json()['calculation_id']}")
        attribution_lineage = client.get(f"/performance/lineage/{attribution_response.json()['calculation_id']}")

    assert contribution_response.status_code == 200
    assert attribution_response.status_code == 200
    assert contribution_lineage.status_code == 200
    assert attribution_lineage.status_code == 200


def test_e2e_performance_contribution_and_attribution_tell_the_same_story() -> None:
    twr_payload = {
        "portfolio_id": "E2E_STORY_001",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-01",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1020.0}],
        "include_benchmark": True,
        "benchmark": {
            "benchmark_id": "BMK_STORY_001",
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
    }
    contribution_payload = {
        "portfolio_id": "E2E_STORY_001",
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
    }
    attribution_payload = {
        "portfolio_id": "E2E_STORY_001",
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
    }

    with TestClient(app) as client:
        twr_response = client.post("/performance/twr", json=twr_payload)
        contribution_response = client.post("/performance/contribution", json=contribution_payload)
        attribution_response = client.post("/performance/attribution", json=attribution_payload)

    assert twr_response.status_code == 200
    assert contribution_response.status_code == 200
    assert attribution_response.status_code == 200

    twr_body = twr_response.json()
    contribution_body = contribution_response.json()
    attribution_body = attribution_response.json()

    twr_itd = twr_body["results_by_period"]["YTD"]
    contribution_itd = contribution_body["results_by_period"]["ITD"]
    attribution_itd = attribution_body["results_by_period"]["ITD"]

    portfolio_return = twr_itd["portfolio"]["summary"]["period_return"]["base"]
    benchmark_return = twr_itd["benchmark"]["summary"]["period_return"]["base"]
    relative_return = twr_itd["relative_performance"]["summary"]["period_return"]["base"]
    contribution_total = contribution_itd["total_contribution"]
    attribution_active = attribution_itd["reconciliation"]["total_active_return"]
    attribution_effects = attribution_itd["reconciliation"]["sum_of_effects"]

    assert portfolio_return == pytest.approx(2.0)
    assert benchmark_return == pytest.approx(1.5)
    assert relative_return == pytest.approx(0.5)
    assert contribution_total == pytest.approx(portfolio_return)
    assert attribution_active == pytest.approx(relative_return)
    assert attribution_effects == pytest.approx(attribution_active)

    assert twr_itd["portfolio"]["breakdowns"]["daily"][0]["period_return"]["base"] == pytest.approx(portfolio_return)
    assert twr_itd["benchmark"]["breakdowns"]["daily"][0]["period_return"]["base"] == pytest.approx(benchmark_return)
    assert twr_itd["relative_performance"]["breakdowns"]["daily"][0]["period_return"]["base"] == pytest.approx(
        relative_return
    )
    assert contribution_itd["timeseries"][0]["total_contribution"] == pytest.approx(contribution_total)
    assert contribution_itd["position_contributions"][0]["total_contribution"] == pytest.approx(contribution_total)
    attribution_group = attribution_itd["levels"][0]["groups"][0]
    assert attribution_group["portfolio_weight_avg"] == pytest.approx(100.0)
    assert attribution_group["benchmark_weight_avg"] == pytest.approx(100.0)
    assert attribution_group["portfolio_return"] == pytest.approx(portfolio_return)
    assert attribution_group["benchmark_return"] == pytest.approx(benchmark_return)
    assert attribution_group["total_effect"] == pytest.approx(attribution_active)


def test_e2e_reset_heavy_contribution_and_daily_series_both_tie_to_twr() -> None:
    twr_payload = {
        "portfolio_id": "E2E_RESET_ALIGNMENT_001",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-04",
        "metric_basis": "GROSS",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
            {"perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
            {"perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
            {"perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
        ],
        "reset_policy": {"emit": True},
    }
    contribution_payload = {
        "portfolio_id": "E2E_RESET_ALIGNMENT_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
                {"perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
                {"perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
                {"perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
            ],
        },
        "positions_data": [
            {
                "position_id": "RESET_STORY_POSITION",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
                    {"perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
                    {"perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
                    {"perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
                ],
            }
        ],
        "emit": {"timeseries": True, "by_position_timeseries": True},
    }

    with TestClient(app) as client:
        twr_response = client.post("/performance/twr", json=twr_payload)
        contribution_response = client.post("/performance/contribution", json=contribution_payload)

    assert twr_response.status_code == 200
    assert contribution_response.status_code == 200

    twr_body = twr_response.json()
    contribution_body = contribution_response.json()

    twr_itd = twr_body["results_by_period"]["ITD"]
    contribution_itd = contribution_body["results_by_period"]["ITD"]

    twr_portfolio_return = twr_itd["portfolio"]["summary"]["period_return"]["base"]
    contribution_total = contribution_itd["total_contribution"]
    contribution_total_portfolio_return = contribution_itd["total_portfolio_return"]

    assert twr_portfolio_return == pytest.approx(21.578947, abs=1e-6)
    assert contribution_total == pytest.approx(twr_portfolio_return)
    assert contribution_total_portfolio_return == pytest.approx(twr_portfolio_return)

    reset_reasons_by_date = {event["date"]: event["reason"] for event in twr_itd["reset_events"]}
    assert "NCTRL_1" in reset_reasons_by_date["2025-01-02"]
    assert "NCTRL_4" in reset_reasons_by_date["2025-01-03"]

    assert contribution_body["audit"]["counts"]["portfolio_reset_days"] == 2
    assert contribution_body["audit"]["counts"]["position_reset_days"] == 2
    assert contribution_body["audit"]["counts"]["portfolio_reset_without_position_reset_days"] == 0
    assert contribution_body["audit"]["counts"]["position_reset_without_portfolio_reset_days"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_positions"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_max_bp"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_sum_bp"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_noise_periods"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_warning_periods"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_material_periods"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_cutover_candidate_periods"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_sum_residual_bp"] == 0
    assert contribution_body["audit"]["counts"]["carino_invalid_domain_days"] == 1
    assert contribution_body["audit"]["counts"]["timeseries_total_delta_periods"] == 0
    assert any(
        "Carino smoothing fell back to raw daily contribution arithmetic" in note
        for note in contribution_body["diagnostics"]["notes"]
    )
    assert not any(
        "do not sum to the residual-adjusted period total" in note for note in contribution_body["diagnostics"]["notes"]
    )
    assert not any(
        "grouped-return alignment remains under characterization" in note
        for note in contribution_body["diagnostics"]["notes"]
    )
    contribution_daily_totals = [point["total_contribution"] for point in contribution_itd["timeseries"]]
    by_position_daily = [point["contribution"] for point in contribution_itd["by_position_timeseries"][0]["series"]]
    assert contribution_daily_totals == pytest.approx(by_position_daily)
    assert sum(contribution_daily_totals) == pytest.approx(contribution_total)


def test_e2e_multi_position_reset_heavy_contribution_keeps_tie_out_and_surfaces_weight_shadow_delta() -> None:
    twr_payload = {
        "portfolio_id": "E2E_MULTI_RESET_ALIGNMENT_001",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-04",
        "metric_basis": "GROSS",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
            {"perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
            {"perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
            {"perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
        ],
        "reset_policy": {"emit": True},
    }
    contribution_payload = {
        "portfolio_id": "E2E_MULTI_RESET_ALIGNMENT_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
                {"perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
                {"perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
                {"perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
            ],
        },
        "positions_data": [
            {
                "position_id": "RESET_STORY_A",
                "meta": {"sector": "Technology"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 600.0, "end_mv": 240.0},
                    {"perf_date": "2025-01-02", "begin_mv": 240.0, "end_mv": -20.0},
                    {"perf_date": "2025-01-03", "begin_mv": -20.0, "bod_cf": 800.0, "end_mv": 840.0},
                    {"perf_date": "2025-01-04", "begin_mv": 840.0, "end_mv": 924.0},
                ],
            },
            {
                "position_id": "RESET_STORY_B",
                "meta": {"sector": "Healthcare"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 400.0, "end_mv": 260.0},
                    {"perf_date": "2025-01-02", "begin_mv": 260.0, "end_mv": -30.0},
                    {"perf_date": "2025-01-03", "begin_mv": -30.0, "bod_cf": 200.0, "end_mv": 210.0},
                    {"perf_date": "2025-01-04", "begin_mv": 210.0, "end_mv": 231.0},
                ],
            },
        ],
        "emit": {"timeseries": True, "by_position_timeseries": True},
    }

    with TestClient(app) as client:
        twr_response = client.post("/performance/twr", json=twr_payload)
        contribution_response = client.post("/performance/contribution", json=contribution_payload)

    assert twr_response.status_code == 200
    assert contribution_response.status_code == 200

    twr_itd = twr_response.json()["results_by_period"]["ITD"]
    contribution_body = contribution_response.json()
    contribution_itd = contribution_body["results_by_period"]["ITD"]

    twr_portfolio_return = twr_itd["portfolio"]["summary"]["period_return"]["base"]
    contribution_total = contribution_itd["total_contribution"]

    assert contribution_total == pytest.approx(twr_portfolio_return)
    assert contribution_itd["total_portfolio_return"] == pytest.approx(twr_portfolio_return)
    assert len(contribution_itd["position_contributions"]) == 2
    assert sum(item["total_contribution"] for item in contribution_itd["position_contributions"]) == pytest.approx(
        contribution_total
    )

    contribution_daily_totals = [point["total_contribution"] for point in contribution_itd["timeseries"]]
    flattened_position_daily = [
        first["contribution"] + second["contribution"]
        for first, second in zip(
            contribution_itd["by_position_timeseries"][0]["series"],
            contribution_itd["by_position_timeseries"][1]["series"],
            strict=True,
        )
    ]
    assert contribution_daily_totals == pytest.approx(flattened_position_daily)
    assert sum(contribution_daily_totals) == pytest.approx(contribution_total)

    assert contribution_body["audit"]["counts"]["portfolio_reset_days"] == 2
    assert contribution_body["audit"]["counts"]["position_reset_days"] == 2
    assert contribution_body["audit"]["counts"]["timeseries_total_delta_periods"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_positions"] == 2
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_max_bp"] > 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_sum_bp"] > 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_material_periods"] == 1
    assert contribution_body["audit"]["counts"]["average_weight_shadow_cutover_candidate_periods"] == 1
    assert contribution_body["audit"]["counts"]["average_weight_sum_residual_bp"] == 0
    assert contribution_body["audit"]["counts"]["carino_invalid_domain_days"] == 1
    assert any(
        "Reset-aware average-weight shadow differs" in note for note in contribution_body["diagnostics"]["notes"]
    )
    assert any("differs materially" in note for note in contribution_body["diagnostics"]["notes"])
    assert any(
        "strong candidates for a future denominator cutover study" in note
        for note in contribution_body["diagnostics"]["notes"]
    )
    assert any(
        "Carino smoothing fell back to raw daily contribution arithmetic" in note
        for note in contribution_body["diagnostics"]["notes"]
    )


def test_e2e_asymmetric_reset_heavy_contribution_keeps_tie_out_while_exposing_weight_methodology_pressure() -> None:
    contribution_payload = {
        "portfolio_id": "E2E_ASYM_RESET_ALIGNMENT_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 550.0},
                {"perf_date": "2025-01-02", "begin_mv": 550.0, "end_mv": -25.0},
                {"perf_date": "2025-01-03", "begin_mv": -25.0, "bod_cf": 1000.0, "end_mv": 1072.5},
                {"perf_date": "2025-01-04", "begin_mv": 1072.5, "end_mv": 1179.75},
            ],
        },
        "positions_data": [
            {
                "position_id": "RESET_DRIVER",
                "meta": {"role": "driver"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 850.0, "end_mv": 350.0},
                    {"perf_date": "2025-01-02", "begin_mv": 350.0, "end_mv": -60.0},
                    {"perf_date": "2025-01-03", "begin_mv": -60.0, "bod_cf": 950.0, "end_mv": 997.5},
                    {"perf_date": "2025-01-04", "begin_mv": 997.5, "end_mv": 1097.25},
                ],
            },
            {
                "position_id": "RESET_RIDER",
                "meta": {"role": "rider"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 150.0, "end_mv": 200.0},
                    {"perf_date": "2025-01-02", "begin_mv": 200.0, "end_mv": 35.0},
                    {"perf_date": "2025-01-03", "begin_mv": 35.0, "bod_cf": 50.0, "end_mv": 75.0},
                    {"perf_date": "2025-01-04", "begin_mv": 75.0, "end_mv": 82.5},
                ],
            },
        ],
        "emit": {"timeseries": True, "by_position_timeseries": True},
    }

    with TestClient(app) as client:
        contribution_response = client.post("/performance/contribution", json=contribution_payload)

    assert contribution_response.status_code == 200

    contribution_body = contribution_response.json()
    contribution_itd = contribution_body["results_by_period"]["ITD"]
    position_contributions_by_id = {
        contribution["position_id"]: contribution for contribution in contribution_itd["position_contributions"]
    }
    driver_contribution = position_contributions_by_id["RESET_DRIVER"]
    rider_contribution = position_contributions_by_id["RESET_RIDER"]

    assert contribution_itd["total_portfolio_return"] == pytest.approx(21.0)
    assert contribution_itd["total_contribution"] == pytest.approx(21.0)
    assert driver_contribution["average_weight"] > rider_contribution["average_weight"]
    assert driver_contribution["total_contribution"] < rider_contribution["total_contribution"]

    contribution_daily_totals = [point["total_contribution"] for point in contribution_itd["timeseries"]]
    position_series_by_id = {
        position_series["position_id"]: position_series
        for position_series in contribution_itd["by_position_timeseries"]
    }
    flattened_position_daily = [
        first["contribution"] + second["contribution"]
        for first, second in zip(
            position_series_by_id["RESET_DRIVER"]["series"],
            position_series_by_id["RESET_RIDER"]["series"],
            strict=True,
        )
    ]
    assert contribution_daily_totals == pytest.approx(flattened_position_daily)
    assert sum(contribution_daily_totals) == pytest.approx(contribution_itd["total_contribution"])

    assert contribution_body["audit"]["counts"]["portfolio_reset_days"] == 2
    assert contribution_body["audit"]["counts"]["position_reset_days"] == 2
    assert contribution_body["audit"]["counts"]["timeseries_total_delta_periods"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_positions"] == 2
    assert contribution_body["audit"]["counts"]["average_weight_shadow_delta_max_bp"] >= 500
    assert (
        contribution_body["audit"]["counts"]["average_weight_shadow_delta_sum_bp"]
        >= contribution_body["audit"]["counts"]["average_weight_shadow_delta_max_bp"]
    )
    assert contribution_body["audit"]["counts"]["average_weight_shadow_material_periods"] == 1
    assert contribution_body["audit"]["counts"]["average_weight_shadow_cutover_candidate_periods"] == 1
    assert contribution_body["audit"]["counts"]["average_weight_sum_residual_bp"] == 0
    assert contribution_body["audit"]["counts"]["carino_invalid_domain_days"] == 1
    assert any(
        "Reset-aware average-weight shadow differs" in note for note in contribution_body["diagnostics"]["notes"]
    )
    assert any("differs materially" in note for note in contribution_body["diagnostics"]["notes"])
    assert any(
        "strong candidates for a future denominator cutover study" in note
        for note in contribution_body["diagnostics"]["notes"]
    )


def test_e2e_balanced_internal_position_flows_keep_flow_residual_silent() -> None:
    contribution_payload = {
        "portfolio_id": "E2E_BALANCED_INTERNAL_FLOWS_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1030.0},
                {"perf_date": "2025-01-02", "begin_mv": 1030.0, "end_mv": 1050.0},
            ],
        },
        "positions_data": [
            {
                "position_id": "REALLOCATED_OUT",
                "meta": {"role": "funding_leg"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 600.0, "end_mv": 618.0},
                    {"perf_date": "2025-01-02", "begin_mv": 618.0, "bod_cf": -100.0, "end_mv": 530.0},
                ],
            },
            {
                "position_id": "REALLOCATED_IN",
                "meta": {"role": "receiving_leg"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 400.0, "end_mv": 412.0},
                    {"perf_date": "2025-01-02", "begin_mv": 412.0, "bod_cf": 100.0, "end_mv": 520.0},
                ],
            },
        ],
        "emit": {"timeseries": True, "by_position_timeseries": True},
    }

    with TestClient(app) as client:
        contribution_response = client.post("/performance/contribution", json=contribution_payload)

    assert contribution_response.status_code == 200

    contribution_body = contribution_response.json()
    contribution_itd = contribution_body["results_by_period"]["ITD"]

    assert contribution_body["audit"]["counts"]["position_flow_residual_days"] == 0
    assert contribution_body["audit"]["counts"]["position_flow_residual_max_bp"] == 0
    assert contribution_body["audit"]["counts"]["position_flow_residual_sum_bp"] == 0
    assert contribution_body["audit"]["counts"]["average_weight_sum_residual_bp"] == 0
    assert contribution_body["audit"]["counts"]["timeseries_total_delta_periods"] == 0
    assert sum(item["average_weight"] for item in contribution_itd["position_contributions"]) == pytest.approx(100.0)
    assert not any(
        "Summed position-level cash flows did not net to zero" in note
        for note in contribution_body["diagnostics"]["notes"]
    )


def test_e2e_material_position_flow_mismatch_emits_cancellation_break_note() -> None:
    contribution_payload = {
        "portfolio_id": "E2E_MATERIAL_FLOW_MISMATCH_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1030.0},
                {"perf_date": "2025-01-02", "begin_mv": 1030.0, "end_mv": 1050.0},
            ],
        },
        "positions_data": [
            {
                "position_id": "FLOW_OUT",
                "meta": {"role": "funding_leg"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 600.0, "end_mv": 618.0},
                    {"perf_date": "2025-01-02", "begin_mv": 618.0, "bod_cf": -100.0, "end_mv": 530.0},
                ],
            },
            {
                "position_id": "FLOW_IN_INCOMPLETE",
                "meta": {"role": "receiving_leg"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 400.0, "end_mv": 412.0},
                    {"perf_date": "2025-01-02", "begin_mv": 412.0, "bod_cf": 80.0, "end_mv": 500.0},
                ],
            },
        ],
    }

    with TestClient(app) as client:
        contribution_response = client.post("/performance/contribution", json=contribution_payload)

    assert contribution_response.status_code == 200

    contribution_body = contribution_response.json()
    assert contribution_body["audit"]["counts"]["position_flow_residual_days"] == 1
    assert contribution_body["audit"]["counts"]["position_flow_residual_max_bp"] > 10
    assert (
        contribution_body["audit"]["counts"]["position_flow_residual_sum_bp"]
        >= contribution_body["audit"]["counts"]["position_flow_residual_max_bp"]
    )
    assert any("materially non-flow-neutral scoped slice" in note for note in contribution_body["diagnostics"]["notes"])


def test_e2e_health_endpoints_contract() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 200
    assert live.json()["status"] == "live"
    assert ready.json()["status"] == "ready"


def test_e2e_contribution_lineage_roundtrip() -> None:
    contribution_payload = {
        "portfolio_id": "E2E_CONTRIB_002",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
            }
        ],
        "emit": {"timeseries": True},
    }

    with TestClient(app) as client:
        contribution_response = client.post("/performance/contribution", json=contribution_payload)
        assert drain_lineage_queue() >= 1
        lineage_response = client.get(f"/performance/lineage/{contribution_response.json()['calculation_id']}")

    assert contribution_response.status_code == 200
    assert lineage_response.status_code == 200
    assert len(lineage_response.json()["artifacts"]) >= 1


def test_e2e_attribution_lineage_roundtrip() -> None:
    attribution_payload = {
        "portfolio_id": "E2E_ATTRIB_002",
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

    with TestClient(app) as client:
        attribution_response = client.post("/performance/attribution", json=attribution_payload)
        assert drain_lineage_queue() >= 1
        lineage_response = client.get(f"/performance/lineage/{attribution_response.json()['calculation_id']}")

    assert attribution_response.status_code == 200
    assert lineage_response.status_code == 200
    assert len(lineage_response.json()["artifacts"]) >= 1


def test_e2e_mwr_lineage_roundtrip() -> None:
    mwr_payload = {
        "portfolio_id": "E2E_MWR_002",
        "begin_mv": 1000.0,
        "end_mv": 1045.0,
        "cash_flows": [{"date": "2025-01-15", "amount": 25.0}],
        "as_of": "2025-01-31",
        "annualization": {"enabled": True, "basis": "ACT/365"},
    }

    with TestClient(app) as client:
        mwr_response = client.post("/performance/mwr", json=mwr_payload)
        assert drain_lineage_queue() >= 1
        lineage_response = client.get(f"/performance/lineage/{mwr_response.json()['calculation_id']}")

    assert mwr_response.status_code == 200
    assert lineage_response.status_code == 200
    assert mwr_response.json()["method"] is not None
    assert len(lineage_response.json()["artifacts"]) >= 1


def test_e2e_capabilities_toggle_disables_input_modes(monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_INPUT_MODE_STATEFUL_ENABLED", "false")
    monkeypatch.setenv("PLATFORM_INPUT_MODE_STATELESS_ENABLED", "false")
    monkeypatch.setenv("PA_CAP_ATTRIBUTION_ENABLED", "false")

    with TestClient(app) as client:
        response = client.get("/integration/capabilities?consumer_system=lotus-manage&tenant_id=tenant-b")

    assert response.status_code == 200
    body = response.json()
    assert body["supported_input_modes"] == []
    features = {item["key"]: item["enabled"] for item in body["features"]}
    surfaces = {item["key"]: item for item in body["analytics_surfaces"]}
    assert features["performance.analytics.attribution"] is False
    assert surfaces["attribution"]["enabled"] is False
    assert surfaces["returns_series"]["supported_input_modes"] == []


def test_e2e_contribution_rejects_empty_analyses_contract() -> None:
    payload = {
        "portfolio_id": "E2E_CONTRIB_INVALID_01",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        ],
    }
    with TestClient(app) as client:
        response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 422
    assert "analyses list cannot be empty" in response.text


def test_e2e_enterprise_authz_blocks_write_without_identity_headers(monkeypatch) -> None:
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    payload = {
        "portfolio_id": "E2E_AUTHZ_01",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }

    with TestClient(app) as client:
        response = client.post("/performance/twr", json=payload)

    assert response.status_code == 403
    assert response.json()["detail"] == "authorization_policy_denied"


def test_e2e_enterprise_authz_blocks_privileged_runtime_read_without_identity_headers(monkeypatch) -> None:
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")

    with TestClient(app) as client:
        response = client.get("/integration/runtime-status")

    assert response.status_code == 403
    assert response.json()["detail"] == "authorization_policy_denied"


def test_e2e_async_replay_uses_single_execution_handle() -> None:
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0
    calculation_id = str(uuid4())
    payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "E2E_CONTRIB_ASYNC_REPLAY",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
            }
        ],
    }

    try:
        with TestClient(app) as client:
            first = client.post("/performance/contribution", json=payload)
            second = client.post("/performance/contribution", json=payload)
            execution = client.get(f"/performance/executions/{calculation_id}")

            assert drain_compute_queue() >= 1

            result = client.get(f"/performance/contribution/results/{calculation_id}")

        assert first.status_code == 202
        assert second.status_code == 202
        assert execution.status_code == 200
        assert execution.json()["execution_mode"] == "async"
        assert result.status_code == 200
        assert result.json()["calculation_id"] == calculation_id
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold
