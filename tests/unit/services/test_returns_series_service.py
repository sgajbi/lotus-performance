from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pandas as pd
import pytest

from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkComponentObservation, BenchmarkReturnPoint
from app.models.returns_series import (
    CalendarPolicy,
    DataPolicy,
    FillMethod,
    InputMode,
    MetricBasis,
    MissingDataPolicy,
    ReturnPoint,
    ReturnsDiagnostics,
    ReturnsFrequency,
    ReturnsRelativePeriod,
    ReturnsSeriesRequest,
    ReturnsWindow,
    ReturnsWindowMode,
    SeriesSelection,
)
from app.services import portfolio_source_service, returns_series_service, stateful_input_service
from app.services.execution_registry import ExecutionRegistry
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from core.errors import APIError
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


def test_aligned_portfolio_benchmark_returns_df_requires_benchmark_and_overlap():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23"]),
            "return_value": [Decimal("0.0100")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24"]),
            "return_value": [Decimal("0.0010")],
        }
    )

    assert (
        returns_series_service._aligned_portfolio_benchmark_returns_df(
            portfolio_df=portfolio_df,
            benchmark_df=None,
        )
        is None
    )
    assert (
        returns_series_service._aligned_portfolio_benchmark_returns_df(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
        )
        is None
    )


def test_daily_return_percentage_to_ratio_uses_shared_numeric_fallback():
    assert returns_series_service._daily_return_percentage_to_ratio("1.25") == Decimal("0.0125")
    assert returns_series_service._daily_return_percentage_to_ratio("not-a-number") is None


def test_daily_ror_from_portfolio_timeseries_rejects_empty_engine_results(monkeypatch):
    class _FakePerformanceRequest:
        @staticmethod
        def model_validate(payload):
            return payload

    monkeypatch.setattr(returns_series_service, "PerformanceRequest", _FakePerformanceRequest)
    monkeypatch.setattr(
        returns_series_service,
        "portfolio_timeseries_to_valuation_points",
        lambda *, observations: [{"valuation_date": "2026-02-23"}],
    )
    monkeypatch.setattr(returns_series_service, "create_engine_config", lambda *args: object())
    monkeypatch.setattr(returns_series_service, "create_engine_dataframe", lambda points: pd.DataFrame(points))
    monkeypatch.setattr(returns_series_service, "run_calculations", lambda *args: (pd.DataFrame(), None))

    with pytest.raises(APIError) as exc:
        returns_series_service.daily_ror_from_portfolio_timeseries(
            observations=[{"valuation_date": "2026-02-23"}],
            performance_start_date=date(2026, 2, 23),
            resolved_window=returns_series_service.ResolvedWindow(
                start_date=date(2026, 2, 23),
                end_date=date(2026, 2, 24),
            ),
            metric_basis="NET",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["message"] == "No portfolio return observations in resolved window."


def test_daily_ror_from_portfolio_timeseries_rejects_invalid_engine_returns(monkeypatch):
    class _FakePerformanceRequest:
        @staticmethod
        def model_validate(payload):
            return payload

    daily_results_df = pd.DataFrame(
        {
            returns_series_service.PortfolioColumns.PERF_DATE.value: ["2026-02-23"],
            returns_series_service.PortfolioColumns.DAILY_ROR.value: ["not-a-number"],
        }
    )
    monkeypatch.setattr(returns_series_service, "PerformanceRequest", _FakePerformanceRequest)
    monkeypatch.setattr(
        returns_series_service,
        "portfolio_timeseries_to_valuation_points",
        lambda *, observations: [{"valuation_date": "2026-02-23"}],
    )
    monkeypatch.setattr(returns_series_service, "create_engine_config", lambda *args: object())
    monkeypatch.setattr(returns_series_service, "create_engine_dataframe", lambda points: pd.DataFrame(points))
    monkeypatch.setattr(returns_series_service, "run_calculations", lambda *args: (daily_results_df, None))

    with pytest.raises(APIError) as exc:
        returns_series_service.daily_ror_from_portfolio_timeseries(
            observations=[{"valuation_date": "2026-02-23"}],
            performance_start_date=date(2026, 2, 23),
            resolved_window=returns_series_service.ResolvedWindow(
                start_date=date(2026, 2, 23),
                end_date=date(2026, 2, 24),
            ),
            metric_basis="NET",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["message"] == "No valid portfolio return observations after normalization."


def test_to_dataframe_normalizes_mixed_date_like_return_points_to_timestamps():
    df = returns_series_service.to_dataframe(
        [
            ReturnPoint(date="2026-02-24", return_value=Decimal("0.002")),
            ReturnPoint(date=pd.Timestamp("2026-02-23T10:00:00Z").date(), return_value=Decimal("0.001")),
        ],
        series_type="portfolio",
    )

    assert [value.date().isoformat() for value in df["date"]] == ["2026-02-23", "2026-02-24"]


def test_to_dataframe_rejects_duplicate_dates_after_timestamp_normalization():
    points = [
        cast(ReturnPoint, SimpleNamespace(date="2026-02-23", return_value=Decimal("0.001"))),
        cast(ReturnPoint, SimpleNamespace(date=pd.Timestamp("2026-02-23"), return_value=Decimal("0.002"))),
    ]

    with pytest.raises(APIError) as exc:
        returns_series_service.to_dataframe(points, series_type="portfolio")

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == "portfolio series contains duplicate dates."


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


def test_benchmark_daily_returns_to_dataframe_rejects_empty_source():
    source_df = pd.DataFrame(columns=["date", "benchmark_return"])

    with pytest.raises(APIError) as exc:
        returns_series_service._benchmark_daily_returns_to_dataframe(source_df)

    assert exc.value.status_code == 422
    assert exc.value.detail["message"] == "Benchmark series is empty."


def test_benchmark_daily_returns_to_dataframe_rejects_duplicate_dates():
    source_df = pd.DataFrame(
        {
            "date": ["2026-02-23", "2026-02-23"],
            "benchmark_return": [Decimal("0.001"), Decimal("0.002")],
        }
    )

    with pytest.raises(APIError) as exc:
        returns_series_service._benchmark_daily_returns_to_dataframe(source_df)

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == "benchmark series contains duplicate dates."


def test_benchmark_daily_returns_to_dataframe_rejects_normalized_duplicate_dates():
    source_df = pd.DataFrame(
        {
            "date": ["2026-02-23", pd.Timestamp("2026-02-23")],
            "benchmark_return": [Decimal("0.001"), Decimal("0.002")],
        }
    )

    with pytest.raises(APIError) as exc:
        returns_series_service._benchmark_daily_returns_to_dataframe(source_df)

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == "benchmark series contains duplicate dates."


def test_period_start_resolves_calendar_trailing_inception_and_year_policies():
    as_of_date = date(2026, 6, 12)

    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.MTD, None) == date(2026, 6, 1)
    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.QTD, None) == date(2026, 4, 1)
    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.YTD, None) == date(2026, 1, 1)
    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.ONE_YEAR, None) == date(2025, 6, 13)
    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.THREE_YEAR, None) == date(2023, 6, 13)
    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.FIVE_YEAR, None) == date(2021, 6, 13)
    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.SI, None) == date(1900, 1, 1)
    assert returns_series_service.period_start(as_of_date, ReturnsRelativePeriod.YEAR, 2024) == date(2024, 1, 1)


