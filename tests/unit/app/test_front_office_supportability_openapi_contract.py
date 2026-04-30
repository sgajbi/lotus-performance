from main import app


def test_front_office_calculation_surfaces_expose_supportability_contract() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    for schema_name in (
        "MoneyWeightedReturnResponse",
        "ContributionResponse",
        "AttributionResponse",
    ):
        schema = schemas[schema_name]
        assert "calculation_supportability" in schema["properties"]
        assert "calculation_supportability" in schema["required"]

    supportability_schema = schemas["PerformanceCalculationSupportability"]
    assert set(supportability_schema["properties"]) >= {
        "state",
        "reason",
        "freshness_bucket",
        "input_row_count",
        "resolved_period_count",
        "benchmark_row_count",
    }
