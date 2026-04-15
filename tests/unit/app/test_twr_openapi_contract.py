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