def test_period_start_rejects_missing_year_and_unknown_period():
    with pytest.raises(ValueError, match="year is required when period=YEAR"):
        returns_series_service.period_start(date(2026, 6, 12), ReturnsRelativePeriod.YEAR, None)

    with pytest.raises(ValueError, match="Unsupported period: CUSTOM"):
        returns_series_service.period_start(
            date(2026, 6, 12),
            cast(ReturnsRelativePeriod, "CUSTOM"),
            None,
        )


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


def test_aligned_cumulative_portfolio_benchmark_returns_df_requires_benchmark_and_overlap():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23"]),
            "return_value": [Decimal("0.0100")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24"]),
            "return_value": [Decimal("0.0010")],
        }
    )

    assert (
        returns_series_service._aligned_cumulative_portfolio_benchmark_returns_df(
            portfolio_df=portfolio_df,
            benchmark_df=None,
        )
        is None
    )
    assert (
        returns_series_service._aligned_cumulative_portfolio_benchmark_returns_df(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
        )
        is None
    )


def test_aligned_cumulative_portfolio_benchmark_returns_df_rejects_empty_selected_series():
    portfolio_df = pd.DataFrame({"date": pd.to_datetime([]), "return_value": []})
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23"]),
            "return_value": [Decimal("0.0010")],
        }
    )

    assert (
        returns_series_service._aligned_cumulative_portfolio_benchmark_returns_df(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
        )
        is None
    )


def test_build_returns_series_point_outputs_emits_selected_point_families():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0050"), Decimal("0.0150")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0001"), Decimal("0.0002")],
        }
    )

    outputs = returns_series_service._build_returns_series_point_outputs(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=risk_free_df,
    )

    assert [str(point.return_value) for point in outputs.portfolio_return_points] == [
        "0.010000000000",
        "0.020000000000",
    ]
    assert outputs.benchmark_return_points is not None
    assert [str(point.return_value) for point in outputs.benchmark_return_points] == [
        "0.005000000000",
        "0.015000000000",
    ]
    assert outputs.risk_free_return_points is not None
    assert [str(point.return_value) for point in outputs.risk_free_return_points] == [
        "0.000100000000",
        "0.000200000000",
    ]
    assert outputs.active_return_points is not None
    assert [str(point.return_value) for point in outputs.active_return_points] == ["0.005000000000", "0.005000000000"]
    assert outputs.cumulative_active_return_points is not None
    assert [str(point.return_value) for point in outputs.cumulative_active_return_points] == [
        "0.005000000000",
        "0.010125000000",
    ]


def test_build_returns_series_point_outputs_omits_unselected_optional_families():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23"]),
            "return_value": [Decimal("0.0100")],
        }
    )

    outputs = returns_series_service._build_returns_series_point_outputs(
        portfolio_df=portfolio_df,
        benchmark_df=None,
        risk_free_df=None,
    )

    assert len(outputs.portfolio_return_points) == 1
    assert outputs.benchmark_return_points is None
    assert outputs.cumulative_benchmark_return_points is None
    assert outputs.risk_free_return_points is None
    assert outputs.cumulative_risk_free_return_points is None
    assert outputs.active_return_points is None
    assert outputs.cumulative_active_return_points is None


def test_final_returns_series_identity_preserves_stateless_context_identity():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-24",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                ],
            },
        }
    )
    context = returns_series_service._ReturnsSeriesExecutionContext(
        request=request,
        resolved_window=returns_series_service.resolve_window(request),
        effective_input_mode=InputMode.STATELESS,
        input_fingerprint="fingerprint-1",
        calculation_hash="hash-1",
        resolved_benchmark_id=None,
        resolved_benchmark_return_source=BenchmarkReturnSource.CALCULATED,
    )
    point_outputs = returns_series_service._ReturnsSeriesPointOutputs(
        portfolio_return_points=[ReturnPoint(date=date(2026, 2, 23), return_value=Decimal("0.0100"))],
        cumulative_portfolio_return_points=None,
        benchmark_return_points=None,
        cumulative_benchmark_return_points=None,
        risk_free_return_points=None,
        cumulative_risk_free_return_points=None,
        active_return_points=None,
        cumulative_active_return_points=None,
    )

    identity = returns_series_service._final_returns_series_identity(
        request=request,
        context=context,
        point_outputs=point_outputs,
    )

    assert identity.input_fingerprint == "fingerprint-1"
    assert identity.calculation_hash == "hash-1"


def test_final_returns_series_identity_refreshes_stateful_identity(monkeypatch):
    request = _build_stateful_request()
    point_outputs = returns_series_service._ReturnsSeriesPointOutputs(
        portfolio_return_points=[ReturnPoint(date=date(2026, 2, 23), return_value=Decimal("0.0100"))],
        cumulative_portfolio_return_points=None,
        benchmark_return_points=[ReturnPoint(date=date(2026, 2, 23), return_value=Decimal("0.0010"))],
        cumulative_benchmark_return_points=None,
        risk_free_return_points=None,
        cumulative_risk_free_return_points=None,
        active_return_points=None,
        cumulative_active_return_points=None,
    )
    context = returns_series_service._ReturnsSeriesExecutionContext(
        request=request,
        resolved_window=returns_series_service.resolve_window(request),
        effective_input_mode=InputMode.STATEFUL,
        input_fingerprint="initial-fingerprint",
        calculation_hash="initial-hash",
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )
    captured: dict[str, object] = {}

    def _fake_update_resolved_stateful_returns_identity(**kwargs):
        captured.update(kwargs)
        return returns_series_service._ReturnsSeriesIdentity(
            input_fingerprint="resolved-fingerprint",
            calculation_hash="resolved-hash",
        )

    monkeypatch.setattr(
        returns_series_service,
        "_update_resolved_stateful_returns_identity",
        _fake_update_resolved_stateful_returns_identity,
    )

    identity = returns_series_service._final_returns_series_identity(
        request=request,
        context=context,
        point_outputs=point_outputs,
    )

    assert identity.input_fingerprint == "resolved-fingerprint"
    assert identity.calculation_hash == "resolved-hash"
    assert captured == {
        "request": request,
        "resolved_window": context.resolved_window,
        "point_outputs": point_outputs,
        "resolved_benchmark_id": "BMK_1",
        "resolved_benchmark_return_source": BenchmarkReturnSource.VENDOR_SERIES,
    }


def test_build_returns_series_response_preserves_context_provenance_and_series_payload():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-24",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                    {"date": "2026-02-24", "return_value": "0.0200"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-23", "return_value": "0.0050"},
                    {"date": "2026-02-24", "return_value": "0.0150"},
                ],
            },
        }
    )
    resolved_window = returns_series_service.resolve_window(request)
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0050"), Decimal("0.0150")],
        }
    )
    point_outputs = returns_series_service._build_returns_series_point_outputs(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=None,
    )
    diagnostics_result = returns_series_service._build_returns_series_diagnostics(
        request=request,
        resolved_window=resolved_window,
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=None,
    )

    response = returns_series_service._build_returns_series_response(
        request=request,
        resolved_window=resolved_window,
        point_outputs=point_outputs,
        diagnostics_result=diagnostics_result,
        effective_input_mode=InputMode.STATELESS,
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )

    assert response.benchmark_context is not None
    assert response.benchmark_context.benchmark_id == "BMK_1"
    assert response.benchmark_context.return_source == BenchmarkReturnSource.VENDOR_SERIES
    assert response.provenance.input_fingerprint == "input-fingerprint"
    assert response.provenance.calculation_hash == "calculation-hash"
    assert response.provenance.input_mode == InputMode.STATELESS
    assert response.series.portfolio_returns == point_outputs.portfolio_return_points
    assert response.series.benchmark_returns == point_outputs.benchmark_return_points
    assert response.diagnostics == diagnostics_result.diagnostics


