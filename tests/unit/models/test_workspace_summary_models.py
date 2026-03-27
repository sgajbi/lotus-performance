import json
from pathlib import Path

import pytest

from app.models.benchmark_analytics_requests import BenchmarkInputMode
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


def _base_stateless_payload() -> dict[str, object]:
    return {
        "portfolio_id": "WORKSPACE_SUMMARY_01",
        "report_end_date": "2026-03-31",
        "performance_start_date": "2025-12-31",
        "input_mode": "stateless",
        "periods": [{"period": "1M", "frequencies": ["daily"]}],
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2026-03-31", "begin_mv": 1000000.0, "end_mv": 1008500.0},
            ]
        },
    }


def _base_stateful_payload() -> dict[str, object]:
    return {
        "portfolio_id": "WORKSPACE_SUMMARY_STATEFUL_01",
        "report_end_date": "2026-03-31",
        "input_mode": "stateful",
        "periods": [{"period": "1M", "frequencies": ["daily"]}],
        "stateful_input": {},
    }


def test_workspace_summary_request_rejects_empty_frequency_list():
    payload = _base_stateless_payload()
    payload["periods"] = [{"period": "1M", "frequencies": []}]

    with pytest.raises(ValueError, match="frequencies list cannot be empty"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_empty_periods():
    payload = _base_stateless_payload()
    payload["periods"] = []

    with pytest.raises(ValueError, match="periods list cannot be empty"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_explicit_period_without_report_start_date():
    payload = _base_stateless_payload()
    payload["periods"] = [{"period": "EXPLICIT", "frequencies": ["daily"]}]

    with pytest.raises(ValueError, match="report_start_date is required when periods include EXPLICIT"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_stateless_request_without_performance_start_date():
    payload = _base_stateless_payload()
    payload.pop("performance_start_date")

    with pytest.raises(ValueError, match="performance_start_date is required when input_mode=stateless"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_stateless_request_with_both_legacy_and_nested_payloads():
    payload = _base_stateless_payload()
    payload["valuation_points"] = [{"perf_date": "2026-03-31", "begin_mv": 1000000.0, "end_mv": 1008500.0}]

    with pytest.raises(ValueError, match="Provide either stateless_input or valuation_points, not both"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_stateless_request_without_any_valuation_input():
    payload = _base_stateless_payload()
    payload.pop("stateless_input")

    with pytest.raises(ValueError, match="stateless_input or valuation_points is required"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_stateful_payloads_on_stateless_request():
    payload = _base_stateless_payload()
    payload["stateful_input"] = {}

    with pytest.raises(ValueError, match="stateful_input must be null when input_mode=stateless"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_stateful_request_without_stateful_input():
    payload = _base_stateful_payload()
    payload.pop("stateful_input")

    with pytest.raises(ValueError, match="stateful_input is required when input_mode=stateful"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_stateless_payloads_on_stateful_request():
    payload = _base_stateful_payload()
    payload["stateless_input"] = {
        "valuation_points": [{"perf_date": "2026-03-31", "begin_mv": 1000000.0, "end_mv": 1008500.0}]
    }

    with pytest.raises(ValueError, match="stateless_input must be null when input_mode=stateful"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_legacy_valuation_points_on_stateful_request():
    payload = _base_stateful_payload()
    payload["valuation_points"] = [{"perf_date": "2026-03-31", "begin_mv": 1000000.0, "end_mv": 1008500.0}]

    with pytest.raises(ValueError, match="valuation_points must be null when input_mode=stateful"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_requires_benchmark_when_stateless_include_benchmark_enabled():
    payload = _base_stateless_payload()
    payload["include_benchmark"] = True

    with pytest.raises(ValueError, match="benchmark configuration is required when include_benchmark=true"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_requires_shared_segmentation_for_detail_blocks():
    payload = _base_stateful_payload()
    payload["contribution"] = {"metric_basis": "NET"}

    with pytest.raises(ValueError, match="segmentation is required when contribution or attribution"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_detail_blocks_in_stateless_mode():
    payload = _base_stateless_payload()
    payload["segmentation"] = {"group_by": ["sector"]}
    payload["contribution"] = {"metric_basis": "NET"}

    with pytest.raises(ValueError, match="workspace contribution and attribution summary blocks currently require"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_non_stateful_benchmark_for_attribution():
    payload = _base_stateful_payload()
    payload["segmentation"] = {"group_by": ["sector"]}
    payload["attribution"] = {"metric_basis": "NET"}
    payload["benchmark"] = {
        "input_mode": "stateless",
        "benchmark_id": "BMK_1",
        "stateless_input": {
            "benchmark_currency": "USD",
            "benchmark_return_points": [{"perf_date": "2026-03-31", "benchmark_return": 0.01}],
        },
    }

    with pytest.raises(ValueError, match="workspace attribution summary currently supports only"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_forces_include_benchmark_when_benchmark_or_attribution_present():
    payload = _base_stateful_payload()
    payload["benchmark"] = {"input_mode": "stateful", "stateful_input": {}}
    request = WorkspaceSummaryRequest.model_validate(payload)

    assert request.include_benchmark is True

    payload = _base_stateful_payload()
    payload["segmentation"] = {"group_by": ["sector"]}
    payload["attribution"] = {"metric_basis": "NET"}
    request = WorkspaceSummaryRequest.model_validate(payload)

    assert request.include_benchmark is True


def test_workspace_summary_request_resolves_legacy_stateless_valuation_points():
    payload = _base_stateless_payload()
    legacy_points = [{"perf_date": "2026-03-31", "begin_mv": 1000000.0, "end_mv": 1008500.0}]
    payload.pop("stateless_input")
    payload["valuation_points"] = legacy_points

    request = WorkspaceSummaryRequest.model_validate(payload)

    assert request.resolved_stateless_valuation_points()[0].perf_date.isoformat() == "2026-03-31"


def test_workspace_summary_request_rejects_duplicate_segmentation_dimensions():
    payload = _base_stateful_payload()
    payload["segmentation"] = {"group_by": ["sector", "sector"]}
    payload["contribution"] = {"metric_basis": "NET"}

    with pytest.raises(ValueError, match="segmentation.group_by cannot contain duplicates"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_summary_request_rejects_empty_segmentation_dimensions():
    payload = _base_stateful_payload()
    payload["segmentation"] = {"group_by": []}
    payload["contribution"] = {"metric_basis": "NET"}

    with pytest.raises(ValueError, match="segmentation.group_by cannot be empty"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_benchmark_request_validates_mode_specific_requirements():
    payload = _base_stateful_payload()
    payload["include_benchmark"] = True
    payload["benchmark"] = {"input_mode": "stateless"}

    with pytest.raises(ValueError, match="benchmark.stateless_input is required"):
        WorkspaceSummaryRequest.model_validate(payload)

    payload = _base_stateful_payload()
    payload["include_benchmark"] = True
    payload["benchmark"] = {
        "input_mode": BenchmarkInputMode.STATEFUL.value,
        "stateful_input": {},
        "stateless_input": {"benchmark_currency": "USD", "benchmark_return_points": []},
    }

    with pytest.raises(ValueError, match="benchmark.stateless_input must be null when benchmark.input_mode=stateful"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_benchmark_request_rejects_stateful_payload_on_stateless_mode():
    payload = _base_stateful_payload()
    payload["include_benchmark"] = True
    payload["benchmark"] = {
        "input_mode": "stateless",
        "benchmark_id": "BMK_1",
        "stateful_input": {},
        "stateless_input": {
            "benchmark_currency": "USD",
            "benchmark_return_points": [{"perf_date": "2026-03-31", "benchmark_return": 0.01}],
        },
    }

    with pytest.raises(ValueError, match="benchmark.stateful_input must be null when benchmark.input_mode=stateless"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_benchmark_request_rejects_missing_benchmark_id_in_stateless_mode():
    payload = _base_stateful_payload()
    payload["include_benchmark"] = True
    payload["benchmark"] = {
        "input_mode": "stateless",
        "stateless_input": {
            "benchmark_currency": "USD",
            "benchmark_return_points": [{"perf_date": "2026-03-31", "benchmark_return": 0.01}],
        },
    }

    with pytest.raises(ValueError, match="benchmark.benchmark_id is required when benchmark.input_mode=stateless"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_workspace_benchmark_request_defaults_stateful_payload_when_omitted():
    payload = _base_stateful_payload()
    payload["include_benchmark"] = True
    payload["benchmark"] = {"input_mode": "stateful"}

    request = WorkspaceSummaryRequest.model_validate(payload)

    assert request.benchmark is not None
    assert request.benchmark.stateful_input is not None
