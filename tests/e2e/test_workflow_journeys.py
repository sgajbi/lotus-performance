from fastapi.testclient import TestClient

from main import app


def test_e2e_platform_readiness_and_capabilities_contract() -> None:
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
    assert "core_api_ref" in body["supported_input_modes"]
    assert "inline_bundle" in body["supported_input_modes"]


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

        contribution_lineage = client.get(f"/performance/lineage/{contribution_response.json()['calculation_id']}")
        attribution_lineage = client.get(f"/performance/lineage/{attribution_response.json()['calculation_id']}")

    assert contribution_response.status_code == 200
    assert attribution_response.status_code == 200
    assert contribution_lineage.status_code == 200
    assert attribution_lineage.status_code == 200


def test_e2e_pas_connected_modes(monkeypatch) -> None:
    async def _mock_get_performance_input(self, portfolio_id, as_of_date, lookback_days, consumer_system):  # noqa: ARG001
        return (
            200,
            {
                "contract_version": "v1",
                "consumer_system": "lotus-gateway",
                "portfolio_id": portfolio_id,
                "performance_start_date": "2026-01-01",
                "valuation_points": [
                    {"day": 1, "perf_date": "2026-02-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"day": 2, "perf_date": "2026-02-23", "begin_mv": 101.0, "end_mv": 102.0},
                ],
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.performance.PasInputService.get_performance_input",
        _mock_get_performance_input,
    )

    twr_pas_payload = {"portfolio_id": "PORT-1001", "as_of_date": "2026-02-23", "periods": ["YTD"]}

    with TestClient(app) as client:
        twr_pas_response = client.post("/performance/twr/pas-input", json=twr_pas_payload)

    assert twr_pas_response.status_code == 200
    assert twr_pas_response.json()["source_mode"] == "core_api_ref"


def test_e2e_core_api_ref_capability_and_execution_contract(monkeypatch) -> None:
    async def _mock_get_performance_input(self, portfolio_id, as_of_date, lookback_days, consumer_system):  # noqa: ARG001
        return (
            200,
            {
                "contract_version": "v1",
                "consumer_system": consumer_system,
                "portfolio_id": portfolio_id,
                "performance_start_date": "2026-01-01",
                "valuation_points": [
                    {"day": 1, "perf_date": "2026-02-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"day": 2, "perf_date": "2026-02-23", "begin_mv": 101.0, "end_mv": 102.0},
                ],
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.performance.PasInputService.get_performance_input",
        _mock_get_performance_input,
    )
    with TestClient(app) as client:
        capabilities = client.get("/integration/capabilities?consumer_system=lotus-gateway&tenant_id=default")
        twr_pas = client.post(
            "/performance/twr/pas-input",
            json={
                "portfolio_id": "PORT-1002",
                "as_of_date": "2026-02-23",
                "consumer_system": "lotus-gateway",
                "periods": ["YTD"],
            },
        )

    assert capabilities.status_code == 200
    assert twr_pas.status_code == 200
    assert "core_api_ref" in capabilities.json()["supported_input_modes"]
    assert twr_pas.json()["source_mode"] == "core_api_ref"
    assert "YTD" in twr_pas.json()["results_by_period"]


def test_e2e_health_endpoints_contract() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 200
    assert live.json()["status"] == "live"
    assert ready.json()["status"] == "ready"


def test_e2e_core_api_ref_upstream_failure_passthrough(monkeypatch) -> None:
    async def _mock_get_performance_input(self, portfolio_id, as_of_date, lookback_days, consumer_system):  # noqa: ARG001
        return 503, {"detail": "lotus-core unavailable"}

    monkeypatch.setattr(
        "app.api.endpoints.performance.PasInputService.get_performance_input",
        _mock_get_performance_input,
    )

    with TestClient(app) as client:
        response = client.post(
            "/performance/twr/pas-input",
            json={"portfolio_id": "PORT-DOWN", "as_of_date": "2026-02-23", "consumer_system": "lotus-gateway"},
        )

    assert response.status_code == 503
    assert "lotus-core unavailable" in response.json()["detail"]


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
        lineage_response = client.get(f"/performance/lineage/{mwr_response.json()['calculation_id']}")

    assert mwr_response.status_code == 200
    assert lineage_response.status_code == 200
    assert mwr_response.json()["method"] is not None
    assert len(lineage_response.json()["artifacts"]) >= 1


def test_e2e_capabilities_toggle_disables_input_modes(monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_INPUT_MODE_CORE_API_REFERENCE_ENABLED", "false")
    monkeypatch.setenv("PLATFORM_INPUT_MODE_INLINE_BUNDLE_ENABLED", "false")
    monkeypatch.setenv("PA_CAP_ATTRIBUTION_ENABLED", "false")

    with TestClient(app) as client:
        response = client.get("/integration/capabilities?consumer_system=lotus-manage&tenant_id=tenant-b")

    assert response.status_code == 200
    body = response.json()
    assert body["supported_input_modes"] == []
    features = {item["key"]: item["enabled"] for item in body["features"]}
    assert features["pa.analytics.attribution"] is False


def test_e2e_pas_input_metadata_fallback_contract(monkeypatch) -> None:
    async def _mock_get_performance_input(self, portfolio_id, as_of_date, lookback_days, consumer_system):  # noqa: ARG001
        return (
            200,
            {
                "performance_start_date": "2026-01-01",
                "valuation_points": [
                    {"day": 1, "perf_date": "2026-02-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"day": 2, "perf_date": "2026-02-23", "begin_mv": 101.0, "end_mv": 102.0},
                ],
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.performance.PasInputService.get_performance_input",
        _mock_get_performance_input,
    )

    with TestClient(app) as client:
        response = client.post(
            "/performance/twr/pas-input",
            json={
                "portfolio_id": "PORT-E2E-FALLBACK",
                "as_of_date": "2026-02-23",
                "consumer_system": "lotus-gateway",
                "periods": ["YTD"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "PORT-E2E-FALLBACK"
    assert body["consumer_system"] == "lotus-gateway"
    assert body["pas_contract_version"] == "v1"


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
