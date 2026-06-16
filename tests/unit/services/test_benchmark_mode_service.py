from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkComponentObservation, BenchmarkReturnPoint
from app.services import benchmark_mode_service
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput


@pytest.mark.asyncio
async def test_resolve_benchmark_request_requires_stateless_input_for_stateless_mode():
    request = BenchmarkAnalyticsRequest.model_construct(  # type: ignore[call-arg]
        calculation_id=uuid4(),
        benchmark_id="BMK_1",
        benchmark_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        analyses=[],
        input_mode=BenchmarkInputMode.STATELESS,
        return_source="calculated",
        stateless_input=None,
        stateful_input=None,
    )

    with pytest.raises(HTTPException, match="stateless_input is required"):
        await benchmark_mode_service.resolve_benchmark_request(request, settings=object())


@pytest.mark.asyncio
async def test_resolve_benchmark_request_passthroughs_stateless_vendor_series_mode():
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    {"perf_date": "2025-01-02", "benchmark_return": 0.02},
                ],
            },
        }
    )

    resolved = await benchmark_mode_service.resolve_benchmark_request(request, settings=object())

    assert resolved.input_mode == BenchmarkInputMode.STATELESS
    assert resolved.input_count == 2
    assert resolved.source_details == {
        "component_observations": 0,
        "component_price_points": 0,
        "benchmark_return_points": 2,
    }
    assert len(resolved.benchmark_request.benchmark_return_points) == 2


def test_resolve_stateless_benchmark_request_projects_calculated_observation_details():
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {
                        "component_id": "IDX_1",
                        "perf_date": "2025-01-01",
                        "weight_bop": 1.0,
                        "component_return": 0.01,
                    }
                ],
            },
        }
    )

    resolved = benchmark_mode_service._resolve_stateless_benchmark_request(request)

    assert resolved.input_mode == BenchmarkInputMode.STATELESS
    assert resolved.input_count == 1
    assert resolved.source_details == {
        "component_observations": 1,
        "component_price_points": 0,
        "benchmark_return_points": 0,
    }
    assert resolved.benchmark_request.benchmark_currency == "USD"
    assert len(resolved.benchmark_request.component_observations) == 1


def test_resolve_stateless_benchmark_request_projects_vendor_series_details():
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    {"perf_date": "2025-01-02", "benchmark_return": 0.02},
                ],
            },
        }
    )

    resolved = benchmark_mode_service._resolve_stateless_benchmark_request(request)

    assert resolved.input_count == 2
    assert resolved.source_details == {
        "component_observations": 0,
        "component_price_points": 0,
        "benchmark_return_points": 2,
    }
    assert not resolved.benchmark_request.component_observations
    assert len(resolved.benchmark_request.benchmark_return_points) == 2


def test_stateful_benchmark_request_helpers_project_normalized_inputs_and_counts():
    calculated_request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "return_source": "calculated",
            "stateful_input": {},
        }
    )
    vendor_request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "return_source": "vendor_series",
            "stateful_input": {},
        }
    )
    calculated_input = StatefulBenchmarkNormalizedInput(
        benchmark_currency="USD",
        component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                perf_date=date(2025, 1, 1),
                weight_bop=1.0,
                component_return=0.01,
            )
        ],
        benchmark_return_points=[],
        source_details={"component_observations": 1},
    )
    vendor_input = StatefulBenchmarkNormalizedInput(
        benchmark_currency="USD",
        component_observations=[],
        benchmark_return_points=[
            BenchmarkReturnPoint(perf_date=date(2025, 1, 1), benchmark_return=0.01),
            BenchmarkReturnPoint(perf_date=date(2025, 1, 2), benchmark_return=0.02),
        ],
        source_details={"benchmark_return_points": 2},
    )

    benchmark_request = benchmark_mode_service._stateful_benchmark_performance_request(
        calculated_request,
        calculated_input,
    )

    assert benchmark_request.benchmark_currency == "USD"
    assert len(benchmark_request.component_observations) == 1
    assert not benchmark_request.benchmark_return_points
    assert benchmark_mode_service._stateful_benchmark_input_count(calculated_request, calculated_input) == 1
    assert benchmark_mode_service._stateful_benchmark_input_count(vendor_request, vendor_input) == 2


