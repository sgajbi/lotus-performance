from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest

import app.services.execution_lifecycle_service as execution_lifecycle_service
import app.services.twr_mode_service as twr_mode_service
import app.services.twr_service as twr_service
from app.core.config import get_settings
from app.models.twr_requests import TWRAnalyticsRequest, TWRResolvedExecutionRequest
from app.services.execution_registry import ExecutionRegistry
from core.repro import generate_canonical_hash, generate_canonical_hash_from_value
from tests.benchmarks.test_stateful_input_performance import (
    STATEFUL_PORTFOLIO_WINDOW_END,
    STATEFUL_PORTFOLIO_WINDOW_START,
    _build_observations,
    _StatefulBenchmarkCoreServiceStub,
)

TWR_BENCHMARK_ORCHESTRATION_MEDIAN_MS_BUDGET = 4200.0


@pytest.mark.asyncio
async def test_twr_stateful_benchmark_orchestration_characterization_contract(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'twr-benchmark-orchestration-execution.db'}")
    execution_store.create_schema()
    settings = get_settings()
    core_service_stub = _StatefulBenchmarkCoreServiceStub()

    original_mode_registry = twr_mode_service.execution_registry
    original_service_registry = twr_service.execution_registry
    original_builder = twr_mode_service.build_stateful_input_service
    original_lifecycle_registry = execution_lifecycle_service.execution_registry
    original_lineage_service = execution_lifecycle_service.lineage_service

    twr_mode_service.execution_registry = execution_store
    twr_service.execution_registry = execution_store
    execution_lifecycle_service.execution_registry = execution_store
    execution_lifecycle_service.lineage_service = type(
        "_NoopLineageService",
        (),
        {"enqueue_capture": staticmethod(lambda **kwargs: None)},
    )()
    twr_mode_service.build_stateful_input_service = lambda settings: twr_mode_service.StatefulInputService(
        core_service=core_service_stub,
        execution_store=execution_store,
        portfolio_chunk_days=settings.STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS,
        reference_chunk_days=settings.STATEFUL_INPUT_REFERENCE_CHUNK_DAYS,
        max_concurrent_chunks=settings.STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS,
    )

    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": STATEFUL_PORTFOLIO_WINDOW_START.isoformat(),
                "observations": _build_observations(
                    start_date=STATEFUL_PORTFOLIO_WINDOW_START,
                    end_date=STATEFUL_PORTFOLIO_WINDOW_END,
                    ending_market_value="101",
                ),
                "retrieval_metadata": {"chunk_count": 41, "page_count": 82},
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PF-TWR-CHAR",
            "performance_start_date": str(STATEFUL_PORTFOLIO_WINDOW_START),
            "metric_basis": "NET",
            "report_end_date": str(STATEFUL_PORTFOLIO_WINDOW_END),
            "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
            "input_mode": "stateful",
            "stateful_input": {"consumer_system": "lotus-performance"},
            "include_benchmark": True,
        }
    )
    source_input_fingerprint, source_calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)

    def _register(calculation_id) -> None:
        execution_store.create_execution(
            calculation_id=calculation_id,
            analytics_type="TWR",
            portfolio_id="PF-TWR-CHAR",
            execution_mode="sync",
            requested_window={"mode": "EXPLICIT"},
            input_fingerprint=source_input_fingerprint,
            calculation_hash=source_calculation_hash,
        )

    try:
        _register(request.calculation_id)
        resolved_request = await twr_mode_service.resolve_twr_request(request, settings=settings)
        resolved_identity = TWRResolvedExecutionRequest(
            portfolio=resolved_request.performance_request,
            benchmark=resolved_request.benchmark_request,
        )
        input_fingerprint, calculation_hash = generate_canonical_hash_from_value(
            resolved_identity,
            settings.APP_VERSION,
        )
        execution_store.update_execution_identity(
            request.calculation_id,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        twr_service.calculate_twr_response(
            resolved_request.performance_request,
            portfolio_id=request.portfolio_id,
            input_mode=resolved_request.input_mode,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            engine_version=settings.APP_VERSION,
            request_artifact_model=resolved_identity,
            benchmark_request=resolved_request.benchmark_request,
            benchmark_input_mode=resolved_request.benchmark_input_mode,
            resolved_benchmark_id=resolved_request.resolved_benchmark_id,
        )

        timings = []
        for _ in range(5):
            calculation_id = uuid4()
            request = request.model_copy(update={"calculation_id": calculation_id})
            _register(calculation_id)
            start = perf_counter()
            resolved_request = await twr_mode_service.resolve_twr_request(request, settings=settings)
            resolved_identity = TWRResolvedExecutionRequest(
                portfolio=resolved_request.performance_request,
                benchmark=resolved_request.benchmark_request,
            )
            input_fingerprint, calculation_hash = generate_canonical_hash_from_value(
                resolved_identity,
                settings.APP_VERSION,
            )
            execution_store.update_execution_identity(
                calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )
            response = twr_service.calculate_twr_response(
                resolved_request.performance_request,
                portfolio_id=request.portfolio_id,
                input_mode=resolved_request.input_mode,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                engine_version=settings.APP_VERSION,
                request_artifact_model=resolved_identity,
                benchmark_request=resolved_request.benchmark_request,
                benchmark_input_mode=resolved_request.benchmark_input_mode,
                resolved_benchmark_id=resolved_request.resolved_benchmark_id,
            )
            timings.append((perf_counter() - start) * 1000)
    finally:
        twr_mode_service.execution_registry = original_mode_registry
        twr_service.execution_registry = original_service_registry
        execution_lifecycle_service.execution_registry = original_lifecycle_registry
        execution_lifecycle_service.lineage_service = original_lineage_service
        twr_mode_service.build_stateful_input_service = original_builder

    assert response.benchmark is not None
    assert response.benchmark.benchmark_id == "BMK-CHAR"
    assert response.results_by_period["ITD"].relative_performance is not None

    median_ms = median(timings)
    assert median_ms <= TWR_BENCHMARK_ORCHESTRATION_MEDIAN_MS_BUDGET, (
        f"Stateful benchmark-inclusive TWR orchestration median {median_ms:.2f}ms exceeded "
        f"budget {TWR_BENCHMARK_ORCHESTRATION_MEDIAN_MS_BUDGET:.2f}ms "
        f"for window {STATEFUL_PORTFOLIO_WINDOW_START}..{STATEFUL_PORTFOLIO_WINDOW_END}."
    )
