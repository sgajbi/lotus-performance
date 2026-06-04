from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import HTTPException

from app.models.benchmark_requests import BenchmarkComponentObservation
from app.models.returns_series import (
    CalendarPolicy,
    FillMethod,
    MissingDataPolicy,
    ReturnPoint,
    ReturnsFrequency,
    ReturnsSeriesRequest,
)
from app.services import portfolio_source_service, returns_series_service, stateful_input_service
from app.services.execution_registry import ExecutionRegistry
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from core.repro import generate_canonical_hash


def test_build_active_return_points_uses_aligned_arithmetic_difference():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0050"), Decimal("-0.0025")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0010"), Decimal("0.0005")],
        }
    )

    active_points = returns_series_service.build_active_return_points(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
    )

    assert active_points is not None
    assert [point.date.isoformat() for point in active_points] == ["2026-02-24", "2026-02-25"]
    assert [str(point.return_value) for point in active_points] == ["0.004000000000", "-0.003000000000"]


def test_daily_return_percentage_to_ratio_uses_shared_numeric_fallback():
    assert returns_series_service._daily_return_percentage_to_ratio("1.25") == Decimal("0.0125")
    assert returns_series_service._daily_return_percentage_to_ratio("not-a-number") is None


def test_to_dataframe_normalizes_mixed_date_like_return_points_to_timestamps():
    df = returns_series_service.to_dataframe(
        [
            ReturnPoint(date="2026-02-24", return_value=Decimal("0.002")),
            ReturnPoint(date=pd.Timestamp("2026-02-23T10:00:00Z").date(), return_value=Decimal("0.001")),
        ],
        series_type="portfolio",
    )

    assert [value.date().isoformat() for value in df["date"]] == ["2026-02-23", "2026-02-24"]


def test_benchmark_daily_returns_to_dataframe_preserves_index_during_timestamp_normalization():
    source_df = pd.DataFrame(
        {
            "date": ["2026-02-23", pd.Timestamp("2026-02-24T10:00:00Z")],
            "benchmark_return": [Decimal("0.001"), Decimal("0.002")],
        },
        index=[10, 11],
    )

    benchmark_df = returns_series_service._benchmark_daily_returns_to_dataframe(source_df)

    assert [value.date().isoformat() for value in benchmark_df["date"]] == ["2026-02-23", "2026-02-24"]
    assert benchmark_df["return_value"].tolist() == [Decimal("0.001"), Decimal("0.002")]


def test_build_cumulative_active_return_points_uses_cumulative_excess_not_linked_active():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.1000"), Decimal("0.1000")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0500"), Decimal("0.0500")],
        }
    )

    cumulative_active_points = returns_series_service.build_cumulative_active_return_points(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
    )

    assert cumulative_active_points is not None
    assert [point.date.isoformat() for point in cumulative_active_points] == ["2026-02-23", "2026-02-24"]
    assert [str(point.return_value) for point in cumulative_active_points] == [
        "0.050000000000",
        "0.107500000000",
    ]


def test_risk_free_points_to_dataframe_converts_annualized_rates_to_daily_returns():
    risk_free_df = returns_series_service.risk_free_points_to_dataframe(
        points=[
            {
                "series_date": "2026-04-10",
                "value": "0.0435",
                "value_convention": "annualized_rate",
                "day_count_convention": "ACT_360",
            },
            {
                "series_date": "2026-04-11",
                "value": "0.0365",
                "value_convention": "annualized_rate",
                "day_count_convention": "ACT_365",
            },
            {
                "series_date": "2026-04-12",
                "value": "0.0002",
                "value_convention": "period_return",
            },
        ]
    )

    assert [str(value) for value in risk_free_df["return_value"]] == [
        "0.0001208333333333333333333333333",
        "0.0001",
        "0.0002",
    ]


