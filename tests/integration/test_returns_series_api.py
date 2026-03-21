from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.benchmark_requests import BenchmarkComponentObservation
from app.models.returns_series import InputMode, ReturnsSeriesRequest
from app.services.async_result_store import async_result_store
from app.services.returns_series_service import ResolvedStatefulReturnsSeriesRequest
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from core.repro import generate_canonical_hash
from main import app
from tests.conftest import drain_compute_queue

settings = get_settings()


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
    assert len(body["series"]["cumulative_portfolio_returns"]) == 5
    assert len(body["series"]["benchmark_returns"]) == 5
    assert len(body["series"]["cumulative_benchmark_returns"]) == 5
    assert len(body["series"]["risk_free_returns"]) == 5
    assert len(body["series"]["cumulative_risk_free_returns"]) == 5
    assert len(body["series"]["active_returns"]) == 5
    assert len(body["series"]["cumulative_active_returns"]) == 5
    assert [point["return_value"] for point in body["series"]["active_returns"]] == [
        "0E-12",
        "0E-12",
        "0E-12",
        "0E-12",
        "0E-12",
    ]
    assert [point["return_value"] for point in body["series"]["cumulative_active_returns"]] == [
        "0E-12",
        "0E-12",
        "0E-12",
        "0E-12",
        "0E-12",
    ]


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


def test_returns_series_sync_duplicate_submission_conflicts_on_reused_calculation_id():
    calculation_id = str(uuid4())
    payload = {
        **_stateless_base_payload(),
        "calculation_id": calculation_id,
    }

    with TestClient(app) as client:
        first = client.post("/integration/returns/series", json=payload)
        second = client.post("/integration/returns/series", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409


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

    async def _mock_build_stateful_benchmark_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-23",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0010,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-24",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0012,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-25",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=-0.0004,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-26",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0008,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-27",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0005,
                ),
            ],
            benchmark_return_points=[],
            source_details={"benchmark_components": 1, "component_observations": 5, "benchmark_chunk_count": 1},
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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr("app.services.returns_series_service.build_stateful_benchmark_input", _mock_build_stateful_benchmark_input)
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
        "stateful_input": {},
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"]["input_mode"] == "stateful"
    assert body["benchmark_context"] == {
        "benchmark_id": "BMK_GLOBAL_1",
        "return_source": "calculated",
    }
    assert len(body["series"]["portfolio_returns"]) == 5
    assert len(body["series"]["cumulative_portfolio_returns"]) == 5
    assert len(body["series"]["benchmark_returns"]) == 5
    assert len(body["series"]["cumulative_benchmark_returns"]) == 5
    assert len(body["series"]["risk_free_returns"]) == 5
    assert len(body["series"]["cumulative_risk_free_returns"]) == 5
    assert len(body["series"]["active_returns"]) == 5
    assert len(body["series"]["cumulative_active_returns"]) == 5
    assert body["series"]["active_returns"][0]["return_value"] == "0.009000000000"
    assert body["series"]["cumulative_active_returns"][0]["return_value"] == "0.009000000000"


def test_returns_series_stateful_provenance_uses_resolved_series_identity(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-20",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1020"},
                    {"valuation_date": "2026-02-25", "beginning_market_value": "1020", "ending_market_value": "1030"},
                ],
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_RESOLVED"}

    async def _mock_build_stateful_benchmark_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-23",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0010,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-24",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0015,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-25",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0020,
                ),
            ],
            benchmark_return_points=[],
            source_details={"benchmark_components": 1, "component_observations": 3, "benchmark_chunk_count": 1},
        )

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr("app.services.returns_series_service.build_stateful_benchmark_input", _mock_build_stateful_benchmark_input)

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
        "input_mode": "stateful",
        "stateful_input": {},
    }
    initial_input_fingerprint, initial_calculation_hash = generate_canonical_hash(payload, "returns-series-v1")

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"]["input_fingerprint"] != initial_input_fingerprint
    assert body["provenance"]["calculation_hash"] != initial_calculation_hash


