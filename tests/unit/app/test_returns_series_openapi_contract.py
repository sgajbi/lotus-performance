from __future__ import annotations

from main import app


def test_returns_series_openapi_describes_usage_and_schema_fields():
    spec = app.openapi()
    post_operation = spec["paths"]["/integration/returns/series"]["post"]
    get_operation = spec["paths"]["/integration/returns/series/results/{calculation_id}"]["get"]

    assert "canonical portfolio/benchmark/risk-free return time series" in post_operation["description"]
    assert "stateful" in post_operation["description"]
    assert "stateless" in post_operation["description"]
    assert "async executor job" in get_operation["description"]

    schemas = spec["components"]["schemas"]
    request_schema = schemas["ReturnsSeriesRequest"]
    accepted_schema = schemas["ReturnsSeriesAcceptedResponse"]
    window_schema = schemas["ReturnsWindow"]
    selection_schema = schemas["SeriesSelection"]

    for field_name in [
        "portfolio_id",
        "as_of_date",
        "window",
        "frequency",
        "metric_basis",
        "series_selection",
        "data_policy",
        "input_mode",
        "stateful_input",
        "stateless_input",
    ]:
        assert request_schema["properties"][field_name]["description"]

    for field_name in ["mode", "from_date", "to_date", "period", "year"]:
        assert window_schema["properties"][field_name]["description"]

    for field_name in ["include_portfolio", "include_benchmark", "include_risk_free"]:
        assert selection_schema["properties"][field_name]["description"]

    for field_name in ["calculation_id", "poll_path", "result_path", "status"]:
        assert accepted_schema["properties"][field_name]["description"]