def test_apply_calendar_policy_filters_daily_business_and_market_dates():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-10", "2026-04-11", "2026-04-12", "2026-04-13"]),
            "return_value": [Decimal("0.001"), Decimal("0.002"), Decimal("0.003"), Decimal("0.004")],
        }
    )

    business_df = returns_series_service.apply_calendar_policy(
        df,
        frequency=ReturnsFrequency.DAILY,
        calendar_policy=CalendarPolicy.BUSINESS,
    )
    market_df = returns_series_service.apply_calendar_policy(
        df,
        frequency=ReturnsFrequency.DAILY,
        calendar_policy=CalendarPolicy.MARKET,
    )
    calendar_df = returns_series_service.apply_calendar_policy(
        df,
        frequency=ReturnsFrequency.DAILY,
        calendar_policy=CalendarPolicy.CALENDAR,
    )

    assert [value.isoformat() for value in business_df["date"].dt.date] == ["2026-04-10", "2026-04-13"]
    assert [value.isoformat() for value in market_df["date"].dt.date] == ["2026-04-10", "2026-04-13"]
    assert len(calendar_df) == 4


def test_detect_gaps_does_not_flag_weekends_under_business_calendar():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-10", "2026-04-13", "2026-04-15"]),
            "return_value": [Decimal("0.001"), Decimal("0.002"), Decimal("0.003")],
        }
    )

    business_gaps = returns_series_service.detect_gaps(
        df,
        frequency=ReturnsFrequency.DAILY,
        series_type="portfolio",
        calendar_policy=CalendarPolicy.BUSINESS,
    )
    calendar_gaps = returns_series_service.detect_gaps(
        df,
        frequency=ReturnsFrequency.DAILY,
        series_type="portfolio",
        calendar_policy=CalendarPolicy.CALENDAR,
    )

    assert [gap.gap_days for gap in business_gaps] == [1]
    assert [gap.gap_days for gap in calendar_gaps] == [2]


def test_strict_intersection_policy_aligns_selected_series():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-25", "2026-02-26"]),
            "return_value": [Decimal("0.0010"), Decimal("0.0020")],
        }
    )

    aligned_portfolio, aligned_benchmark, aligned_risk_free = returns_series_service._apply_strict_intersection_policy(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=None,
        missing_data_policy=MissingDataPolicy.STRICT_INTERSECTION,
    )

    assert list(aligned_portfolio["date"].dt.date) == [pd.Timestamp("2026-02-25").date()]
    assert aligned_benchmark is not None
    assert list(aligned_benchmark["date"].dt.date) == [pd.Timestamp("2026-02-25").date()]
    assert aligned_risk_free is None


def test_strict_intersection_policy_rejects_no_overlap():
    portfolio_df = pd.DataFrame({"date": pd.to_datetime(["2026-02-24"]), "return_value": [Decimal("0.0100")]})
    benchmark_df = pd.DataFrame({"date": pd.to_datetime(["2026-02-25"]), "return_value": [Decimal("0.0010")]})

    with pytest.raises(HTTPException) as exc:
        returns_series_service._apply_strict_intersection_policy(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
            risk_free_df=None,
            missing_data_policy=MissingDataPolicy.STRICT_INTERSECTION,
        )

    assert exc.value.status_code == 422


def test_selected_fill_method_aligns_optional_series_to_portfolio_dates():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200"), Decimal("0.0300")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-26"]),
            "return_value": [Decimal("0.0010"), Decimal("0.0030")],
        }
    )

    _, filled_benchmark, _ = returns_series_service._apply_selected_fill_method(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=None,
        fill_method=FillMethod.FORWARD_FILL,
    )

    assert filled_benchmark is not None
    assert list(filled_benchmark["return_value"]) == [Decimal("0.0010"), Decimal("0.0010"), Decimal("0.0030")]


@pytest.mark.asyncio
async def test_resolve_stateful_returns_series_benchmark_id_uses_assignment_when_missing():
    request = _build_stateful_request()

    class Service:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": "BMK_CORE"}

    benchmark_id = await returns_series_service._resolve_stateful_returns_series_benchmark_id(
        request=request,
        stateful_input_service=Service(),
        resolved_benchmark_id=None,
    )

    assert benchmark_id == "BMK_CORE"


