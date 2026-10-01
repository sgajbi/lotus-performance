from main import app


def test_group_return_evidence_openapi_declares_the_versioned_economic_and_lineage_contract() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/integration/attribution/group-return-evidence/v1"]["post"]
    response_schema = schema["components"]["schemas"]["GroupReturnEvidenceResponse"]
    snapshot_schema = schema["components"]["schemas"]["GroupReturnEvidenceSourceSnapshot"]

    assert operation["summary"] == "Publish source-owned group-return evidence for empirical active-risk attribution"
    assert "does not calculate risk attribution" in operation["description"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/GroupReturnEvidenceRequest"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/GroupReturnEvidenceResponse"
    )
    assert {
        "return_basis",
        "valuation_basis",
        "weight_basis",
        "coverage",
        "aggregate_returns",
        "source_lineage",
    }.issubset(response_schema["properties"])
    assert "as_of_date" in snapshot_schema["properties"]
