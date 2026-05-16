from __future__ import annotations

from main import app


def test_benchmark_exposure_context_openapi_documents_usage_and_fields() -> None:
    spec = app.openapi()
    operation = spec["paths"]["/integration/benchmarks/exposure-context"]["post"]

    assert "downstream risk attribution" in operation["summary"]
    assert "lotus-core benchmark composition lineage" in operation["description"]
    assert "lotus-core remains the authoritative system of record" in operation["description"]

    schemas = spec["components"]["schemas"]
    request_schema = schemas["BenchmarkExposureContextRequest"]
    row_schema = schemas["BenchmarkExposureRow"]
    response_schema = schemas["BenchmarkExposureContextResponse"]
    metadata_schema = schemas["BenchmarkExposureMetadata"]

    for field_name in [
        "portfolio_id",
        "benchmark_id",
        "as_of_date",
        "window",
        "frequency",
        "reporting_currency",
        "grouping_dimensions",
        "page",
    ]:
        assert request_schema["properties"][field_name]["description"]

    assert "DAILY only" in request_schema["properties"]["frequency"]["description"]
    assert request_schema["examples"][0]["grouping_dimensions"] == ["POSITION", "SECTOR", "ASSET_CLASS", "ISSUER"]

    for field_name in [
        "valuation_date",
        "component_id",
        "grouping_dimension",
        "group_key",
        "group_label",
        "weight",
    ]:
        assert row_schema["properties"][field_name]["description"]

    for field_name in [
        "calculation_id",
        "source_service",
        "contract_version",
        "portfolio_id",
        "benchmark_id",
        "benchmark_version",
        "as_of_date",
        "window",
        "frequency",
        "reporting_currency",
        "rows",
        "page",
        "metadata",
    ]:
        assert response_schema["properties"][field_name]["description"]

    assert response_schema["examples"][0]["metadata"]["source_system"] == "lotus-core"
    assert metadata_schema["properties"]["retrieval_metadata"]["description"]