@pytest.mark.asyncio
async def test_resolve_stateful_returns_series_benchmark_id_rejects_missing_assignment():
    request = _build_stateful_request()

    class Service:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 404, {}

    with pytest.raises(HTTPException) as exc:
        await returns_series_service._resolve_stateful_returns_series_benchmark_id(
            request=request,
            stateful_input_service=Service(),
            resolved_benchmark_id=None,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_stateful_returns_series_benchmark_id_rejects_invalid_payload():
    request = _build_stateful_request()

    class Service:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": None}

    with pytest.raises(HTTPException) as exc:
        await returns_series_service._resolve_stateful_returns_series_benchmark_id(
            request=request,
            stateful_input_service=Service(),
            resolved_benchmark_id=None,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_retrieve_stateful_returns_series_risk_free_uses_core_series():
    request = _build_stateful_request(
        reporting_currency="USD",
        series_selection={"include_portfolio": True, "include_benchmark": False, "include_risk_free": True},
    )
    resolved_window = returns_series_service.resolve_window(request)

    class Service:
        async def get_risk_free_series(self, **kwargs):  # noqa: ARG002
            return 200, {"points": [{"series_date": "2026-02-25", "value": "0.0001"}]}

    points, payload = await returns_series_service._retrieve_stateful_returns_series_risk_free(
        request=request,
        stateful_input_service=Service(),
        resolved_window=resolved_window,
    )

    assert points == [{"series_date": "2026-02-25", "value": "0.0001"}]
    assert payload == {"points": points}


@pytest.mark.asyncio
async def test_retrieve_stateful_returns_series_risk_free_requires_reporting_currency():
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": False, "include_risk_free": True},
    )
    resolved_window = returns_series_service.resolve_window(request)

    with pytest.raises(HTTPException) as exc:
        await returns_series_service._retrieve_stateful_returns_series_risk_free(
            request=request,
            stateful_input_service=object(),
            resolved_window=resolved_window,
        )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_retrieve_stateful_returns_series_risk_free_rejects_invalid_payload():
    request = _build_stateful_request(
        reporting_currency="USD",
        series_selection={"include_portfolio": True, "include_benchmark": False, "include_risk_free": True},
    )
    resolved_window = returns_series_service.resolve_window(request)

    class Service:
        async def get_risk_free_series(self, **kwargs):  # noqa: ARG002
            return 200, {"points": None}

    with pytest.raises(HTTPException) as exc:
        await returns_series_service._retrieve_stateful_returns_series_risk_free(
            request=request,
            stateful_input_service=Service(),
            resolved_window=resolved_window,
        )

    assert exc.value.status_code == 422


def _build_stateful_request(**overrides):
    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "P1",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
        "input_mode": "stateful",
        "stateful_input": {},
    }
    payload.update(overrides)
    return ReturnsSeriesRequest.model_validate(payload)


def _seed_execution(monkeypatch, tmp_path, request):
    store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    store.create_schema()
    monkeypatch.setattr(returns_series_service, "execution_registry", store)
    monkeypatch.setattr(stateful_input_service, "execution_registry", store)
    store.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id=request.portfolio_id,
        execution_mode="sync",
        requested_window={},
    )
    return store


@pytest.mark.asyncio
async def test_calculate_returns_series_requires_open_date(monkeypatch, tmp_path):
    request = _build_stateful_request()
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"}
            ]
        }

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )

    with pytest.raises(HTTPException) as exc:
        await returns_series_service.calculate_returns_series(request)
    assert exc.value.status_code == 422
    assert exc.value.detail["message"] == "Stateful source missing portfolio_open_date."


