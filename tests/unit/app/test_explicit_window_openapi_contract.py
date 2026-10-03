from main import app


def test_explicit_window_order_is_declared_on_every_public_request_schema() -> None:
    schemas = app.openapi()["components"]["schemas"]
    request_schemas = (
        "TWRAnalyticsRequest",
        "WorkspaceSummaryRequest",
        "BenchmarkAnalyticsRequest",
        "ContributionAnalyticsRequest",
        "AttributionAnalyticsRequest",
    )

    for schema_name in request_schemas:
        description = schemas[schema_name]["properties"]["report_start_date"]["description"]
        assert "must be on or before report_end_date" in description
