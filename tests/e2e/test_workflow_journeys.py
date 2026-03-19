import os
from datetime import date
from uuid import uuid4

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
            {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"day": 2, "perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
            {"day": 3, "perf_date": "2025-01-03", "begin_mv": 1020.1, "end_mv": 1030.301},
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
    assert twr_body["results_by_period"]["ITD"]["portfolio_return"]["base"] > 0

    mwr_body = mwr_response.json()
    assert mwr_body["portfolio_id"] == "E2E_WORKFLOW_001"


def test_e2e_stateful_analytics_workflow(monkeypatch) -> None:
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
                        "beginning_market_value": "100000",
                        "ending_market_value": "110000",
                        "cash_flows": [{"amount": "10000", "timing": "bod"}],
                    },
                    {
                        "valuation_date": "2025-01-03",
                        "beginning_market_value": "110000",
                        "ending_market_value": "111000",
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
            date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            date=date(2025, 1, 2),
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
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-02",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }
    mwr_payload = {
        "portfolio_id": "E2E_STATEFUL_001",
        "as_of": "2025-01-02",
        "mwr_method": "DIETZ",
        "input_mode": "stateful",
        "stateful_input": {
            "consumer_system": "lotus-performance",
            "window_start_date": "2025-01-01",
        },
    }
    contribution_payload = {
        "portfolio_id": "E2E_STATEFUL_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
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
        "stateful_input": {"consumer_system": "lotus-performance"},
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


def test_e2e_contribution_attribution_and_lineage() -> None:
    contribution_payload = {
        "portfolio_id": "E2E_CONTRIB_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
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
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
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
    assert features["pa.analytics.attribution"] is False
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
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
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
        "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
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
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "positions_data": [
            {
                "position_id": "AAPL",
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
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
