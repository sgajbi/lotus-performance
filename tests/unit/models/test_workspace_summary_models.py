import json
from pathlib import Path

from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.models.workspace_summary_responses import WorkspaceSummaryAcceptedResponse, WorkspaceSummaryResponse

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_workspace_summary_request_schema_includes_stateless_and_stateful_examples():
    schema = WorkspaceSummaryRequest.model_json_schema()
    examples = schema["examples"]

    assert len(examples) == 2
    assert examples[0]["input_mode"] == "stateless"
    assert examples[0]["include_benchmark"] is True
    assert examples[0]["benchmark"]["input_mode"] == "stateless"
    assert examples[1]["input_mode"] == "stateful"
    assert examples[1]["segmentation"]["group_by"] == ["sector", "country"]
    assert examples[1]["contribution"]["top_positions"] == 5
    assert examples[1]["attribution"]["metric_basis"] == "NET"


def test_workspace_summary_response_schema_includes_workspace_detail_example():
    schema = WorkspaceSummaryResponse.model_json_schema()
    example = schema["examples"][0]

    assert example["results_by_period"]["YTD"]["portfolio_twr"]["net"]["summary"]["period_return"]["base"] == 3.41
    assert example["results_by_period"]["YTD"]["portfolio_twr"]["net"]["summary"]["annualized_return"]["base"] == 3.41
    assert example["results_by_period"]["YTD"]["benchmark"]["summary"]["cumulative_return"]["base"] == 2.98
    assert example["results_by_period"]["YTD"]["active"]["net"]["cumulative_return"]["base"] == 0.43
    assert example["results_by_period"]["YTD"]["money_weighted_return"]["period_return"] == 3.27
    assert example["results_by_period"]["YTD"]["contribution"]["segmentation"] == ["sector", "country"]
    assert example["results_by_period"]["YTD"]["attribution"]["benchmark_context"]["benchmark_id"] == "BMK_GLOBAL_60_40"
    assert example["audit"]["counts"]["workspace_detail_block_count"] == 2


def test_workspace_summary_accepted_response_schema_includes_polling_example():
    schema = WorkspaceSummaryAcceptedResponse.model_json_schema()
    example = schema["examples"][0]

    assert example["poll_path"].startswith("/performance/executions/")
    assert example["result_path"].startswith("/performance/workspace-summary/results/")


def test_workspace_summary_json_examples_match_schema_examples():
    stateless_example = json.loads(
        (REPO_ROOT / "docs/examples/workspace_summary_request.json").read_text(encoding="utf-8")
    )
    stateful_detail_example = json.loads(
        (REPO_ROOT / "docs/examples/workspace_summary_stateful_detail_request.json").read_text(encoding="utf-8")
    )
    schema_examples = WorkspaceSummaryRequest.model_json_schema()["examples"]

    assert schema_examples[0] == stateless_example
    assert schema_examples[1] == stateful_detail_example


def test_workspace_summary_accepted_response_json_example_matches_schema_example():
    accepted_example = json.loads(
        (REPO_ROOT / "docs/examples/workspace_summary_accepted_response.json").read_text(encoding="utf-8")
    )
    schema_example = WorkspaceSummaryAcceptedResponse.model_json_schema()["examples"][0]

    assert accepted_example == schema_example