@pytest.mark.asyncio
async def test_resolve_benchmark_request_fails_retrieval_stage_for_stateful_errors(monkeypatch):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    stage_events: list[tuple[str, str]] = []

    monkeypatch.setattr(
        benchmark_mode_service.execution_registry,
        "start_stage",
        lambda calculation_id, stage_name: stage_events.append(("start", stage_name)),
    )
    monkeypatch.setattr(
        benchmark_mode_service.execution_registry,
        "fail_stage",
        lambda calculation_id, stage_name, message: stage_events.append(("fail", stage_name)),
    )
    monkeypatch.setattr(
        "app.services.benchmark_mode_service.build_stateful_input_service",
        lambda settings: object(),
    )

    async def _raise_http_error(**kwargs):  # noqa: ARG001
        raise HTTPException(status_code=503, detail="stateful benchmark unavailable")

    monkeypatch.setattr(
        "app.services.benchmark_mode_service.build_stateful_benchmark_input",
        _raise_http_error,
    )

    with pytest.raises(HTTPException, match="stateful benchmark unavailable"):
        await benchmark_mode_service.resolve_benchmark_request(request, settings=object())

    assert ("start", "retrieval") in stage_events
    assert ("fail", "retrieval") in stage_events


@pytest.mark.asyncio
async def test_resolve_benchmark_request_fails_normalization_stage_when_request_building_breaks(monkeypatch):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    stage_events: list[tuple[str, str]] = []

    monkeypatch.setattr(
        benchmark_mode_service.execution_registry,
        "start_stage",
        lambda calculation_id, stage_name: stage_events.append(("start", stage_name)),
    )
    monkeypatch.setattr(
        benchmark_mode_service.execution_registry,
        "complete_stage",
        lambda calculation_id, stage_name, details: stage_events.append(("complete", stage_name)),
    )
    monkeypatch.setattr(
        benchmark_mode_service.execution_registry,
        "fail_stage",
        lambda calculation_id, stage_name, message: stage_events.append(("fail", stage_name)),
    )
    monkeypatch.setattr(
        "app.services.benchmark_mode_service.build_stateful_input_service",
        lambda settings: object(),
    )

    async def _build_normalized_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[],
            benchmark_return_points=[],
            source_details={"benchmark_return_points": 0},
        )

    monkeypatch.setattr(
        "app.services.benchmark_mode_service.build_stateful_benchmark_input",
        _build_normalized_input,
    )
    monkeypatch.setattr(
        BenchmarkAnalyticsRequest,
        "to_benchmark_performance_request",
        lambda self, **kwargs: (_ for _ in ()).throw(ValueError("bad normalization")),
    )

    with pytest.raises(ValueError, match="bad normalization"):
        await benchmark_mode_service.resolve_benchmark_request(request, settings=object())

    assert ("start", "retrieval") in stage_events
    assert ("complete", "retrieval") in stage_events
    assert ("start", "normalization") in stage_events
    assert ("fail", "normalization") in stage_events


@pytest.mark.asyncio
async def test_resolve_benchmark_request_uses_vendor_series_point_count_for_stateful_mode(monkeypatch):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "return_source": "vendor_series",
            "stateful_input": {},
        }
    )

    monkeypatch.setattr(
        benchmark_mode_service.execution_registry,
        "start_stage",
        lambda calculation_id, stage_name: None,
    )
    monkeypatch.setattr(
        benchmark_mode_service.execution_registry,
        "complete_stage",
        lambda calculation_id, stage_name, details: None,
    )
    monkeypatch.setattr(
        "app.services.benchmark_mode_service.build_stateful_input_service",
        lambda settings: object(),
    )

    async def _build_normalized_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[],
            benchmark_return_points=[
                BenchmarkReturnPoint(perf_date=date(2025, 1, 1), benchmark_return=0.01),
                BenchmarkReturnPoint(perf_date=date(2025, 1, 2), benchmark_return=0.02),
            ],
            source_details={"benchmark_return_points": 2},
        )

    monkeypatch.setattr(
        "app.services.benchmark_mode_service.build_stateful_benchmark_input",
        _build_normalized_input,
    )

    resolved = await benchmark_mode_service.resolve_benchmark_request(request, settings=object())

    assert resolved.input_mode == BenchmarkInputMode.STATEFUL
    assert resolved.input_count == 2
    assert len(resolved.benchmark_request.benchmark_return_points) == 2