def test_normalize_returns_series_execution_frames_applies_request_policy():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
            "data_policy": {"missing_data_policy": "STRICT_INTERSECTION", "fill_method": "ZERO_FILL"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [{"date": "2026-02-23", "return_value": "0.0100"}],
                "benchmark_returns": [{"date": "2026-02-23", "return_value": "0.0050"}],
                "risk_free_returns": [{"date": "2026-02-23", "return_value": "0.0001"}],
            },
        }
    )
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200"), Decimal("0.0300")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0150"), Decimal("0.0300")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0001"), Decimal("0.0002")],
        }
    )

    normalized_frames = returns_series_service._normalize_returns_series_execution_frames(
        request=request,
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=risk_free_df,
    )

    assert list(normalized_frames.portfolio_df["date"].dt.date) == [date(2026, 2, 24)]
    assert normalized_frames.benchmark_df is not None
    assert list(normalized_frames.benchmark_df["date"].dt.date) == [date(2026, 2, 24)]
    assert normalized_frames.risk_free_df is not None
    assert list(normalized_frames.risk_free_df["date"].dt.date) == [date(2026, 2, 24)]


def test_build_returns_series_execution_result_preserves_policy_response_and_stage_details():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
            "data_policy": {"missing_data_policy": "STRICT_INTERSECTION"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [{"date": "2026-02-23", "return_value": "0.0100"}],
                "benchmark_returns": [{"date": "2026-02-23", "return_value": "0.0050"}],
                "risk_free_returns": [{"date": "2026-02-23", "return_value": "0.0001"}],
            },
        }
    )
    context = returns_series_service._ReturnsSeriesExecutionContext(
        request=request,
        resolved_window=returns_series_service.resolve_window(request),
        effective_input_mode=InputMode.STATELESS,
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0150"), Decimal("0.0300")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0002"), Decimal("0.0003")],
        }
    )

    result = returns_series_service._build_returns_series_execution_result(
        context=context,
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=risk_free_df,
    )

    response = result.response
    assert result.stage_details == {"requested_points": 3, "returned_points": 1}
    assert [point.date for point in response.series.portfolio_returns] == [date(2026, 2, 24)]
    assert response.series.benchmark_returns is not None
    assert [str(point.return_value) for point in response.series.benchmark_returns] == ["0.015000000000"]
    assert response.series.risk_free_returns is not None
    assert [str(point.return_value) for point in response.series.risk_free_returns] == ["0.000200000000"]
    assert response.benchmark_context is not None
    assert response.benchmark_context.benchmark_id == "BMK_1"
    assert response.benchmark_context.return_source == BenchmarkReturnSource.VENDOR_SERIES
    assert response.provenance.input_fingerprint == "input-fingerprint"
    assert response.provenance.calculation_hash == "calculation-hash"
    assert response.diagnostics.coverage.returned_points == 1


def test_build_returns_series_execution_result_marks_filled_side_source_stale():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
            "data_policy": {"missing_data_policy": "ALLOW_PARTIAL", "fill_method": "FORWARD_FILL"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [{"date": "2026-02-25", "return_value": "0.0200"}],
                "benchmark_returns": [{"date": "2026-02-24", "return_value": "0.0010"}],
            },
        }
    )
    context = returns_series_service._ReturnsSeriesExecutionContext(
        request=request,
        resolved_window=returns_series_service.resolve_window(request),
        effective_input_mode=InputMode.STATELESS,
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0150"), Decimal("0.0200")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0010"), Decimal("0.0020")],
        }
    )

    result = returns_series_service._build_returns_series_execution_result(
        context=context,
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=None,
    )

    assert result.response.series.benchmark_returns is not None
    assert [point.date for point in result.response.series.benchmark_returns] == [
        date(2026, 2, 23),
        date(2026, 2, 24),
        date(2026, 2, 25),
    ]
    assert result.response.diagnostics.freshness == "stale"


def test_returns_series_benchmark_context_requires_id_and_source():
    context = returns_series_service._returns_series_benchmark_context(
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )

    assert context is not None
    assert context.benchmark_id == "BMK_1"
    assert context.return_source == BenchmarkReturnSource.VENDOR_SERIES
    assert (
        returns_series_service._returns_series_benchmark_context(
            resolved_benchmark_id=None,
            resolved_benchmark_return_source=BenchmarkReturnSource.VENDOR_SERIES,
        )
        is None
    )
    assert (
        returns_series_service._returns_series_benchmark_context(
            resolved_benchmark_id="BMK_1",
            resolved_benchmark_return_source=None,
        )
        is None
    )


def test_requested_returns_series_execution_context_uses_stateful_benchmark_defaults():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-24",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
            "input_mode": "stateful",
            "benchmark": {"benchmark_id": "BMK_REQUESTED", "return_source": "vendor_series"},
            "stateful_input": {},
        }
    )
    expected_fingerprint, expected_hash = generate_canonical_hash(request, "returns-series-v1")

    context = returns_series_service._requested_returns_series_execution_context(
        request=request,
        source_input_mode=None,
        resolved_benchmark_id_override=None,
        resolved_benchmark_return_source_override=None,
    )

    assert context.request is request
    assert context.resolved_window.start_date.isoformat() == "2026-02-23"
    assert context.resolved_window.end_date.isoformat() == "2026-02-24"
    assert context.effective_input_mode == InputMode.STATEFUL
    assert context.input_fingerprint == expected_fingerprint
    assert context.calculation_hash == expected_hash
    assert context.resolved_benchmark_id == "BMK_REQUESTED"
    assert context.resolved_benchmark_return_source == BenchmarkReturnSource.VENDOR_SERIES


@pytest.mark.asyncio
async def test_resolve_returns_series_execution_context_preserves_stateless_overrides():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-24",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                    {"date": "2026-02-24", "return_value": "0.0200"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-23", "return_value": "0.0050"},
                    {"date": "2026-02-24", "return_value": "0.0150"},
                ],
            },
        }
    )
    expected_fingerprint, expected_hash = generate_canonical_hash(request, "returns-series-v1")

    context = await returns_series_service._resolve_returns_series_execution_context(
        request=request,
        source_input_mode=InputMode.STATEFUL,
        resolved_benchmark_id_override="BMK_RESOLVED",
        resolved_benchmark_return_source_override="vendor_series",
    )

    assert context.request is request
    assert context.resolved_window.start_date.isoformat() == "2026-02-23"
    assert context.resolved_window.end_date.isoformat() == "2026-02-24"
    assert context.effective_input_mode == InputMode.STATEFUL
    assert context.input_fingerprint == expected_fingerprint
    assert context.calculation_hash == expected_hash
    assert context.resolved_benchmark_id == "BMK_RESOLVED"
    assert context.resolved_benchmark_return_source == BenchmarkReturnSource.VENDOR_SERIES


