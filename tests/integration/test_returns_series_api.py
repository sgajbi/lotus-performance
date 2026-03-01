from decimal import Decimal

from fastapi.testclient import TestClient

from main import app


def _daily_points():
    return [
        {"date": "2026-02-23", "return_value": "0.0100"},
        {"date": "2026-02-24", "return_value": "0.0050"},
        {"date": "2026-02-25", "return_value": "-0.0025"},
        {"date": "2026-02-26", "return_value": "0.0030"},
        {"date": "2026-02-27", "return_value": "0.0015"},
    ]


def _stateless_base_payload():
    return {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateless",
        "stateless_input": {
            "portfolio_returns": _daily_points(),
        },
    }


def test_returns_series_stateless_daily_success_with_benchmark_and_risk_free():
    payload = _stateless_base_payload()
    payload["series_selection"] = {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True}
    payload["stateless_input"]["benchmark_returns"] = _daily_points()
    payload["stateless_input"]["risk_free_returns"] = _daily_points()

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"]["input_mode"] == "stateless"
    assert len(body["series"]["portfolio_returns"]) == 5
    assert len(body["series"]["benchmark_returns"]) == 5
    assert len(body["series"]["risk_free_returns"]) == 5


def test_returns_series_stateless_weekly_uses_geometric_linking():
    payload = _stateless_base_payload()
    payload["frequency"] = "WEEKLY"

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    points = response.json()["series"]["portfolio_returns"]
    assert len(points) == 1
    expected = (
        Decimal("1.0100") * Decimal("1.0050") * Decimal("0.9975") * Decimal("1.0030") * Decimal("1.0015")
    ) - Decimal("1")
    actual = Decimal(points[0]["return_value"])
    assert abs(actual - expected) < Decimal("0.0000000001")


def test_returns_series_rejects_duplicate_dates():
    payload = _stateless_base_payload()
    payload["window"] = {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-24"}
    payload["stateless_input"]["portfolio_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0010"},
        {"date": "2026-02-24", "return_value": "0.0020"},
    ]

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"


def test_returns_series_stateful_fetches_benchmark_and_risk_free(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1015"},
                    {
                        "valuation_date": "2026-02-25",
                        "beginning_market_value": "1015",
                        "ending_market_value": "1012.46",
                    },
                    {
                        "valuation_date": "2026-02-26",
                        "beginning_market_value": "1012.46",
                        "ending_market_value": "1015.49738",
                    },
                    {
                        "valuation_date": "2026-02-27",
                        "beginning_market_value": "1015.49738",
                        "ending_market_value": "1017.02062607",
                    },
                ],
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_GLOBAL_1"}

    async def _mock_get_benchmark_return_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-02-23", "benchmark_return": "0.0010"},
                    {"series_date": "2026-02-24", "benchmark_return": "0.0012"},
                    {"series_date": "2026-02-25", "benchmark_return": "-0.0004"},
                    {"series_date": "2026-02-26", "benchmark_return": "0.0008"},
                    {"series_date": "2026-02-27", "benchmark_return": "0.0005"},
                ]
            },
        )

    async def _mock_get_risk_free_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-02-23", "value": "0.0001"},
                    {"series_date": "2026-02-24", "value": "0.0001"},
                    {"series_date": "2026-02-25", "value": "0.0001"},
                    {"series_date": "2026-02-26", "value": "0.0001"},
                    {"series_date": "2026-02-27", "value": "0.0001"},
                ]
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_benchmark_return_series",
        _mock_get_benchmark_return_series,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_risk_free_series",
        _mock_get_risk_free_series,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "reporting_currency": "USD",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"]["input_mode"] == "stateful"
    assert len(body["series"]["portfolio_returns"]) == 5
    assert len(body["series"]["benchmark_returns"]) == 5
    assert len(body["series"]["risk_free_returns"]) == 5


def test_returns_series_stateful_requires_reporting_currency_for_risk_free(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1015"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_risk_free": True},
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"


