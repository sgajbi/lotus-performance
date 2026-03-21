# tests/benchmarks/test_engine_performance.py
from datetime import date, timedelta
from statistics import median
from time import perf_counter

import pytest

from adapters.api_adapter import create_engine_config, create_engine_dataframe
from app.models.requests import PerformanceRequest
from engine.compute import run_calculations

CHARACTERIZATION_ROW_COUNT = 75_000
CHARACTERIZATION_MEDIAN_SECONDS_BUDGET = 0.50


def _build_characterization_payload() -> dict:
    """Create a large but representable daily workload for engine characterization.

    A true 500k unique-daily-row dataset is not representable in this engine path because
    pandas/numpy timestamp bounds cap realistic daily dates well below that size. This
    fixture therefore uses the largest practical daily-row scale that still exercises the
    vectorized hot path with real date uniqueness.
    """
    base_payload = {
        "portfolio_id": "BENCHMARK_PORT_01",
        "performance_start_date": "2023-12-31",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "rounding_precision": 4,
    }
    valuation_templates = [
        {"begin_mv": 100000.0, "end_mv": 101000.0},
        {"begin_mv": 101000.0, "end_mv": 102500.0},
        {
            "begin_mv": 102500.0,
            "bod_cf": 5000.0,
            "mgmt_fees": -10.0,
            "end_mv": 108000.0,
        },
    ]
    start_date = date(2024, 1, 1)
    valuation_points = []
    for day_offset in range(CHARACTERIZATION_ROW_COUNT):
        template = valuation_templates[day_offset % len(valuation_templates)]
        perf_date = start_date + timedelta(days=day_offset)
        valuation_points.append(
            {
                "perf_date": perf_date.isoformat(),
                **template,
            }
        )
    base_payload["valuation_points"] = valuation_points
    base_payload["report_end_date"] = valuation_points[-1]["perf_date"]
    return base_payload


@pytest.fixture(scope="module")
def large_input_data():
    return _build_characterization_payload()


def test_vectorized_engine_performance(benchmark, large_input_data):
    """Benchmarks the vectorized engine on the governed large daily workload."""
    pydantic_request = PerformanceRequest.model_validate(large_input_data)

    effective_start_date = date.fromisoformat(large_input_data["valuation_points"][0]["perf_date"])
    effective_end_date = date.fromisoformat(large_input_data["report_end_date"])

    engine_config = create_engine_config(pydantic_request, effective_start_date, effective_end_date)
    valuation_points_list = [item.model_dump() for item in pydantic_request.valuation_points]
    engine_df = create_engine_dataframe(valuation_points_list)
    assert len(engine_df) == CHARACTERIZATION_ROW_COUNT

    def run():
        run_calculations(engine_df.copy(deep=True), engine_config)

    benchmark.group = f"Engine Performance ({CHARACTERIZATION_ROW_COUNT} daily rows)"
    benchmark(run)


def test_vectorized_engine_characterization_contract(large_input_data):
    """Enforces a non-flaky runtime budget for the governed large daily workload."""
    pydantic_request = PerformanceRequest.model_validate(large_input_data)

    effective_start_date = date.fromisoformat(large_input_data["valuation_points"][0]["perf_date"])
    effective_end_date = date.fromisoformat(large_input_data["report_end_date"])

    engine_config = create_engine_config(pydantic_request, effective_start_date, effective_end_date)
    valuation_points_list = [item.model_dump() for item in pydantic_request.valuation_points]
    engine_df = create_engine_dataframe(valuation_points_list)

    assert len(engine_df) == CHARACTERIZATION_ROW_COUNT

    run_calculations(engine_df.copy(deep=True), engine_config)

    timings = []
    for _ in range(5):
        start = perf_counter()
        run_calculations(engine_df.copy(deep=True), engine_config)
        timings.append(perf_counter() - start)

    median_seconds = median(timings)
    assert median_seconds <= CHARACTERIZATION_MEDIAN_SECONDS_BUDGET, (
        f"Vectorized engine median runtime {median_seconds:.3f}s exceeded "
        f"budget {CHARACTERIZATION_MEDIAN_SECONDS_BUDGET:.3f}s "
        f"for {CHARACTERIZATION_ROW_COUNT} daily rows."
    )