@pytest.mark.asyncio
async def test_calculate_returns_series_maps_assignment_source_unavailable(monkeypatch, tmp_path):
    request = _build_stateful_request()
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-23",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"}
            ],
        }

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 503, {"detail": "down"}

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)

    with pytest.raises(HTTPException) as exc:
        await returns_series_service.calculate_returns_series(request)
    assert exc.value.status_code == 503
    assert "Benchmark assignment source unavailable" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_calculate_returns_series_requires_benchmark_id_and_points(monkeypatch, tmp_path):
    request = _build_stateful_request(benchmark={"return_source": "vendor_series"})
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-23",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
                {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
            ],
        }

    async def _missing_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {}

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _missing_assignment
    )

    with pytest.raises(HTTPException) as exc_missing_id:
        await returns_series_service.calculate_returns_series(request)
    assert exc_missing_id.value.status_code == 422

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK"}

    async def _bad_points(self, **kwargs):  # noqa: ARG001
        return 200, {"bad": []}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _bad_points)

    with pytest.raises(HTTPException) as exc_bad_points:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bad_points.value.status_code == 422
    assert "benchmark series is empty" in exc_bad_points.value.detail["message"]


@pytest.mark.asyncio
async def test_calculate_returns_series_maps_benchmark_and_risk_free_errors(monkeypatch, tmp_path):
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        reporting_currency="USD",
        benchmark={"return_source": "vendor_series"},
    )
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-23",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
                {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
            ],
        }

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK"}

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)

    async def _benchmark_404(self, **kwargs):  # noqa: ARG001
        return 404, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_404)
    with pytest.raises(HTTPException) as exc_bmk_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_404.value.status_code == 404

    async def _benchmark_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_503)
    with pytest.raises(HTTPException) as exc_bmk_503:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_503.value.status_code == 503

    async def _benchmark_ok(self, **kwargs):  # noqa: ARG001
        return 200, {"points": [{"series_date": "2026-02-23", "benchmark_return": "0.01"}]}

    async def _risk_free_404(self, **kwargs):  # noqa: ARG001
        return 404, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_ok)
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_risk_free_series", _risk_free_404)
    with pytest.raises(HTTPException) as exc_rf_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_rf_404.value.status_code == 404

    async def _risk_free_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_risk_free_series", _risk_free_503)
    with pytest.raises(HTTPException) as exc_rf_503:
        await returns_series_service.calculate_returns_series(request)
    assert exc_rf_503.value.status_code == 503


@pytest.mark.asyncio
async def test_calculate_returns_series_handles_unexpected_exception_and_strict_intersection(monkeypatch, tmp_path):
    request = ReturnsSeriesRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
            "data_policy": {"missing_data_policy": "STRICT_INTERSECTION"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.01"},
                    {"date": "2026-02-24", "return_value": "0.02"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-24", "return_value": "0.03"},
                    {"date": "2026-02-25", "return_value": "0.04"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-24", "return_value": "0.001"},
                    {"date": "2026-02-25", "return_value": "0.001"},
                ],
            },
        }
    )
    store = _seed_execution(monkeypatch, tmp_path, request)

    response = await returns_series_service.calculate_returns_series(request)
    assert len(response.series.portfolio_returns) == 1
    assert len(response.series.benchmark_returns or []) == 1
    assert len(response.series.risk_free_returns or []) == 1

    async def _boom(_request):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(
        returns_series_service, "resample_returns", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    failing_request = ReturnsSeriesRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.01"},
                    {"date": "2026-02-24", "return_value": "0.02"},
                ]
            },
        }
    )
    store.create_execution(
        calculation_id=failing_request.calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="P1",
        execution_mode="sync",
        requested_window={},
    )
    with pytest.raises(RuntimeError, match="boom"):
        await returns_series_service.calculate_returns_series(failing_request)
    execution = store.get_execution(failing_request.calculation_id)
    assert execution is not None
    assert execution.status.value == "failed"


