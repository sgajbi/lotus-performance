import json
from pathlib import Path

from app.api.endpoints.integration_capabilities import IntegrationCapabilitiesResponse
from app.services.integration_capabilities_service import build_integration_capabilities_report

REPO_ROOT = Path(__file__).resolve().parents[3]
CAPABILITY_ENV_VARS = (
    "PA_CAP_TWR_ENABLED",
    "PA_CAP_MWR_ENABLED",
    "PA_CAP_CONTRIBUTION_ENABLED",
    "PA_CAP_ATTRIBUTION_ENABLED",
    "PA_CAP_BENCHMARK_ENABLED",
    "PA_CAP_WORKSPACE_SUMMARY_ENABLED",
    "PA_CAP_COMPOSITE_TWR_ENABLED",
    "PLATFORM_INPUT_MODE_STATEFUL_ENABLED",
    "PLATFORM_INPUT_MODE_STATELESS_ENABLED",
    "PA_POLICY_VERSION",
)


def _index_by_key(rows: list[dict[str, object]], key: str) -> dict[object, dict[str, object]]:
    return {row[key]: row for row in rows}


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
        "composite_twr",
        "mandate_performance_health_context",
        "returns_series",
        "benchmark_exposure_context",
    }
    assert surfaces["workspace_summary"]["poll_path_template"] == "/performance/executions/{calculation_id}"
    assert surfaces["workspace_summary"]["options"][0]["key"] == "benchmark_mode"
    assert surfaces["twr"]["contract_notes"] == [
        "supports portfolio-level TWR only",
        "does not advertise composite, group, or sleeve TWR calculation support",
    ]
    assert surfaces["composite_twr"]["supported_input_modes"] == ["persisted_member_facts"]
    assert surfaces["composite_twr"]["contract_notes"] == [
        "calculates composite TWR only from persisted member-return facts",
        "does not accept ad hoc member returns or hidden request-time portfolio TWR fan-out",
        "does not advertise composite contribution, attribution, MWR, benchmark active return, or special composite structures",
    ]
    assert "performance.analytics.composite_twr" in features
    assert "performance.analytics.workspace_summary" in features
    assert "performance.integration.mandate_performance_health_context" in features
    assert "performance_workspace" in workflows
    assert "composite_performance_publication" in workflows
    assert "mandate_performance_health_context" in workflows


def test_integration_capabilities_json_example_matches_schema_example():
    example_file = json.loads(
        (REPO_ROOT / "docs/examples/integration_capabilities_response.json").read_text(encoding="utf-8")
    )
    schema_example = IntegrationCapabilitiesResponse.model_json_schema()["examples"][0]

    assert example_file == schema_example


def test_integration_capabilities_schema_example_matches_runtime_contract_fields(monkeypatch):
    for env_var in CAPABILITY_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)
    schema_example = IntegrationCapabilitiesResponse.model_json_schema()["examples"][0]
    runtime_report = build_integration_capabilities_report()

    assert schema_example["supported_input_modes"] == runtime_report.supported_input_modes

    example_surfaces = _index_by_key(schema_example["analytics_surfaces"], "key")
    runtime_surfaces = _index_by_key(runtime_report.analytics_surfaces, "key")
    assert set(example_surfaces) == set(runtime_surfaces)
    for surface_key, runtime_surface in runtime_surfaces.items():
        example_surface = example_surfaces[surface_key]
        for field in (
            "path",
            "enabled",
            "supported_input_modes",
            "supports_async",
            "poll_path_template",
            "result_path_template",
            "stateful_restrictions",
            "contract_notes",
            "options",
        ):
            assert example_surface.get(field) == runtime_surface.get(field)

    example_features = _index_by_key(schema_example["features"], "key")
    runtime_features = _index_by_key(runtime_report.features, "key")
    assert example_features == runtime_features

    example_workflows = _index_by_key(schema_example["workflows"], "workflow_key")
    runtime_workflows = _index_by_key(runtime_report.workflows, "workflow_key")
    assert example_workflows == runtime_workflows
