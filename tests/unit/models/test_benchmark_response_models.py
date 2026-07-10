from app.models.benchmark_responses import BenchmarkAcceptedResponse, BenchmarkPerformanceResponse


def test_benchmark_response_schemas_document_examples_for_swagger():
    response_schema = BenchmarkPerformanceResponse.model_json_schema()
    accepted_schema = BenchmarkAcceptedResponse.model_json_schema()

    assert response_schema["examples"][0]["benchmark_id"] == "BMK_PB_GLOBAL_BALANCED_60_40"
    assert response_schema["examples"][0]["results_by_period"]["YTD"]["benchmark"]["input_mode"] == "stateful"
    for field_name in (
        "calculation_id",
        "benchmark_id",
        "benchmark_currency",
        "input_mode",
        "return_source",
        "results_by_period",
        "meta",
        "diagnostics",
        "audit",
    ):
        assert response_schema["properties"][field_name]["description"]

    assert accepted_schema["examples"][0]["result_path"].startswith("/performance/benchmark/results/")
    for field_name in ("calculation_id", "poll_path", "result_path", "recommended_poll_after_seconds"):
        field_schema = accepted_schema["properties"][field_name]
        assert field_schema["description"]
        assert field_schema["examples"]