def test_build_returns_series_diagnostics_reports_coverage_gaps_and_market_warning():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-26",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-26"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                    {"date": "2026-02-25", "return_value": "0.0200"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-23", "return_value": "0.0010"},
                    {"date": "2026-02-26", "return_value": "0.0020"},
                ],
            },
            "data_policy": {"calendar_policy": "MARKET", "missing_data_policy": "ALLOW_PARTIAL"},
        }
    )
    resolved_window = returns_series_service.resolve_window(request)
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-25"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-26"]),
            "return_value": [Decimal("0.0010"), Decimal("0.0020")],
        }
    )

    result = returns_series_service._build_returns_series_diagnostics(
        request=request,
        resolved_window=resolved_window,
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=None,
    )

    assert result.requested_points == 4
    assert result.returned_points == 2
    assert result.diagnostics.coverage.missing_points == 2
    assert result.diagnostics.freshness == "stale"
    assert result.diagnostics.warnings == ["MARKET calendar policy currently uses business-day approximation."]
    assert {gap.series_type for gap in result.diagnostics.gaps} == {"portfolio", "benchmark"}


def test_returns_series_freshness_marks_stale_source_warnings() -> None:
    assert (
        returns_series_service._returns_series_freshness(
            warnings=["stale benchmark observation retained by source policy"]
        )
        == "stale"
    )
    assert (
        returns_series_service._returns_series_freshness(
            warnings=["MARKET calendar policy currently uses business-day approximation."]
        )
        == "current"
    )


def test_returns_series_freshness_uses_last_required_business_date() -> None:
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-04-12",
            "window": {"mode": "EXPLICIT", "from_date": "2026-04-10", "to_date": "2026-04-12"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "data_policy": {"calendar_policy": "BUSINESS"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [{"date": "2026-04-10", "return_value": "0.0100"}],
            },
        }
    )
    resolved_window = returns_series_service.resolve_window(request)
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-10"]),
            "return_value": [Decimal("0.0100")],
        }
    )

    result = returns_series_service._build_returns_series_diagnostics(
        request=request,
        resolved_window=resolved_window,
        portfolio_df=portfolio_df,
        benchmark_df=None,
        risk_free_df=None,
    )

    assert result.requested_points == 1
    assert result.diagnostics.freshness == "current"


@pytest.mark.asyncio
async def test_calculate_returns_series_uses_raw_source_dates_for_weekly_freshness(
    monkeypatch,
    tmp_path,
) -> None:
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-04-10",
            "window": {"mode": "EXPLICIT", "from_date": "2026-04-06", "to_date": "2026-04-10"},
            "frequency": "WEEKLY",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "data_policy": {"missing_data_policy": "ALLOW_PARTIAL"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [{"date": "2026-04-06", "return_value": "0.0100"}],
            },
        }
    )
    _seed_execution(monkeypatch, tmp_path, request)

    result = await returns_series_service._calculate_returns_series(  # noqa: SLF001
        request,
        source_input_mode=InputMode.STATELESS,
        resolved_benchmark_id_override=None,
        resolved_benchmark_return_source_override=None,
    )

    assert [point.date for point in result.series.portfolio_returns] == [date(2026, 4, 10)]
    assert result.diagnostics.freshness == "stale"


def test_returns_diagnostics_accepts_legacy_payload_without_freshness() -> None:
    diagnostics = ReturnsDiagnostics.model_validate(
        {
            "coverage": {
                "requested_points": 2,
                "returned_points": 2,
                "missing_points": 0,
                "coverage_ratio": "1",
            },
            "gaps": [],
            "policy_applied": {},
            "risk_free_source_quality": None,
            "warnings": [],
        }
    )

    assert diagnostics.freshness == "current"


def test_build_returns_series_diagnostics_reports_stateless_risk_free_source_quality():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-24",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": True},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                    {"date": "2026-02-24", "return_value": "0.0200"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-23", "return_value": "0.0001"},
                    {"date": "2026-02-24", "return_value": "0.0002"},
                ],
            },
        }
    )
    resolved_window = returns_series_service.resolve_window(request)
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-23", "2026-02-24"]),
            "return_value": [Decimal("0.0001"), Decimal("0.0002")],
        }
    )

    result = returns_series_service._build_returns_series_diagnostics(
        request=request,
        resolved_window=resolved_window,
        portfolio_df=portfolio_df,
        benchmark_df=None,
        risk_free_df=risk_free_df,
    )

    assert result.diagnostics.risk_free_source_quality is not None
    assert result.diagnostics.risk_free_source_quality.raw_points == 2
    assert result.diagnostics.risk_free_source_quality.normalized_points == 2
    assert result.diagnostics.risk_free_source_quality.skipped_points == 0


def test_returns_series_gaps_includes_selected_risk_free_series():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-27"]),
            "return_value": [Decimal("0.0001"), Decimal("0.0003")],
        }
    )

    gaps = returns_series_service._returns_series_gaps(
        portfolio_df=portfolio_df,
        benchmark_df=None,
        risk_free_df=risk_free_df,
        frequency=ReturnsFrequency.DAILY,
        calendar_policy=CalendarPolicy.CALENDAR,
    )

    assert [(gap.series_type, gap.from_date, gap.to_date, gap.gap_days) for gap in gaps] == [
        ("risk_free", date(2026, 2, 24), date(2026, 2, 27), 2)
    ]


def test_build_returns_series_diagnostics_enforces_fail_fast_missing_points():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-26",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-26"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-24", "return_value": "0.0100"},
                ],
            },
            "data_policy": {"missing_data_policy": "FAIL_FAST"},
        }
    )
    resolved_window = returns_series_service.resolve_window(request)
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24"]),
            "return_value": [Decimal("0.0100")],
        }
    )

    with pytest.raises(APIError, match="Missing 2 required points under FAIL_FAST policy"):
        returns_series_service._build_returns_series_diagnostics(
            request=request,
            resolved_window=resolved_window,
            portfolio_df=portfolio_df,
            benchmark_df=None,
            risk_free_df=None,
        )


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


def test_risk_free_return_value_from_source_normalizes_annualized_and_period_returns():
    assert returns_series_service._risk_free_return_value_from_source(
        {
            "value": "0.036",
            "value_convention": "annualized_rate",
            "day_count_convention": "ACT_360",
        }
    ) == Decimal("0.0001")
    assert returns_series_service._risk_free_return_value_from_source(
        {
            "value": "0.036",
            "value_convention": "annualized_rate",
            "day_count_convention": "unknown",
        }
    ) == Decimal("0.0001")
    assert returns_series_service._risk_free_return_value_from_source({"value": "0.0002"}) == Decimal("0.0002")


def test_risk_free_return_value_from_source_rejects_missing_or_invalid_values():
    assert returns_series_service._risk_free_return_value_from_source({}) is None
    assert returns_series_service._risk_free_return_value_from_source({"value": "not-a-decimal"}) is None


def test_risk_free_points_to_dataframe_skips_malformed_points():
    risk_free_df = returns_series_service.risk_free_points_to_dataframe(
        points=[
            {"series_date": "2026-04-10", "value": "0.0001"},
            {"series_date": "not-a-date", "value": "0.0002"},
            {"series_date": "2026-04-11"},
            {"value": "0.0003"},
            {"series_date": "2026-04-12", "value": "not-a-decimal"},
        ]
    )

    assert [value.date().isoformat() for value in risk_free_df["date"]] == ["2026-04-10"]
    assert [str(value) for value in risk_free_df["return_value"]] == ["0.0001"]


