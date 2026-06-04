from __future__ import annotations

from main import app


def test_lineage_openapi_documents_inventory_and_artifact_routes() -> None:
    spec = app.openapi()
    lineage_get = spec["paths"]["/performance/lineage/{calculation_id}"]["get"]
    artifact_get = spec["paths"]["/performance/lineage/{calculation_id}/artifacts/{artifact_name}"]["get"]

    assert "controlled download URLs" in lineage_get["description"]
    assert "manifest that matches durable metadata" in lineage_get["description"]
    assert "404" in lineage_get["responses"]
    assert "503" in lineage_get["responses"]
    lineage_404_schema = lineage_get["responses"]["404"]["content"]["application/json"]["schema"]
    lineage_503_schema = lineage_get["responses"]["503"]["content"]["application/json"]["schema"]
    assert lineage_404_schema["$ref"].endswith("/ErrorDetailResponse")
    assert lineage_503_schema["$ref"].endswith("/ErrorDetailResponse")
    assert lineage_get["parameters"][0]["name"] == "calculation_id"
    assert "Durable calculation identifier" in lineage_get["parameters"][0]["description"]

    assert "Downloads a lineage artifact" in artifact_get["description"]
    assert "Only artifacts declared by durable lineage metadata" in artifact_get["description"]
    assert "200" in artifact_get["responses"]
    assert "404" in artifact_get["responses"]
    assert "503" in artifact_get["responses"]
    artifact_404_schema = artifact_get["responses"]["404"]["content"]["application/json"]["schema"]
    artifact_503_schema = artifact_get["responses"]["503"]["content"]["application/json"]["schema"]
    assert artifact_404_schema["$ref"].endswith("/ErrorDetailResponse")
    assert artifact_503_schema["$ref"].endswith("/ErrorDetailResponse")
    assert [parameter["name"] for parameter in artifact_get["parameters"]] == ["calculation_id", "artifact_name"]


def test_lineage_response_schema_documents_artifact_contract() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    response_schema = schemas["LineageResponse"]
    artifact_schema = schemas["ArtifactLink"]

    for field_name in [
        "calculation_id",
        "calculation_type",
        "timestamp_utc",
        "status",
        "artifacts",
        "error_message",
    ]:
        assert response_schema["properties"][field_name]["description"]

    assert artifact_schema["properties"]["url"]["description"]
    assert response_schema["properties"]["calculation_type"]["examples"] == ["TWR"]
    assert response_schema["properties"]["status"]["examples"] == ["complete"]
    assert "request.json" in str(response_schema["properties"]["artifacts"]["examples"])