def test_returns_series_stateful_vendor_series_override_uses_core_benchmark_series(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-20",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1020"},
                    {"valuation_date": "2026-02-25", "beginning_market_value": "1020", "ending_market_value": "1030"},
                ],
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_VENDOR"}

    async def _mock_get_benchmark_return_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-02-23", "benchmark_return": "0.0010"},
                    {"series_date": "2026-02-24", "benchmark_return": "0.0012"},
                    {"series_date": "2026-02-25", "benchmark_return": "0.0014"},
                ]
            },
        )

    async def _unexpected_build_stateful_benchmark_input(**kwargs):  # noqa: ARG001
        raise AssertionError("calculated benchmark path should not run for vendor_series override")

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
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
        "app.services.returns_series_service.build_stateful_benchmark_input",
        _unexpected_build_stateful_benchmark_input,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
        "benchmark": {"return_source": "vendor_series"},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["benchmark_context"] == {
        "benchmark_id": "BMK_VENDOR",
        "return_source": "vendor_series",
    }
    assert [point["return_value"] for point in body["series"]["benchmark_returns"]] == [
        "0.001000000000",
        "0.001200000000",
        "0.001400000000",
    ]


def test_returns_series_stateful_long_window_uses_chunked_portfolio_retrieval(monkeypatch):
    original_chunk_days = settings.STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS
    settings.STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS = 2
    calls: list[tuple[str, str]] = []

    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        calls.append((str(kwargs["start_date"]), str(kwargs["end_date"])))
        return (
            200,
            {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {
                        "valuation_date": str(kwargs["start_date"]),
                        "beginning_market_value": "1000",
                        "ending_market_value": "1005",
                    },
                    {
                        "valuation_date": str(kwargs["end_date"]),
                        "beginning_market_value": "1005",
                        "ending_market_value": "1010",
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        with TestClient(app) as client:
            response = client.post("/integration/returns/series", json=payload)
    finally:
        settings.STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS = original_chunk_days

    assert response.status_code == 200
    assert calls == [
        ("2026-02-23", "2026-02-24"),
        ("2026-02-25", "2026-02-26"),
        ("2026-02-27", "2026-02-27"),
    ]


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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
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
        "stateful_input": {},
    }

    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"


def test_returns_series_async_result_retrieval(monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 0

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
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        with TestClient(app) as client:
            accepted = client.post("/integration/returns/series", json=payload)
            assert accepted.status_code == 202
            calculation_id = accepted.json()["calculation_id"]

            pending_result = client.get(f"/integration/returns/series/results/{calculation_id}")
            assert pending_result.status_code == 202

            assert drain_compute_queue() >= 1

            complete_result = client.get(f"/integration/returns/series/results/{calculation_id}")
            assert complete_result.status_code == 200
            body = complete_result.json()
            assert body["calculation_id"] == calculation_id
            assert len(body["series"]["portfolio_returns"]) == 3
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold


def test_returns_series_async_result_retrieval_uses_durable_store(monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 0

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
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        with TestClient(app) as client:
            accepted = client.post("/integration/returns/series", json=payload)
            assert accepted.status_code == 202
            calculation_id = accepted.json()["calculation_id"]

            assert drain_compute_queue() == 1

            from app.services.compute_job_store import compute_job_store

            compute_job_store.clear_all_records()
            result = async_result_store.get_result(UUID(calculation_id))
            assert result is not None

            complete_result = client.get(f"/integration/returns/series/results/{calculation_id}")
            assert complete_result.status_code == 200
            assert complete_result.json()["calculation_id"] == calculation_id
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold


def test_returns_series_async_result_not_found_and_failed(monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 0

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

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-23",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-23"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        with TestClient(app) as client:
            missing = client.get(f"/integration/returns/series/results/{uuid4()}")
            assert missing.status_code == 404

            accepted = client.post("/integration/returns/series", json=payload)
            calculation_id = accepted.json()["calculation_id"]

            from app.services.compute_job_store import compute_job_store

            compute_job_store.mark_failed(UUID(calculation_id), error_message="executor boom")
            failed = client.get(f"/integration/returns/series/results/{calculation_id}")
            assert failed.status_code == 409
            assert failed.json()["detail"] == "executor boom"
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold


def test_returns_series_async_duplicate_submission_replays_same_request(monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 0

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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    calculation_id = str(uuid4())
    payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-24",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        with TestClient(app) as client:
            first = client.post("/integration/returns/series", json=payload)
            second = client.post("/integration/returns/series", json=payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["calculation_id"] == calculation_id
        assert second.json()["calculation_id"] == calculation_id
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold


def test_returns_series_async_duplicate_submission_conflicts_on_payload_drift(monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 0

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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    calculation_id = str(uuid4())
    first_payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-24",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }
    second_payload = {
        **first_payload,
        "frequency": "WEEKLY",
    }

    try:
        with TestClient(app) as client:
            first = client.post("/integration/returns/series", json=first_payload)
            second = client.post("/integration/returns/series", json=second_payload)

        assert first.status_code == 202
        assert second.status_code == 409
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold


def test_returns_series_stateful_short_window_offloads_on_resolved_workload(monkeypatch):
    original_window_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 30
    settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT = 3

    resolved_request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "DEMO_DPM_EUR_001",
            "calculation_id": str(uuid4()),
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                    {"date": "2026-02-24", "return_value": "0.0050"},
                    {"date": "2026-02-25", "return_value": "-0.0025"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-23", "return_value": "0.0010"},
                    {"date": "2026-02-24", "return_value": "0.0012"},
                    {"date": "2026-02-25", "return_value": "0.0014"},
                ],
            },
        }
    )

    async def _mock_resolve_stateful_returns_series_request(request):  # noqa: ARG001
        resolved_payload = {
            "portfolio_id": "DEMO_DPM_EUR_001",
            "as_of_date": "2026-02-25",
            "resolved_window": {
                "start_date": "2026-02-23",
                "end_date": "2026-02-25",
                "resolved_period_label": None,
            },
            "frequency": "DAILY",
            "metric_basis": "NET",
            "reporting_currency": None,
            "series_selection": {
                "include_portfolio": True,
                "include_benchmark": True,
                "include_risk_free": False,
            },
            "benchmark": {
                "benchmark_id": "BMK_RESOLVED",
                "return_source": "calculated",
            },
            "risk_free": None,
            "data_policy": {
                "missing_data_policy": "FAIL_FAST",
                "fill_method": "NONE",
                "calendar_policy": "BUSINESS",
                "max_gap_days": None,
            },
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                    {"date": "2026-02-24", "return_value": "0.0050"},
                    {"date": "2026-02-25", "return_value": "-0.0025"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-23", "return_value": "0.0010"},
                    {"date": "2026-02-24", "return_value": "0.0012"},
                    {"date": "2026-02-25", "return_value": "0.0014"},
                ],
                "risk_free_returns": None,
            },
        }
        return ResolvedStatefulReturnsSeriesRequest(
            request=resolved_request.model_copy(update={"calculation_id": request.calculation_id}),
            identity_payload=resolved_payload,
            input_count=5,
            resolved_benchmark_id="BMK_RESOLVED",
            resolved_benchmark_return_source="calculated",
            benchmark_work_units=5,
        )

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.resolve_stateful_returns_series_request",
        _mock_resolve_stateful_returns_series_request,
    )

    calculation_id = str(uuid4())
    payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True},
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        with TestClient(app) as client:
            accepted = client.post("/integration/returns/series", json=payload)
            assert accepted.status_code == 202

            replay = client.post("/integration/returns/series", json=payload)
            assert replay.status_code == 202

            assert drain_compute_queue() >= 1

            result = client.get(f"/integration/returns/series/results/{calculation_id}")
            assert result.status_code == 200
            body = result.json()
            assert body["provenance"]["input_mode"] == InputMode.STATEFUL.value
            assert body["benchmark_context"] == {
                "benchmark_id": "BMK_RESOLVED",
                "return_source": "calculated",
            }
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_returns_series_stateful_source_unavailable(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return 503, {"detail": "unavailable"}

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
    }
    with TestClient(app) as client:
        response = client.post("/integration/returns/series", json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SOURCE_UNAVAILABLE"


def test_returns_series_stateful_requires_observations(monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return 200, {"portfolio_open_date": "2026-02-23", "observations": []}

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-27"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {},
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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
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
        "stateful_input": {},
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