def test_risk_free_source_quality_from_points_reports_skipped_malformed_rows():
    quality = returns_series_service.risk_free_source_quality_from_points(
        [
            {"series_date": "2026-04-10", "value": "0.0001"},
            {"series_date": "not-a-date", "value": "0.0002"},
            {"series_date": "2026-04-11"},
            {"value": "0.0003"},
        ]
    )

    assert quality is not None
    assert quality.raw_points == 4
    assert quality.normalized_points == 1
    assert quality.skipped_points == 3


def test_risk_free_points_to_dataframe_rejects_duplicate_dates():
    with pytest.raises(APIError) as exc:
        returns_series_service.risk_free_points_to_dataframe(
            points=[
                {"series_date": "2026-04-10", "value": "0.0001"},
                {"series_date": "2026-04-10", "value": "0.0002"},
            ]
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == "risk_free series contains duplicate dates."


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


def test_detect_gaps_applies_weekly_interval_threshold():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-03", "2026-04-11", "2026-04-20"]),
            "return_value": [Decimal("0.001"), Decimal("0.002"), Decimal("0.003")],
        }
    )

    gaps = returns_series_service.detect_gaps(
        df,
        frequency=ReturnsFrequency.WEEKLY,
        series_type="benchmark",
    )

    assert [(gap.from_date, gap.to_date, gap.gap_days) for gap in gaps] == [(date(2026, 4, 11), date(2026, 4, 20), 8)]


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


def test_strict_intersection_policy_includes_risk_free_dates():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200"), Decimal("0.0300")],
        }
    )
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25"]),
            "return_value": [Decimal("0.0010"), Decimal("0.0020")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-25", "2026-02-26"]),
            "return_value": [Decimal("0.0001"), Decimal("0.0002")],
        }
    )

    aligned_portfolio, aligned_benchmark, aligned_risk_free = returns_series_service._apply_strict_intersection_policy(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=risk_free_df,
        missing_data_policy=MissingDataPolicy.STRICT_INTERSECTION,
    )

    assert list(aligned_portfolio["date"].dt.date) == [pd.Timestamp("2026-02-25").date()]
    assert aligned_benchmark is not None
    assert list(aligned_benchmark["date"].dt.date) == [pd.Timestamp("2026-02-25").date()]
    assert aligned_risk_free is not None
    assert list(aligned_risk_free["date"].dt.date) == [pd.Timestamp("2026-02-25").date()]


def test_strict_intersection_policy_allows_unselected_benchmark():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200"), Decimal("0.0300")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-25", "2026-02-26"]),
            "return_value": [Decimal("0.0001"), Decimal("0.0002")],
        }
    )

    aligned_portfolio, aligned_benchmark, aligned_risk_free = returns_series_service._apply_strict_intersection_policy(
        portfolio_df=portfolio_df,
        benchmark_df=None,
        risk_free_df=risk_free_df,
        missing_data_policy=MissingDataPolicy.STRICT_INTERSECTION,
    )

    assert list(aligned_portfolio["date"].dt.date) == [
        pd.Timestamp("2026-02-25").date(),
        pd.Timestamp("2026-02-26").date(),
    ]
    assert aligned_benchmark is None
    assert aligned_risk_free is not None
    assert list(aligned_risk_free["date"].dt.date) == [
        pd.Timestamp("2026-02-25").date(),
        pd.Timestamp("2026-02-26").date(),
    ]


def test_strict_intersection_policy_rejects_no_overlap():
    portfolio_df = pd.DataFrame({"date": pd.to_datetime(["2026-02-24"]), "return_value": [Decimal("0.0100")]})
    benchmark_df = pd.DataFrame({"date": pd.to_datetime(["2026-02-25"]), "return_value": [Decimal("0.0010")]})

    with pytest.raises(APIError) as exc:
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


def test_selected_fill_method_zero_fills_risk_free_to_portfolio_dates():
    portfolio_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26"]),
            "return_value": [Decimal("0.0100"), Decimal("0.0200"), Decimal("0.0300")],
        }
    )
    risk_free_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24", "2026-02-26"]),
            "return_value": [Decimal("0.0001"), Decimal("0.0003")],
        }
    )

    _, filled_benchmark, filled_risk_free = returns_series_service._apply_selected_fill_method(
        portfolio_df=portfolio_df,
        benchmark_df=None,
        risk_free_df=risk_free_df,
        fill_method=FillMethod.ZERO_FILL,
    )

    assert filled_benchmark is None
    assert filled_risk_free is not None
    assert list(filled_risk_free["return_value"]) == [Decimal("0.0001"), 0.0, Decimal("0.0003")]


def test_prepare_stateless_returns_series_dataframes_respects_selected_series():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-26",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-26"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-24", "return_value": "0.0100"},
                    {"date": "2026-02-25", "return_value": "0.0200"},
                    {"date": "2026-02-26", "return_value": "0.0300"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-24", "return_value": "0.0010"},
                    {"date": "2026-02-25", "return_value": "0.0020"},
                    {"date": "2026-02-26", "return_value": "0.0030"},
                ],
            },
        }
    )
    resolved_window = returns_series_service.resolve_window(request)

    portfolio_df, benchmark_df, risk_free_df = returns_series_service._prepare_stateless_returns_series_dataframes(
        request=request,
        resolved_window=resolved_window,
    )

    assert list(portfolio_df["return_value"]) == [Decimal("0.0100"), Decimal("0.0200"), Decimal("0.0300")]
    assert benchmark_df is not None
    assert list(benchmark_df["return_value"]) == [Decimal("0.0010"), Decimal("0.0020"), Decimal("0.0030")]
    assert risk_free_df is None


def test_optional_stateless_returns_series_dataframe_builds_only_selected_series():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-26",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-26"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [{"date": "2026-02-24", "return_value": "0.0100"}],
            },
        }
    )
    resolved_window = returns_series_service.resolve_window(request)
    points = [ReturnPoint(date=date(2026, 2, 24), return_value=Decimal("0.0010"))]

    unselected_df = returns_series_service._optional_stateless_returns_series_dataframe(
        selected=False,
        points=points,
        series_type="benchmark",
        request=request,
        resolved_window=resolved_window,
    )
    selected_df = returns_series_service._optional_stateless_returns_series_dataframe(
        selected=True,
        points=points,
        series_type="benchmark",
        request=request,
        resolved_window=resolved_window,
    )

    assert unselected_df is None
    assert selected_df is not None
    assert list(selected_df["return_value"]) == [Decimal("0.0010")]


def test_prepare_stateless_returns_series_dataframes_requires_stateless_input():
    request = ReturnsSeriesRequest.model_construct(
        portfolio_id="P1",
        as_of_date=pd.Timestamp("2026-02-26").date(),
        window=ReturnsWindow.model_construct(
            mode=ReturnsWindowMode.EXPLICIT,
            from_date=pd.Timestamp("2026-02-24").date(),
            to_date=pd.Timestamp("2026-02-26").date(),
        ),
        frequency=ReturnsFrequency.DAILY,
        metric_basis=MetricBasis.NET,
        reporting_currency=None,
        series_selection=SeriesSelection(),
        benchmark=None,
        risk_free=None,
        data_policy=DataPolicy(),
        input_mode=InputMode.STATELESS,
        stateless_input=None,
        stateful_input=None,
    )
    resolved_window = returns_series_service.resolve_window(request)

    with pytest.raises(APIError) as exc:
        returns_series_service._prepare_stateless_returns_series_dataframes(
            request=request,
            resolved_window=resolved_window,
        )

    assert exc.value.status_code == 400


