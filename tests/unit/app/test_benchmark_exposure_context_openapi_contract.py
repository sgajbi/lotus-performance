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
    source_quality_schema = schemas["BenchmarkExposureSourceQuality"]
    page_request_schema = schemas["BenchmarkExposurePageRequest"]
    page_response_schema = schemas["BenchmarkExposurePageResponse"]

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
    assert "source-bound continuation" in page_request_schema["properties"]["page_token"]["description"]
    assert "continuation_consistency" in page_response_schema["required"]
    assert "BENCHMARK_EXPOSURE_PAGE_SOURCE_CHANGED" in operation["responses"]["409"]["description"]
    assert (
        operation["responses"]["409"]["content"]["application/json"]["example"]["error_code"]
        == "BENCHMARK_EXPOSURE_PAGE_SOURCE_CHANGED"
    )
    assert "legacy_offset_unbound" in page_response_schema["properties"]["continuation_consistency"]["description"]
    assert response_schema["examples"][0]["page"]["continuation_consistency"] == "source_bound"

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
    assert metadata_schema["properties"]["correlation_id"]["description"]
    assert response_schema["examples"][0]["metadata"]["correlation_id"] == "corr_benchmark_exposure_001"
    assert metadata_schema["properties"]["retrieval_metadata"]["description"]
    assert metadata_schema["properties"]["retrieval_metadata_quality"]["description"]
    assert metadata_schema["properties"]["exposure_source_quality"]["description"]
    assert response_schema["examples"][0]["metadata"]["retrieval_metadata_quality"]["reason_codes"] == []
    assert response_schema["examples"][0]["metadata"]["exposure_source_quality"] == {
        "status": "complete",
        "omitted_component_count": 0,
        "omitted_point_count": 0,
        "reason_codes": [],
        "omissions": [],
        "omissions_truncated": False,
    }
    for field_name in [
        "status",
        "omitted_component_count",
        "omitted_point_count",
        "reason_codes",
        "omissions",
        "omissions_truncated",
    ]:
        assert source_quality_schema["properties"][field_name]["description"]