@pytest.mark.asyncio
async def test_calculate_returns_series_updates_stateful_identity_from_resolved_series(monkeypatch, tmp_path):
    request = _build_stateful_request(reporting_currency="USD")
    store = _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-20",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
                {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
                {"valuation_date": "2026-02-25", "beginning_market_value": "102", "ending_market_value": "103"},
            ],
        }

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_RESOLVED"}

    async def _build_benchmark(**kwargs):  # noqa: ARG001
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
                    component_return=0.0020,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-25",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.0030,
                ),
            ],
            benchmark_return_points=[],
            source_details={"benchmark_components": 1, "component_observations": 3, "benchmark_chunk_count": 1},
        )

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)
    monkeypatch.setattr(returns_series_service, "build_stateful_benchmark_input", _build_benchmark)

    initial_input_fingerprint, initial_calculation_hash = generate_canonical_hash(request, "returns-series-v1")

    response = await returns_series_service.calculate_returns_series(request)

    assert response.benchmark_context is not None
    assert response.benchmark_context.benchmark_id == "BMK_RESOLVED"
    assert response.benchmark_context.return_source.value == "calculated"

    resolved_payload = returns_series_service._build_stateful_resolved_returns_payload(
        request=request,
        resolved_window=response.resolved_window,
        portfolio_records=[point.model_dump(mode="json") for point in response.series.portfolio_returns],
        benchmark_records=[point.model_dump(mode="json") for point in (response.series.benchmark_returns or [])],
        risk_free_records=None,
        resolved_benchmark_id="BMK_RESOLVED",
        resolved_benchmark_return_source="calculated",
    )
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash(
        resolved_payload,
        "returns-series-v1",
    )

    assert response.provenance.input_fingerprint == expected_input_fingerprint
    assert response.provenance.calculation_hash == expected_calculation_hash
    assert response.provenance.input_fingerprint != initial_input_fingerprint
    assert response.provenance.calculation_hash != initial_calculation_hash

    execution = store.get_execution(request.calculation_id)
    assert execution is not None
    assert execution.input_fingerprint == expected_input_fingerprint
    assert execution.calculation_hash == expected_calculation_hash


@pytest.mark.asyncio
async def test_calculate_returns_series_uses_runtime_stateful_settings(monkeypatch, tmp_path):
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
        data_policy={"missing_data_policy": "ALLOW_PARTIAL"},
    )
    _seed_execution(monkeypatch, tmp_path, request)
    captured: dict[str, object] = {}

    class _FakeStatefulInputService:
        def __init__(self, *, core_service, portfolio_chunk_days, reference_chunk_days, max_concurrent_chunks):
            captured["core_init"] = {
                "base_url": getattr(core_service, "_base_url"),
                "timeout_seconds": getattr(core_service, "_timeout"),
                "max_retries": getattr(core_service, "_max_retries"),
                "retry_backoff_seconds": getattr(core_service, "_retry_backoff_seconds"),
            }
            captured["stateful_init"] = {
                "portfolio_chunk_days": portfolio_chunk_days,
                "reference_chunk_days": reference_chunk_days,
                "max_concurrent_chunks": max_concurrent_chunks,
            }

        async def get_portfolio_timeseries(self, **kwargs):
            return 200, {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"}
                ],
            }

    monkeypatch.setattr(
        returns_series_service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "CORE_CONTROL_PLANE_BASE_URL": "http://runtime-core-control",
                "CORE_QUERY_BASE_URL": "http://runtime-core",
                "resolved_core_control_plane_base_url": "http://runtime-core-control",
                "CORE_TIMEOUT_SECONDS": 17.0,
                "CORE_MAX_RETRIES": 5,
                "CORE_RETRY_BACKOFF_SECONDS": 1.5,
                "STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS": 13,
                "STATEFUL_INPUT_REFERENCE_CHUNK_DAYS": 29,
                "STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS": 7,
            },
        )(),
    )
    monkeypatch.setattr(portfolio_source_service, "StatefulInputService", _FakeStatefulInputService)
    monkeypatch.setattr(
        returns_series_service,
        "daily_ror_from_portfolio_timeseries",
        lambda **kwargs: __import__("pandas").DataFrame(
            {"date": __import__("pandas").to_datetime(["2026-02-23"]), "return_value": [0.01]}
        ),
    )

    response = await returns_series_service.calculate_returns_series(request)

    assert captured["core_init"] == {
        "base_url": "http://runtime-core-control",
        "timeout_seconds": 17.0,
        "max_retries": 5,
        "retry_backoff_seconds": 1.5,
    }
    assert captured["stateful_init"] == {
        "portfolio_chunk_days": 13,
        "reference_chunk_days": 29,
        "max_concurrent_chunks": 7,
    }
    assert len(response.series.portfolio_returns) == 1