def test_build_stateful_returns_series_frames_normalizes_vendor_benchmark_and_risk_free_points():
    request = _build_stateful_request(
        reporting_currency="USD",
        series_selection={"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
    )
    resolved_window = returns_series_service.resolve_window(request)

    frames = returns_series_service._build_stateful_returns_series_frames(
        request=request,
        resolved_window=resolved_window,
        observations=[
            {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
            {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
            {"valuation_date": "2026-02-25", "beginning_market_value": "102", "ending_market_value": "103"},
        ],
        portfolio_performance_start_date=pd.Timestamp("2026-02-23").date(),
        benchmark_points=[
            {"series_date": "2026-02-23", "benchmark_return": "0.001"},
            {"series_date": "2026-02-25", "benchmark_return": "0.003"},
        ],
        benchmark_df=None,
        risk_free_points=[
            {"series_date": "2026-02-24", "value": "0.0001"},
            {"series_date": "2026-02-25", "value": "0.0002"},
        ],
    )

    assert not frames.portfolio_df.empty
    assert frames.benchmark_df is not None
    assert [value.date().isoformat() for value in frames.benchmark_df["date"]] == ["2026-02-23", "2026-02-25"]
    assert [str(value) for value in frames.benchmark_df["return_value"]] == ["0.001", "0.003"]
    assert frames.risk_free_df is not None
    assert [value.date().isoformat() for value in frames.risk_free_df["date"]] == ["2026-02-24", "2026-02-25"]
    assert [str(value) for value in frames.risk_free_df["return_value"]] == ["0.0001", "0.0002"]


def test_build_stateful_returns_series_frames_preserves_calculated_benchmark_frame():
    request = _build_stateful_request()
    resolved_window = returns_series_service.resolve_window(request)
    benchmark_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-24"]),
            "return_value": [Decimal("0.001")],
        }
    )

    frames = returns_series_service._build_stateful_returns_series_frames(
        request=request,
        resolved_window=resolved_window,
        observations=[
            {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
            {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
        ],
        portfolio_performance_start_date=pd.Timestamp("2026-02-23").date(),
        benchmark_points=None,
        benchmark_df=benchmark_df,
        risk_free_points=None,
    )

    assert frames.benchmark_df is benchmark_df
    assert frames.risk_free_df is None


def test_stateful_returns_retrieval_stage_details_preserve_count_policy():
    portfolio_source = returns_series_service.StatefulPortfolioInput(
        performance_start_date=pd.Timestamp("2026-02-23").date(),
        observations=[{"valuation_date": "2026-02-23"}, {"valuation_date": "2026-02-24"}],
        retrieval_metadata=stateful_input_service.RetrievalMetadata(chunk_count=2, page_count=3),
    )
    benchmark_resolution = returns_series_service._StatefulBenchmarkResolution(
        benchmark_id="BMK1",
        benchmark_points=[{"series_date": "2026-02-23"}, {"series_date": "2026-02-24"}],
        benchmark_df=None,
        benchmark_source_details={"benchmark_chunk_count": 4, "benchmark_page_count": 5},
        benchmark_work_units=6,
    )

    details = returns_series_service._stateful_returns_retrieval_stage_details(
        observations=portfolio_source.observations,
        portfolio_source=portfolio_source,
        benchmark_resolution=benchmark_resolution,
        risk_free_points=[{"date": "2026-02-23"}],
        risk_free_payload={"retrieval_metadata": {"chunk_count": "7", "page_count": 8}},
    )

    assert details == {
        "portfolio_observations": 2,
        "benchmark_points": 2,
        "benchmark_work_units": 6,
        "risk_free_points": 1,
        "portfolio_chunk_count": 2,
        "portfolio_page_count": 3,
        "benchmark_chunk_count": 4,
        "benchmark_page_count": 5,
        "risk_free_chunk_count": 7,
    }


def test_stateful_returns_normalization_stage_details_reports_selected_frame_counts():
    portfolio_df = pd.DataFrame({"date": pd.to_datetime(["2026-02-24", "2026-02-25"])})
    benchmark_df = pd.DataFrame({"date": pd.to_datetime(["2026-02-24"])})
    risk_free_df = pd.DataFrame({"date": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26"])})

    details = returns_series_service._stateful_returns_normalization_stage_details(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=risk_free_df,
    )

    assert details == {
        "portfolio_points": 2,
        "benchmark_points": 1,
        "risk_free_points": 3,
    }


def test_build_resolved_stateful_returns_series_request_completes_normalization_stage(monkeypatch, tmp_path):
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": False, "include_risk_free": False}
    )
    store = _seed_execution(monkeypatch, tmp_path, request)
    store.start_stage(request.calculation_id, returns_series_service.EXECUTION_STAGE_NORMALIZATION)
    resolved_window = returns_series_service.resolve_window(request)
    observations = [
        {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
        {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
        {"valuation_date": "2026-02-25", "beginning_market_value": "102", "ending_market_value": "103"},
    ]

    result = returns_series_service._build_resolved_stateful_returns_series_request(
        request=request,
        resolved_window=resolved_window,
        observations=observations,
        portfolio_performance_start_date=pd.Timestamp("2026-02-23").date(),
        benchmark_resolution=returns_series_service._StatefulBenchmarkResolution(
            benchmark_id=None,
            benchmark_points=None,
            benchmark_df=None,
            benchmark_source_details={},
            benchmark_work_units=0,
        ),
        risk_free_points=None,
        resolved_benchmark_id=None,
        resolved_benchmark_return_source=BenchmarkReturnSource.CALCULATED,
    )

    assert result.request.input_mode == InputMode.STATELESS
    assert result.request.stateless_input is not None
    assert len(result.request.stateless_input.portfolio_returns) == 3
    assert result.identity_payload["input_mode"] == InputMode.STATELESS.value
    assert result.identity_payload["stateless_input"]["benchmark_returns"] is None
    execution = store.get_execution(request.calculation_id)
    assert execution is not None
    stages = {stage.stage_name: stage for stage in execution.stages}
    assert stages[returns_series_service.EXECUTION_STAGE_NORMALIZATION].status.value == "complete"
    assert stages[returns_series_service.EXECUTION_STAGE_NORMALIZATION].details == {
        "portfolio_points": 3,
        "benchmark_points": 0,
        "risk_free_points": 0,
    }


def test_resolved_stateful_returns_series_request_payload_promotes_stateless_input():
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        risk_free={"source": "SOFR"},
    )
    identity_payload = {
        "stateless_input": {
            "portfolio_returns": [{"date": "2026-02-23", "return": 0.01}],
            "benchmark_returns": [{"date": "2026-02-23", "return": 0.008}],
            "risk_free_returns": [{"date": "2026-02-23", "return": 0.001}],
        }
    }

    payload = returns_series_service._resolved_stateful_returns_series_request_payload(
        request=request,
        identity_payload=identity_payload,
    )

    assert payload["input_mode"] == InputMode.STATELESS.value
    assert payload["portfolio_id"] == request.portfolio_id
    assert payload["risk_free"] == request.risk_free.model_dump(mode="json")
    assert payload["stateless_input"] == identity_payload["stateless_input"]


def test_stateful_returns_series_resolution_context_builds_window_and_service(monkeypatch):
    request = _build_stateful_request()
    settings = object()
    service = object()

    monkeypatch.setattr(returns_series_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        returns_series_service,
        "build_stateful_input_service",
        lambda *, settings: service,
    )

    context = returns_series_service._stateful_returns_series_resolution_context(request)

    assert context.active_settings is settings
    assert context.stateful_input_service is service
    assert context.resolved_window == returns_series_service.resolve_window(request)


def test_stateful_returns_series_resolution_context_requires_stateful_mode():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-24",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-24"},
            "frequency": "DAILY",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.0100"},
                ],
            },
        }
    )

    with pytest.raises(ValueError, match="only supports stateful requests"):
        returns_series_service._stateful_returns_series_resolution_context(request)


