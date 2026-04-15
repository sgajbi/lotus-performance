from __future__ import annotations

from main import app


def test_workspace_summary_openapi_describes_usage_and_schema_fields():
    spec = app.openapi()
    post_operation = spec["paths"]["/performance/workspace-summary"]["post"]
    get_operation = spec["paths"]["/performance/workspace-summary/results/{calculation_id}"]["get"]

    assert "front-office workspace summary" in post_operation["description"]
    assert "portfolio TWR net/gross" in post_operation["description"]
    assert "stateful_input envelope" in post_operation["description"]
    assert "async request" in get_operation["description"]

    schemas = spec["components"]["schemas"]
    request_schema = schemas["WorkspaceSummaryRequest"]
    period_schema = schemas["WorkspaceSummaryPeriodRequest"]
    benchmark_schema = schemas["WorkspaceBenchmarkRequest"]
    accepted_schema = schemas["WorkspaceSummaryAcceptedResponse"]

    for field_name in [
        "portfolio_id",
        "report_end_date",
        "periods",
        "input_mode",
        "stateless_input",
        "stateful_input",
        "valuation_points",
        "include_benchmark",
        "benchmark",
        "mwr_method",
        "report_ccy",
    ]:
        assert request_schema["properties"][field_name]["description"]

    assert "Deprecated compatibility" in request_schema["properties"]["valuation_points"]["description"]

    for field_name in ["period", "frequencies"]:
        assert period_schema["properties"][field_name]["description"]

    for field_name in ["benchmark_id", "input_mode", "return_source", "stateless_input", "stateful_input"]:
        assert benchmark_schema["properties"][field_name]["description"]

    for field_name in ["calculation_id", "poll_path", "result_path"]:
        assert accepted_schema["properties"][field_name]["description"]
