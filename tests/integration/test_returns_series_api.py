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


def test_returns_series_inline_daily_success_with_benchmark_and_risk_free():
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {
            "include_portfolio": True,
            "include_benchmark": True,
            "include_risk_free": True,
        },
        "data_policy": {
            "missing_data_policy": "ALLOW_PARTIAL",
            "fill_method": "NONE",
            "calendar_policy": "BUSINESS",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": _daily_points(),
                "benchmark_returns": _daily_points(),
                "risk_free_returns": _daily_points(),
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["source_service"] == "lotus-performance"
    assert body["portfolio_id"] == "DEMO_DPM_EUR_001"
    assert body["frequency"] == "DAILY"
    assert len(body["series"]["portfolio_returns"]) == 5
    assert len(body["series"]["benchmark_returns"]) == 5
    assert len(body["series"]["risk_free_returns"]) == 5
    assert body["diagnostics"]["coverage"]["coverage_ratio"] == "1.0"
    assert body["provenance"]["input_mode"] == "inline_bundle"
    assert body["metadata"]["correlation_id"] is not None
    assert response.headers.get("X-Correlation-Id")


def test_returns_series_weekly_uses_geometric_linking():
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "WEEKLY",
        "metric_basis": "NET",
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": _daily_points(),
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    points = body["series"]["portfolio_returns"]
    assert len(points) == 1
    expected = (
        Decimal("1.0100") * Decimal("1.0050") * Decimal("0.9975") * Decimal("1.0030") * Decimal("1.0015")
    ) - Decimal("1")
    actual = Decimal(points[0]["return_value"])
    assert abs(actual - expected) < Decimal("0.0000000001")


def test_returns_series_strict_intersection_aligns_dates():
    benchmark_points = [
        {"date": "2026-02-24", "return_value": "0.0050"},
        {"date": "2026-02-25", "return_value": "-0.0025"},
        {"date": "2026-02-26", "return_value": "0.0030"},
    ]
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
        "data_policy": {
            "missing_data_policy": "STRICT_INTERSECTION",
            "fill_method": "NONE",
            "calendar_policy": "BUSINESS",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": _daily_points(),
                "benchmark_returns": benchmark_points,
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert [p["date"] for p in body["series"]["portfolio_returns"]] == ["2026-02-24", "2026-02-25", "2026-02-26"]
    assert [p["date"] for p in body["series"]["benchmark_returns"]] == ["2026-02-24", "2026-02-25", "2026-02-26"]


def test_returns_series_strict_intersection_aligns_risk_free_dates_too():
    benchmark_points = [
        {"date": "2026-02-24", "return_value": "0.0050"},
        {"date": "2026-02-25", "return_value": "-0.0025"},
        {"date": "2026-02-26", "return_value": "0.0030"},
    ]
    risk_free_points = [
        {"date": "2026-02-25", "return_value": "0.0001"},
        {"date": "2026-02-26", "return_value": "0.0001"},
        {"date": "2026-02-27", "return_value": "0.0001"},
    ]
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        "data_policy": {
            "missing_data_policy": "STRICT_INTERSECTION",
            "fill_method": "NONE",
            "calendar_policy": "BUSINESS",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": _daily_points(),
                "benchmark_returns": benchmark_points,
                "risk_free_returns": risk_free_points,
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    expected_dates = ["2026-02-25", "2026-02-26"]
    assert [p["date"] for p in body["series"]["portfolio_returns"]] == expected_dates
    assert [p["date"] for p in body["series"]["benchmark_returns"]] == expected_dates
    assert [p["date"] for p in body["series"]["risk_free_returns"]] == expected_dates


def test_returns_series_rejects_duplicate_dates():
    duplicate_points = [
        {"date": "2026-02-24", "return_value": "0.0010"},
        {"date": "2026-02-24", "return_value": "0.0020"},
    ]
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-24"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": duplicate_points,
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "INVALID_REQUEST"


def test_returns_series_core_api_ref_fetches_benchmark_and_risk_free(monkeypatch):
    async def _mock_get_performance_input(self, portfolio_id, as_of_date, lookback_days, consumer_system):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_id": portfolio_id,
                "performance_start_date": "2026-02-23",
                "valuation_points": [
                    {"day": 1, "perf_date": "2026-02-23", "begin_mv": 1000.0, "end_mv": 1010.0},
                    {"day": 2, "perf_date": "2026-02-24", "begin_mv": 1010.0, "end_mv": 1015.0},
                    {"day": 3, "perf_date": "2026-02-25", "begin_mv": 1015.0, "end_mv": 1012.46},
                    {"day": 4, "perf_date": "2026-02-26", "begin_mv": 1012.46, "end_mv": 1015.49738},
                    {"day": 5, "perf_date": "2026-02-27", "begin_mv": 1015.49738, "end_mv": 1017.02062607},
                ],
            },
        )

    async def _mock_get_benchmark_assignment(self, portfolio_id, as_of_date, reporting_currency=None):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_GLOBAL_1"}

    async def _mock_get_benchmark_return_series(
        self, benchmark_id, as_of_date, start_date, end_date, frequency="daily"
    ):  # noqa: ARG001
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

    async def _mock_get_risk_free_series(
        self, currency, as_of_date, start_date, end_date, frequency="daily", series_mode="return_series"
    ):  # noqa: ARG001
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
        "app.api.endpoints.returns_series.PasInputService.get_performance_input",
        _mock_get_performance_input,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.PasInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.PasInputService.get_benchmark_return_series",
        _mock_get_benchmark_return_series,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.PasInputService.get_risk_free_series",
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
        "source": {
            "input_mode": "core_api_ref",
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert len(body["series"]["portfolio_returns"]) == 5
    assert len(body["series"]["benchmark_returns"]) == 5
    assert len(body["series"]["risk_free_returns"]) == 5
    assert body["provenance"]["input_mode"] == "core_api_ref"
    assert {source["service"] for source in body["provenance"]["upstream_sources"]} == {"lotus-core"}


def test_returns_series_core_api_ref_requires_reporting_currency_for_risk_free(monkeypatch):
    async def _mock_get_performance_input(self, portfolio_id, as_of_date, lookback_days, consumer_system):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_id": portfolio_id,
                "performance_start_date": "2026-02-23",
                "valuation_points": [
                    {"day": 1, "perf_date": "2026-02-23", "begin_mv": 1000.0, "end_mv": 1010.0},
                    {"day": 2, "perf_date": "2026-02-24", "begin_mv": 1010.0, "end_mv": 1015.0},
                ],
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.PasInputService.get_performance_input",
        _mock_get_performance_input,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_risk_free": True},
        "source": {
            "input_mode": "core_api_ref",
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "INVALID_REQUEST"


def test_returns_series_strict_intersection_no_overlap_fails():
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        "data_policy": {
            "missing_data_policy": "STRICT_INTERSECTION",
            "fill_method": "NONE",
            "calendar_policy": "BUSINESS",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0010"},
                    {"date": "2026-02-24", "return_value": "0.0010"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-25", "return_value": "0.0010"},
                    {"date": "2026-02-26", "return_value": "0.0010"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-27", "return_value": "0.0001"},
                ],
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "INSUFFICIENT_DATA"


def test_returns_series_forward_fill_applies_to_benchmark_and_risk_free():
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        "data_policy": {
            "missing_data_policy": "ALLOW_PARTIAL",
            "fill_method": "FORWARD_FILL",
            "calendar_policy": "BUSINESS",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": [
                    {"date": "2026-02-24", "return_value": "0.0010"},
                    {"date": "2026-02-25", "return_value": "0.0012"},
                    {"date": "2026-02-26", "return_value": "0.0014"},
                    {"date": "2026-02-27", "return_value": "0.0016"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-24", "return_value": "0.0020"},
                    {"date": "2026-02-26", "return_value": "0.0030"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-24", "return_value": "0.0001"},
                    {"date": "2026-02-26", "return_value": "0.0003"},
                ],
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    benchmark_values = [p["return_value"] for p in body["series"]["benchmark_returns"]]
    risk_free_values = [p["return_value"] for p in body["series"]["risk_free_returns"]]
    assert benchmark_values == ["0.002000000000", "0.002000000000", "0.003000000000", "0.003000000000"]
    assert risk_free_values == ["0.000100000000", "0.000100000000", "0.000300000000", "0.000300000000"]


def test_returns_series_zero_fill_applies_to_benchmark_and_risk_free():
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        "data_policy": {
            "missing_data_policy": "ALLOW_PARTIAL",
            "fill_method": "ZERO_FILL",
            "calendar_policy": "BUSINESS",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": [
                    {"date": "2026-02-24", "return_value": "0.0010"},
                    {"date": "2026-02-25", "return_value": "0.0012"},
                    {"date": "2026-02-26", "return_value": "0.0014"},
                    {"date": "2026-02-27", "return_value": "0.0016"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-24", "return_value": "0.0020"},
                    {"date": "2026-02-26", "return_value": "0.0030"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-24", "return_value": "0.0001"},
                    {"date": "2026-02-26", "return_value": "0.0003"},
                ],
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    benchmark_values = [p["return_value"] for p in body["series"]["benchmark_returns"]]
    risk_free_values = [p["return_value"] for p in body["series"]["risk_free_returns"]]
    assert benchmark_values == ["0.002000000000", "0E-12", "0.003000000000", "0E-12"]
    assert risk_free_values == ["0.000100000000", "0E-12", "0.000300000000", "0E-12"]


def test_returns_series_fail_fast_rejects_missing_points():
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-21", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "data_policy": {
            "missing_data_policy": "FAIL_FAST",
            "fill_method": "NONE",
            "calendar_policy": "CALENDAR",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": _daily_points(),
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "INSUFFICIENT_DATA"


def test_returns_series_market_calendar_emits_warning():
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "data_policy": {
            "missing_data_policy": "ALLOW_PARTIAL",
            "fill_method": "NONE",
            "calendar_policy": "MARKET",
        },
        "source": {
            "input_mode": "inline_bundle",
            "inline_bundle": {
                "portfolio_returns": [
                    {"date": "2026-02-24", "return_value": "0.0010"},
                    {"date": "2026-02-25", "return_value": "0.0012"},
                    {"date": "2026-02-26", "return_value": "0.0014"},
                    {"date": "2026-02-27", "return_value": "0.0016"},
                ],
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "MARKET calendar policy currently uses business-day approximation." in body["diagnostics"]["warnings"]
