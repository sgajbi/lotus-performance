import json
from pathlib import Path

from app.api.endpoints.integration_capabilities import IntegrationCapabilitiesResponse

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_integration_capabilities_response_schema_includes_certified_surface_example():
    schema = IntegrationCapabilitiesResponse.model_json_schema()
    example = schema["examples"][0]
    surfaces = {surface["key"]: surface for surface in example["analytics_surfaces"]}
    features = {feature["key"] for feature in example["features"]}
    workflows = {workflow["workflow_key"] for workflow in example["workflows"]}

    assert example["contract_version"] == "v1"
    assert set(surfaces) == {
        "twr",
        "twr_inspection",
        "mwr",
        "benchmark",
        "workspace_summary",
        "contribution",
        "attribution",
        "returns_series",
        "benchmark_exposure_context",
    }
    assert surfaces["workspace_summary"]["poll_path_template"] == "/performance/executions/{calculation_id}"
    assert surfaces["workspace_summary"]["options"][0]["key"] == "benchmark_mode"
    assert surfaces["twr"]["contract_notes"] == [
        "supports portfolio-level TWR only",
        "does not advertise composite, group, or sleeve TWR calculation support",
    ]
    assert "performance.analytics.workspace_summary" in features
    assert "performance_workspace" in workflows


def test_integration_capabilities_json_example_matches_schema_example():
    example_file = json.loads(
        (REPO_ROOT / "docs/examples/integration_capabilities_response.json").read_text(encoding="utf-8")
    )
    schema_example = IntegrationCapabilitiesResponse.model_json_schema()["examples"][0]

    assert example_file == schema_example