def test_stateful_returns_series_resolution_context_requires_stateful_input():
    request = _build_stateful_request().model_copy(update={"stateful_input": None})

    with pytest.raises(APIError) as exc:
        returns_series_service._stateful_returns_series_resolution_context(request)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_retrieve_stateful_returns_series_sources_completes_retrieval_stage(monkeypatch, tmp_path):
    request = _build_stateful_request(
        reporting_currency="USD",
        series_selection={"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
    )
    store = _seed_execution(monkeypatch, tmp_path, request)
    resolved_window = returns_series_service.resolve_window(request)
    portfolio_source = returns_series_service.StatefulPortfolioInput(
        performance_start_date=pd.Timestamp("2026-02-23").date(),
        observations=[{"valuation_date": "2026-02-23"}, {"valuation_date": "2026-02-24"}],
        retrieval_metadata=stateful_input_service.RetrievalMetadata(chunk_count=2, page_count=3),
    )
    benchmark_resolution = returns_series_service._StatefulBenchmarkResolution(
        benchmark_id="BMK_CORE",
        benchmark_points=[{"series_date": "2026-02-23"}],
        benchmark_df=None,
        benchmark_source_details={"benchmark_chunk_count": 4, "benchmark_page_count": 5},
        benchmark_work_units=1,
    )

    async def _portfolio_source(**kwargs):  # noqa: ARG001
        return portfolio_source

    async def _benchmark_source(**kwargs):  # noqa: ARG001
        return benchmark_resolution

    async def _risk_free_source(**kwargs):  # noqa: ARG001
        return [{"series_date": "2026-02-23"}], {"retrieval_metadata": {"chunk_count": 6, "page_count": 7}}

    monkeypatch.setattr(
        returns_series_service,
        "_retrieve_stateful_returns_series_portfolio_source",
        _portfolio_source,
    )
    monkeypatch.setattr(
        returns_series_service,
        "_resolve_stateful_returns_series_benchmark_source",
        _benchmark_source,
    )
    monkeypatch.setattr(
        returns_series_service,
        "_retrieve_stateful_returns_series_risk_free",
        _risk_free_source,
    )

    sources = await returns_series_service._retrieve_stateful_returns_series_sources(
        request=request,
        context=returns_series_service._StatefulReturnsSeriesResolutionContext(
            active_settings=object(),
            resolved_window=resolved_window,
            stateful_input_service=object(),
        ),
    )

    assert sources.portfolio_source is portfolio_source
    assert sources.benchmark_resolution is benchmark_resolution
    assert sources.risk_free_points == [{"series_date": "2026-02-23"}]
    assert sources.resolved_benchmark_return_source == BenchmarkReturnSource.CALCULATED
    execution = store.get_execution(request.calculation_id)
    assert execution is not None
    retrieval_stage = next(
        stage for stage in execution.stages if stage.stage_name == returns_series_service.EXECUTION_STAGE_RETRIEVAL
    )
    assert retrieval_stage.status.value == "complete"
    assert retrieval_stage.details == {
        "portfolio_observations": 2,
        "benchmark_points": 1,
        "benchmark_work_units": 1,
        "risk_free_points": 1,
        "portfolio_chunk_count": 2,
        "portfolio_page_count": 3,
        "benchmark_chunk_count": 4,
        "benchmark_page_count": 5,
        "risk_free_chunk_count": 6,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "mapped_status", "mapped_code"),
    [(503, 503, "SOURCE_UNAVAILABLE"), (404, 422, "INSUFFICIENT_DATA")],
)
async def test_retrieve_stateful_returns_series_portfolio_source_maps_upstream_errors(
    monkeypatch,
    upstream_status,
    mapped_status,
    mapped_code,
):
    request = _build_stateful_request()
    resolved_window = returns_series_service.resolve_window(request)

    async def _retrieve_stateful_portfolio_input(**kwargs):  # noqa: ARG001
        raise APIError(status_code=upstream_status, detail={"message": "portfolio source unavailable"})

    monkeypatch.setattr(
        returns_series_service,
        "retrieve_stateful_portfolio_input",
        _retrieve_stateful_portfolio_input,
    )

    with pytest.raises(APIError) as exc:
        await returns_series_service._retrieve_stateful_returns_series_portfolio_source(
            active_settings=object(),
            stateful_input_service=object(),
            request=request,
            resolved_window=resolved_window,
        )

    assert exc.value.status_code == mapped_status
    assert exc.value.detail["code"] == mapped_code
    assert "portfolio source unavailable" in exc.value.detail["message"]


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

    with pytest.raises(APIError) as exc:
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

    with pytest.raises(APIError) as exc:
        await returns_series_service._resolve_stateful_returns_series_benchmark_id(
            request=request,
            stateful_input_service=Service(),
            resolved_benchmark_id=None,
        )

    assert exc.value.status_code == 422


def test_benchmark_id_from_assignment_payload_rejects_blank_benchmark_id():
    with pytest.raises(APIError) as exc:
        returns_series_service._benchmark_id_from_assignment_payload({"benchmark_id": ""})

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "CONTRACT_VIOLATION_UPSTREAM"


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

    with pytest.raises(APIError) as exc:
        await returns_series_service._retrieve_stateful_returns_series_risk_free(
            request=request,
            stateful_input_service=object(),
            resolved_window=resolved_window,
        )

    assert exc.value.status_code == 400


def test_risk_free_points_from_payload_accepts_points_list():
    points = [{"series_date": "2026-02-25", "value": "0.0001"}]

    assert returns_series_service._risk_free_points_from_payload({"points": points}) == points


