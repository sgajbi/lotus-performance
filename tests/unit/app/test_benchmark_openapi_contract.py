from main import app


def test_benchmark_openapi_describes_usage_boundaries_and_async_result_path():
    schema = app.openapi()
    benchmark_post = schema["paths"]["/performance/benchmark"]["post"]
    benchmark_result = schema["paths"]["/performance/benchmark/results/{calculation_id}"]["get"]

    assert "benchmark's own return path" in benchmark_post["description"]
    assert 'input_mode="stateless"' in benchmark_post["description"]
    assert 'input_mode="stateful"' in benchmark_post["description"]
    assert 'return_source="calculated"' in benchmark_post["description"]
    assert 'return_source="vendor_series"' in benchmark_post["description"]
    assert "POST /integration/returns/series" in benchmark_post["description"]
    assert "previously returned `202 Accepted`" in benchmark_result["description"]
    assert "/performance/executions/{calculation_id}" in benchmark_result["description"]
