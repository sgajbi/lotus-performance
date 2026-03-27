import json
from pathlib import Path

from app.api.endpoints.integration_capabilities import IntegrationCapabilitiesResponse

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_integration_capabilities_response_schema_includes_workspace_summary_example():
    schema = IntegrationCapabilitiesResponse.model_json_schema()
    example = schema["examples"][0]

    assert example["contract_version"] == "v1"
    assert example["analytics_surfaces"][0]["key"] == "workspace_summary"
    assert example["analytics_surfaces"][0]["poll_path_template"] == "/performance/executions/{calculation_id}"
    assert example["analytics_surfaces"][0]["options"][0]["key"] == "benchmark_mode"
    assert example["features"][0]["key"] == "pa.analytics.workspace_summary"
    assert example["workflows"][0]["workflow_key"] == "performance_workspace"


def test_integration_capabilities_json_example_matches_schema_example():
    example_file = json.loads(
        (REPO_ROOT / "docs/examples/integration_capabilities_response.json").read_text(encoding="utf-8")
    )
    schema_example = IntegrationCapabilitiesResponse.model_json_schema()["examples"][0]

    assert example_file == schema_example
