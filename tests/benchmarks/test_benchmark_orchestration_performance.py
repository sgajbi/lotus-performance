from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest

import app.services.benchmark_mode_service as benchmark_mode_service
import app.services.benchmark_service as benchmark_service
import app.services.execution_lifecycle_service as execution_lifecycle_service
from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.services.execution_registry import ExecutionRegistry
from app.services.stateful_input_service import StatefulInputService
from core.repro import generate_canonical_hash
from tests.benchmarks.test_stateful_input_performance import (
    STATEFUL_PORTFOLIO_WINDOW_END,
    STATEFUL_PORTFOLIO_WINDOW_START,
    _StatefulBenchmarkCoreServiceStub,
)

BENCHMARK_ORCHESTRATION_MEDIAN_MS_BUDGET = 3600.0


@pytest.mark.asyncio
async def test_benchmark_stateful_orchestration_characterization_contract(tmp_path):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'benchmark-orchestration-execution.db'}")
    execution_store.create_schema()
    settings = get_settings()
    core_service_stub = _StatefulBenchmarkCoreServiceStub()

    original_mode_registry = benchmark_mode_service.execution_registry
    original_service_registry = benchmark_service.execution_registry
    original_builder = benchmark_mode_service.build_stateful_input_service
    original_lifecycle_registry = execution_lifecycle_service.execution_registry
    original_lineage_service = execution_lifecycle_service.lineage_service

    benchmark_mode_service.execution_registry = execution_store
    benchmark_service.execution_registry = execution_store
    execution_lifecycle_service.execution_registry = execution_store
    execution_lifecycle_service.lineage_service = type(
        "_NoopLineageService",
        (),
        {"enqueue_capture": staticmethod(lambda **kwargs: None)},
    )()
    benchmark_mode_service.build_stateful_input_service = lambda settings: StatefulInputService(
        core_service=core_service_stub,
        execution_store=execution_store,
        portfolio_chunk_days=settings.STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS,
        reference_chunk_days=settings.STATEFUL_INPUT_REFERENCE_CHUNK_DAYS,
        max_concurrent_chunks=settings.STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS,
    )

    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK-CHAR",
            "benchmark_start_date": str(STATEFUL_PORTFOLIO_WINDOW_START),
            "report_end_date": str(STATEFUL_PORTFOLIO_WINDOW_END),
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "return_source": "calculated",
            "stateful_input": {"consumer_system": "lotus-performance"},
            "output": {"include_timeseries": True},
        }
    )
    source_input_fingerprint, source_calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)

    def _register(calculation_id) -> None:
        execution_store.create_execution(
            calculation_id=calculation_id,
            analytics_type="BENCHMARK",
            portfolio_id="BMK-CHAR",
            execution_mode="sync",
            requested_window={"mode": "EXPLICIT"},
            input_fingerprint=source_input_fingerprint,
            calculation_hash=source_calculation_hash,
        )

    try:
        _register(request.calculation_id)
        resolved_request = await benchmark_mode_service.resolve_benchmark_request(request, settings=settings)
        benchmark_request = resolved_request.benchmark_request
        input_fingerprint, calculation_hash = generate_canonical_hash(benchmark_request, settings.APP_VERSION)
        execution_store.update_execution_identity(
            request.calculation_id,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        benchmark_service.calculate_benchmark_response(
            benchmark_request,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            input_mode=BenchmarkInputMode.STATEFUL,
            engine_version=settings.APP_VERSION,
            request_artifact_model=benchmark_request,
        )

        timings = []
        for _ in range(5):
            calculation_id = uuid4()
            request = request.model_copy(update={"calculation_id": calculation_id})
            _register(calculation_id)
            start = perf_counter()
            resolved_request = await benchmark_mode_service.resolve_benchmark_request(request, settings=settings)
            benchmark_request = resolved_request.benchmark_request
            input_fingerprint, calculation_hash = generate_canonical_hash(benchmark_request, settings.APP_VERSION)
            execution_store.update_execution_identity(
                calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )
            response = benchmark_service.calculate_benchmark_response(
                benchmark_request,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                input_mode=BenchmarkInputMode.STATEFUL,
                engine_version=settings.APP_VERSION,
                request_artifact_model=benchmark_request,
            )
            timings.append((perf_counter() - start) * 1000)
    finally:
        benchmark_mode_service.execution_registry = original_mode_registry
        benchmark_service.execution_registry = original_service_registry
        execution_lifecycle_service.execution_registry = original_lifecycle_registry
        execution_lifecycle_service.lineage_service = original_lineage_service
        benchmark_mode_service.build_stateful_input_service = original_builder

    expected_days = (STATEFUL_PORTFOLIO_WINDOW_END - STATEFUL_PORTFOLIO_WINDOW_START).days + 1
    assert response.benchmark_currency == "USD"
    assert response.audit.counts["component_observations"] == expected_days * 4
    assert response.audit.counts["daily_returns"] == expected_days

    median_ms = median(timings)
    assert median_ms <= BENCHMARK_ORCHESTRATION_MEDIAN_MS_BUDGET, (
        f"Stateful benchmark orchestration median {median_ms:.2f}ms exceeded "
        f"budget {BENCHMARK_ORCHESTRATION_MEDIAN_MS_BUDGET:.2f}ms "
        f"for window {STATEFUL_PORTFOLIO_WINDOW_START}..{STATEFUL_PORTFOLIO_WINDOW_END}."
    )
