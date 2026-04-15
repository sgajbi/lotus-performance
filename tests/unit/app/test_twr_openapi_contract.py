from main import app


def test_twr_openapi_documents_async_execution_contract() -> None:
    spec = app.openapi()

    twr_post = spec["paths"]["/performance/twr"]["post"]
    assert "time-weighted return" in twr_post["description"].lower()
    assert "stateful lotus-core-sourced" in twr_post["description"]
    assert "202" in twr_post["responses"]
    assert "poll_path" in str(twr_post["responses"]["202"])
    assert "result_path" in str(twr_post["responses"]["202"])

    twr_result = spec["paths"]["/performance/twr/results/{calculation_id}"]["get"]
    assert "previously returned 202 Accepted" in twr_result["description"]
    assert "202" in twr_result["responses"]
    assert "404" in twr_result["responses"]


def test_twr_inspection_openapi_explains_supportability_purpose() -> None:
    spec = app.openapi()

    inspection_post = spec["paths"]["/performance/inspections/twr"]["post"]
    assert "supportability inspection" in inspection_post["description"]
    assert "source-quality" in inspection_post["description"]
    assert "source-economics" in inspection_post["description"]
    assert "reconciliation" in inspection_post["description"]

    inspection_result = spec["paths"]["/performance/inspections/{inspection_id}"]["get"]
    assert "supportability inspection" in inspection_result["description"]
    assert "202" in inspection_result["responses"]
    assert "404" in inspection_result["responses"]

    artifact_route = spec["paths"]["/performance/inspections/{inspection_id}/artifacts/{artifact_name}"]["get"]
    assert "evidence artifact" in artifact_route["summary"].lower()
    assert "Only artifact names recorded" in artifact_route["description"]
    assert "source_economics_summary.json" in artifact_route["parameters"][1]["description"]
    assert "404" in artifact_route["responses"]
    assert "503" in artifact_route["responses"]


def test_twr_inspection_openapi_uses_domain_specific_schema_examples() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    request_schema = schemas["TWRInspectionRequest"]
    request_example = request_schema["examples"][0]
    assert request_example["subject_type"] == "twr_calculation"
    assert request_example["inspection_profile"] == "support_triage"
    assert request_schema["properties"]["request"]["description"].startswith("Fresh TWR request to inspect")

    response_schema = schemas["TWRInspectionResponse"]
    response_example = response_schema["examples"][0]
    assert response_example["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert response_example["artifacts"]["source_economics_summary.json"].endswith(
        "/artifacts/source_economics_summary.json"
    )
    assert (
        response_schema["properties"]["findings"]["description"]
        == "Ordered supportability findings with owner, severity, recommended action, and evidence."
    )

    finding_schema = schemas["TWRInspectionFinding"]
    finding_example = finding_schema["examples"][0]
    assert finding_example["code"] == "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH"
    assert finding_schema["properties"]["owner_repo"]["examples"] == ["lotus-performance"]
    assert finding_schema["properties"]["evidence"]["description"] == (
        "Structured finding-specific evidence. Shape varies by finding code."
    )