def test_returns_series_stateful_source_unavailable(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return 503, {"detail": "unavailable"}

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SOURCE_UNAVAILABLE"


def test_returns_series_stateful_requires_observations(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return 200, {"portfolio_open_date": "2026-02-23", "observations": []}

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INSUFFICIENT_DATA"


def test_returns_series_stateful_requires_valid_portfolio_open_date(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "bad-date",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"}
                ],
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INSUFFICIENT_DATA"


def test_returns_series_stateful_benchmark_assignment_error_mapping(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"}
                ],
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 404, {"detail": "missing"}

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True},
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 404


def test_returns_series_stateless_strict_intersection_no_overlap_fails():
    payload = _stateless_base_payload()
    payload["series_selection"] = {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True}
    payload["data_policy"] = {
        "missing_data_policy": "STRICT_INTERSECTION",
        "fill_method": "NONE",
        "calendar_policy": "BUSINESS",
    }
    payload["stateless_input"]["portfolio_returns"] = [
        {"date": "2026-02-23", "return_value": "0.0010"},
        {"date": "2026-02-24", "return_value": "0.0010"},
    ]
    payload["stateless_input"]["benchmark_returns"] = [
        {"date": "2026-02-25", "return_value": "0.0010"},
        {"date": "2026-02-26", "return_value": "0.0010"},
    ]
    payload["stateless_input"]["risk_free_returns"] = [
        {"date": "2026-02-27", "return_value": "0.0001"},
    ]
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INSUFFICIENT_DATA"


def test_returns_series_stateless_forward_fill_applies():
    payload = _stateless_base_payload()
    payload["window"] = {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"}
    payload["series_selection"] = {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True}
    payload["data_policy"] = {
        "missing_data_policy": "ALLOW_PARTIAL",
        "fill_method": "FORWARD_FILL",
        "calendar_policy": "BUSINESS",
    }
    payload["stateless_input"]["portfolio_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0010"},
        {"date": "2026-02-25", "return_value": "0.0012"},
        {"date": "2026-02-26", "return_value": "0.0014"},
        {"date": "2026-02-27", "return_value": "0.0016"},
    ]
    payload["stateless_input"]["benchmark_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0020"},
        {"date": "2026-02-26", "return_value": "0.0030"},
    ]
    payload["stateless_input"]["risk_free_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0001"},
        {"date": "2026-02-26", "return_value": "0.0003"},
    ]
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 200
    benchmark_values = [p["return_value"] for p in response.json()["series"]["benchmark_returns"]]
    assert benchmark_values == ["0.002000000000", "0.002000000000", "0.003000000000", "0.003000000000"]


def test_returns_series_stateless_zero_fill_applies():
    payload = _stateless_base_payload()
    payload["window"] = {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"}
    payload["series_selection"] = {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True}
    payload["data_policy"] = {
        "missing_data_policy": "ALLOW_PARTIAL",
        "fill_method": "ZERO_FILL",
        "calendar_policy": "BUSINESS",
    }
    payload["stateless_input"]["portfolio_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0010"},
        {"date": "2026-02-25", "return_value": "0.0012"},
        {"date": "2026-02-26", "return_value": "0.0014"},
        {"date": "2026-02-27", "return_value": "0.0016"},
    ]
    payload["stateless_input"]["benchmark_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0020"},
        {"date": "2026-02-26", "return_value": "0.0030"},
    ]
    payload["stateless_input"]["risk_free_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0001"},
        {"date": "2026-02-26", "return_value": "0.0003"},
    ]
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 200
    benchmark_values = [p["return_value"] for p in response.json()["series"]["benchmark_returns"]]
    assert benchmark_values == ["0.002000000000", "0E-12", "0.003000000000", "0E-12"]


def test_returns_series_stateless_fail_fast_rejects_missing_points():
    payload = _stateless_base_payload()
    payload["window"] = {"mode": "EXPLICIT", "from_date": "2026-02-21", "to_date": "2026-02-27"}
    payload["data_policy"] = {
        "missing_data_policy": "FAIL_FAST",
        "fill_method": "NONE",
        "calendar_policy": "CALENDAR",
    }
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INSUFFICIENT_DATA"


def test_returns_series_stateless_market_calendar_emits_warning():
    payload = _stateless_base_payload()
    payload["window"] = {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"}
    payload["stateless_input"]["portfolio_returns"] = [
        {"date": "2026-02-24", "return_value": "0.0010"},
        {"date": "2026-02-25", "return_value": "0.0012"},
        {"date": "2026-02-26", "return_value": "0.0014"},
        {"date": "2026-02-27", "return_value": "0.0016"},
    ]
    payload["data_policy"] = {
        "missing_data_policy": "ALLOW_PARTIAL",
        "fill_method": "NONE",
        "calendar_policy": "MARKET",
    }
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 200
    assert (
        "MARKET calendar policy currently uses business-day approximation."
        in response.json()["diagnostics"]["warnings"]
    )
