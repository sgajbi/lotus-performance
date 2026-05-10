from main import app


def test_twr_openapi_documents_async_execution_contract() -> None:
    spec = app.openapi()

    twr_post = spec["paths"]["/performance/twr"]["post"]
    assert "time-weighted return" in twr_post["description"].lower()
    assert "stateful lotus-core-sourced" in twr_post["description"]
    assert "202" in twr_post["responses"]
    assert "poll_path" in str(twr_post["responses"]["202"])
    assert "result_path" in str(twr_post["responses"]["202"])
    response_schema = spec["components"]["schemas"]["PerformanceResponse"]
    assert "calculation_supportability" in response_schema["properties"]
    supportability_schema = spec["components"]["schemas"]["PerformanceCalculationSupportability"]
    assert supportability_schema["properties"]["state"]["description"].startswith("Bounded supportability state")
    assert "freshness_bucket" in supportability_schema["properties"]
    assert "source_quality_evidence" in supportability_schema["properties"]
    benchmark_context_schema = spec["components"]["schemas"]["TWRBenchmarkContext"]
    assert "supportability_evidence" in benchmark_context_schema["properties"]
    benchmark_evidence_schema = spec["components"]["schemas"]["TWRBenchmarkSupportabilityEvidence"]
    assert (
        "FX, and calendar supportability warning codes"
        in benchmark_evidence_schema["properties"]["warning_codes"]["description"]
    )
    assert (
        "Portfolio and benchmark daily observation date alignment state"
        in benchmark_evidence_schema["properties"]["calendar_alignment_state"]["description"]
    )
    source_quality_schema = spec["components"]["schemas"]["PerformanceSourceQualityEvidence"]
    assert "unsupported for TWR" in source_quality_schema["properties"]["unsupported_cashflow_count"]["description"]
    assert "source-quality warning codes" in source_quality_schema["properties"]["warnings"]["description"]
    breakdown_item_schema = spec["components"]["schemas"]["ComparativeBreakdownItem"]
    assert "calculation_evidence" in breakdown_item_schema["properties"]
    assert (
        "implementation-backed daily twr calculation evidence"
        in str(breakdown_item_schema["properties"]["calculation_evidence"]).lower()
    )
    evidence_schema = spec["components"]["schemas"]["TWRDailyCalculationEvidence"]
    evidence_properties = evidence_schema["properties"]
    assert evidence_properties["calculation_method"]["description"] == "Daily TWR method used for this portfolio day."
    assert "Capital denominator convention" in evidence_properties["denominator_basis"]["description"]
    assert "External flow timing convention" in evidence_properties["flow_timing_convention"]["description"]
    assert (
        "before applying the absolute denominator policy"
        in evidence_properties["signed_adjusted_capital"]["description"]
    )
    assert "percentage-point output units" in evidence_properties["daily_return"]["description"]
    assert "geometric linking" in evidence_properties["linkability_status"]["description"]
    assert "TWR episode classification" in evidence_properties["episode_status"]["description"]
    assert "reason_codes" in evidence_properties
    assert "warnings" in evidence_properties

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
    assert "support_brief.md" in artifact_route["parameters"][1]["description"]
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
    assert response_example["artifacts"]["support_brief.md"].endswith("/artifacts/support_brief.md")
    assert response_example["artifacts"]["source_economics_summary.json"].endswith(
        "/artifacts/source_economics_summary.json"
    )
    assert (
        response_schema["properties"]["findings"]["description"]
        == "Ordered supportability findings with owner, severity, recommended action, and evidence."
    )
    assert "workflow_pack_run" in response_schema["properties"]
    assert response_example["workflow_pack_run"]["workflow_authority_owner"] == "lotus-performance"

    finding_schema = schemas["TWRInspectionFinding"]
    finding_example = finding_schema["examples"][0]
    assert finding_example["code"] == "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH"
    assert finding_schema["properties"]["owner_repo"]["examples"] == ["lotus-performance"]
    assert finding_schema["properties"]["evidence"]["description"] == (
        "Structured finding-specific evidence. Shape varies by finding code."
    )