def test_risk_free_points_from_payload_rejects_missing_points_list():
    with pytest.raises(APIError) as exc:
        returns_series_service._risk_free_points_from_payload({"points": None})

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "CONTRACT_VIOLATION_UPSTREAM"


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

    with pytest.raises(APIError) as exc:
        await returns_series_service._retrieve_stateful_returns_series_risk_free(
            request=request,
            stateful_input_service=Service(),
            resolved_window=resolved_window,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_retrieve_stateful_returns_series_vendor_benchmark_uses_core_series():
    request = _build_stateful_request(benchmark={"benchmark_id": "BMK", "return_source": "vendor_series"})
    resolved_window = returns_series_service.resolve_window(request)

    class Service:
        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 200, {
                "points": [{"series_date": "2026-02-25", "benchmark_return": "0.001"}],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            }

    source = await returns_series_service._retrieve_stateful_returns_series_vendor_benchmark(
        request=request,
        stateful_input_service=Service(),
        resolved_window=resolved_window,
        benchmark_id="BMK",
    )

    assert source.benchmark_points == [{"series_date": "2026-02-25", "benchmark_return": "0.001"}]
    assert source.benchmark_source_details["benchmark_points"] == 1
    assert source.benchmark_source_details["benchmark_chunk_count"] == 1
    assert source.benchmark_work_units == 1


@pytest.mark.asyncio
async def test_retrieve_stateful_returns_series_vendor_benchmark_maps_source_errors():
    request = _build_stateful_request(benchmark={"benchmark_id": "BMK", "return_source": "vendor_series"})
    resolved_window = returns_series_service.resolve_window(request)

    class MissingService:
        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 404, {}

    with pytest.raises(APIError) as exc_missing:
        await returns_series_service._retrieve_stateful_returns_series_vendor_benchmark(
            request=request,
            stateful_input_service=MissingService(),
            resolved_window=resolved_window,
            benchmark_id="BMK",
        )
    assert exc_missing.value.status_code == 404

    class UnavailableService:
        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 503, {}

    with pytest.raises(APIError) as exc_unavailable:
        await returns_series_service._retrieve_stateful_returns_series_vendor_benchmark(
            request=request,
            stateful_input_service=UnavailableService(),
            resolved_window=resolved_window,
            benchmark_id="BMK",
        )
    assert exc_unavailable.value.status_code == 503


@pytest.mark.asyncio
async def test_retrieve_stateful_returns_series_vendor_benchmark_rejects_invalid_payload():
    request = _build_stateful_request(benchmark={"benchmark_id": "BMK", "return_source": "vendor_series"})
    resolved_window = returns_series_service.resolve_window(request)

    class Service:
        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 200, {"points": None}

    with pytest.raises(APIError) as exc:
        await returns_series_service._retrieve_stateful_returns_series_vendor_benchmark(
            request=request,
            stateful_input_service=Service(),
            resolved_window=resolved_window,
            benchmark_id="BMK",
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_stateful_returns_series_benchmark_source_skips_unselected_benchmark():
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": False, "include_risk_free": False}
    )
    resolved_window = returns_series_service.resolve_window(request)

    resolution = await returns_series_service._resolve_stateful_returns_series_benchmark_source(
        request=request,
        stateful_input_service=object(),
        resolved_window=resolved_window,
        resolved_benchmark_id=None,
        resolved_benchmark_return_source=BenchmarkReturnSource.CALCULATED,
    )

    assert resolution.benchmark_id is None
    assert resolution.benchmark_points is None
    assert resolution.benchmark_df is None
    assert resolution.benchmark_source_details == {}
    assert resolution.benchmark_work_units == 0


@pytest.mark.asyncio
async def test_resolve_stateful_returns_series_benchmark_source_builds_calculated_frame(monkeypatch):
    request = _build_stateful_request(benchmark={"benchmark_id": "BMK", "return_source": "calculated"})
    resolved_window = returns_series_service.resolve_window(request)

    async def _build_benchmark(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-23",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.001,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX1",
                    perf_date="2026-02-24",
                    weight_bop=1.0,
                    component_currency="USD",
                    component_return=0.002,
                ),
            ],
            benchmark_return_points=[],
            source_details={"benchmark_components": 1, "component_observations": 2},
        )

    monkeypatch.setattr(returns_series_service, "build_stateful_benchmark_input", _build_benchmark)

    resolution = await returns_series_service._resolve_stateful_returns_series_benchmark_source(
        request=request,
        stateful_input_service=object(),
        resolved_window=resolved_window,
        resolved_benchmark_id="BMK",
        resolved_benchmark_return_source=BenchmarkReturnSource.CALCULATED,
    )

    assert resolution.benchmark_id == "BMK"
    assert resolution.benchmark_points is None
    assert resolution.benchmark_df is not None
    assert [value.date().isoformat() for value in resolution.benchmark_df["date"]] == ["2026-02-23", "2026-02-24"]
    assert resolution.benchmark_source_details == {
        "benchmark_components": 1,
        "component_observations": 2,
        "benchmark_points": 2,
    }
    assert resolution.benchmark_work_units == 2


@pytest.mark.asyncio
async def test_resolve_stateful_normalized_benchmark_source_projects_return_points(monkeypatch):
    request = _build_stateful_request(benchmark={"benchmark_id": "BMK", "return_source": "calculated"})
    resolved_window = returns_series_service.resolve_window(request)

    async def _build_benchmark(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[],
            benchmark_return_points=[
                BenchmarkReturnPoint(perf_date="2026-02-23", benchmark_return=0.001),
                BenchmarkReturnPoint(perf_date="2026-02-24", benchmark_return=0.002),
            ],
            source_details={"benchmark_return_points": 2},
        )

    monkeypatch.setattr(returns_series_service, "build_stateful_benchmark_input", _build_benchmark)

    resolution = await returns_series_service._resolve_stateful_normalized_benchmark_source(
        request=request,
        stateful_input_service=object(),
        resolved_window=resolved_window,
        benchmark_id="BMK",
        resolved_benchmark_return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )

    assert resolution.benchmark_id == "BMK"
    assert resolution.benchmark_points is None
    assert resolution.benchmark_df is not None
    assert [value.date().isoformat() for value in resolution.benchmark_df["date"]] == ["2026-02-23", "2026-02-24"]
    assert resolution.benchmark_source_details == {
        "benchmark_return_points": 2,
        "benchmark_points": 2,
    }
    assert resolution.benchmark_work_units == 2


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

    with pytest.raises(APIError) as exc:
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

    with pytest.raises(APIError) as exc:
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

    with pytest.raises(APIError) as exc_missing_id:
        await returns_series_service.calculate_returns_series(request)
    assert exc_missing_id.value.status_code == 422

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK"}

    async def _bad_points(self, **kwargs):  # noqa: ARG001
        return 200, {"bad": []}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _bad_points)

    with pytest.raises(APIError) as exc_bad_points:
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
    with pytest.raises(APIError) as exc_bmk_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_404.value.status_code == 404

    async def _benchmark_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_503)
    with pytest.raises(APIError) as exc_bmk_503:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_503.value.status_code == 503

    async def _benchmark_ok(self, **kwargs):  # noqa: ARG001
        return 200, {"points": [{"series_date": "2026-02-23", "benchmark_return": "0.01"}]}

    async def _risk_free_404(self, **kwargs):  # noqa: ARG001
        return 404, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_ok)
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_risk_free_series", _risk_free_404)
    with pytest.raises(APIError) as exc_rf_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_rf_404.value.status_code == 404

    async def _risk_free_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_risk_free_series", _risk_free_503)
    with pytest.raises(APIError) as exc_rf_503:
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
        def __init__(
            self,
            *,
            core_service,
            portfolio_chunk_days,
            reference_chunk_days,
            max_concurrent_chunks,
            max_pages_per_chunk,
        ):
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
                "max_pages_per_chunk": max_pages_per_chunk,
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
                "STATEFUL_INPUT_MAX_PAGES_PER_CHUNK": 11,
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
        "max_pages_per_chunk": 11,
    }
    assert len(response.series.portfolio_returns) == 1
