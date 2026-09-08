from main import app


def test_calculation_responses_publish_applied_currency_evidence_contract():
    schemas = app.openapi()["components"]["schemas"]

    for response_schema_name in (
        "PerformanceResponse",
        "WorkspaceSummaryResponse",
        "ContributionResponse",
        "AttributionResponse",
    ):
        schema = schemas[response_schema_name]
        assert "currency_evidence" in schema["properties"]
        assert "currency_evidence" in schema["required"]

    evidence_properties = schemas["AppliedCurrencyEvidence"]["properties"]
    for field_name in (
        "portfolio_base_currency",
        "requested_report_ccy",
        "applied_report_ccy",
        "restated",
        "currency_mode_applied",
        "fx_source",
        "fx_coverage",
        "fixing_policy",
        "applied_pairs",
        "reason",
    ):
        assert evidence_properties[field_name]["description"]
