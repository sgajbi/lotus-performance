from main import app


def test_attribution_openapi_documents_private_banking_usage_and_error_paths() -> None:
    spec = app.openapi()

    attribution_post = spec["paths"]["/performance/attribution"]["post"]

    assert "portfolio active return versus a benchmark" in attribution_post["description"]
    assert "front-office users" in attribution_post["description"]
    assert "lotus-core analytics-input contracts" in attribution_post["description"]
    assert "downstream systems should not infer totals" in attribution_post["description"]
    for status_code in ("202", "400", "409", "422", "500"):
        assert status_code in attribution_post["responses"]
    assert "poll_path" in str(attribution_post["responses"]["202"])
    assert "missing FX" in attribution_post["responses"]["422"]["description"]
    assert "unsupported grouping dimension" in attribution_post["responses"]["422"]["description"]
    assert "unexpected attribution request resolution" in attribution_post["responses"]["500"]["description"].lower()

    attribution_result = spec["paths"]["/performance/attribution/results/{calculation_id}"]["get"]
    assert "previously accepted" in attribution_result["description"]
    for status_code in ("202", "404", "409"):
        assert status_code in attribution_result["responses"]
    assert "Async attribution result not found" in str(attribution_result["responses"]["404"])


def test_attribution_openapi_documents_status_reason_and_supportability_fields() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    request_schema = schemas["AttributionAnalyticsRequest"]
    request_example = request_schema["examples"][0]
    assert request_example["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert request_example["input_mode"] == "stateful"
    assert request_example["stateful_input"]["dimensions"] == ["asset_class", "sector"]

    response_schema = schemas["AttributionResponse"]
    response_example = response_schema["examples"][0]
    assert response_example["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert response_example["results_by_period"]["ITD"]["status"] == "partial"
    assert response_example["results_by_period"]["ITD"]["reason_codes"] == ["off_benchmark_exposure"]

    period_schema = schemas["SinglePeriodAttributionResult"]
    for field_name in ("status", "reason_codes", "reasons", "supportability_evidence"):
        assert field_name in period_schema["properties"]
        assert period_schema["properties"][field_name]["description"]

    evidence_schema = schemas["AttributionSupportabilityEvidence"]
    for field_name in (
        "portfolio_only_group_count",
        "benchmark_only_group_count",
        "unclassified_group_count",
        "missing_benchmark_return_count",
        "negative_weight_count",
        "zero_portfolio_exposure_count",
        "currency_attribution_status",
        "linking_status",
    ):
        assert field_name in evidence_schema["properties"]
        assert evidence_schema["properties"][field_name]["description"]
    assert evidence_schema["examples"][0]["currency_attribution_status"] == "not_requested"

    reconciliation_schema = schemas["Reconciliation"]
    assert "residual_materiality" in reconciliation_schema["properties"]
    assert "reviewable breaks" in reconciliation_schema["properties"]["residual_materiality"]["description"]
