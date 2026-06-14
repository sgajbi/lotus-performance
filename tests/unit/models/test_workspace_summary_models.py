import json
from datetime import date
from pathlib import Path

import pytest

from app.models.benchmark_analytics_requests import BenchmarkInputMode
from app.models.twr_requests import TWRInputMode
from app.models.workspace_summary_requests import (
    WorkspaceBenchmarkRequest,
    WorkspaceSummaryRequest,
    _has_exactly_one_workspace_summary_stateless_payload,
    _has_legacy_workspace_summary_valuation_points,
    _has_nested_workspace_summary_stateless_input,
    _requested_workspace_periods,
    _resolve_workspace_summary_include_benchmark,
    _validate_workspace_stateful_benchmark_payload,
    _validate_workspace_stateless_benchmark_payload,
    _validate_workspace_summary_benchmark_request,
    _validate_workspace_summary_stateless_inputs,
    _workspace_summary_stateless_envelope_issue,
)
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
    assert "segmentation" not in examples[1]
    assert "contribution" not in examples[1]
    assert "attribution" not in examples[1]


def test_workspace_summary_response_schema_includes_workspace_summary_example():
    schema = WorkspaceSummaryResponse.model_json_schema()
    example = schema["examples"][0]

    assert example["results_by_period"]["YTD"]["portfolio_twr"]["net"]["summary"]["period_return"]["base"] == 3.41
    assert example["results_by_period"]["YTD"]["portfolio_twr"]["net"]["summary"]["annualized_return"]["base"] == 3.41
    assert example["results_by_period"]["YTD"]["benchmark"]["summary"]["cumulative_return"]["base"] == 2.98
    assert example["results_by_period"]["YTD"]["active"]["net"]["cumulative_return"]["base"] == 0.43
    assert example["results_by_period"]["YTD"]["money_weighted_return"]["period_return"] == 3.27
    assert "contribution" not in example["results_by_period"]["YTD"]
    assert "attribution" not in example["results_by_period"]["YTD"]
    assert "workspace_detail_block_count" not in example["audit"]["counts"]


def test_workspace_summary_accepted_response_schema_includes_polling_example():
    schema = WorkspaceSummaryAcceptedResponse.model_json_schema()
    example = schema["examples"][0]

    assert example["poll_path"].startswith("/performance/executions/")
    assert example["result_path"].startswith("/performance/workspace-summary/results/")


def test_workspace_summary_json_examples_match_schema_examples():
    stateless_example = json.loads(
        (REPO_ROOT / "docs/examples/workspace_summary_request.json").read_text(encoding="utf-8")
    )
    stateful_summary_example = json.loads(
        (REPO_ROOT / "docs/examples/workspace_summary_stateful_detail_request.json").read_text(encoding="utf-8")
    )
    schema_examples = WorkspaceSummaryRequest.model_json_schema()["examples"]

    assert schema_examples[0] == stateless_example
    assert schema_examples[1] == stateful_summary_example


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


def test_requested_workspace_periods_returns_distinct_period_codes():
    request = WorkspaceSummaryRequest.model_validate(_base_stateless_payload())

    assert _requested_workspace_periods(request) == {request.periods[0].period}


def test_workspace_summary_request_rejects_explicit_period_without_report_start_date():
    payload = _base_stateless_payload()
    payload["periods"] = [{"period": "EXPLICIT", "frequencies": ["daily"]}]

    with pytest.raises(ValueError, match="report_start_date is required when periods include EXPLICIT"):
        WorkspaceSummaryRequest.model_validate(payload)


def test_validate_workspace_summary_stateless_inputs_rejects_dual_payloads():
    request = WorkspaceSummaryRequest.model_construct(
        input_mode=TWRInputMode.STATELESS,
        performance_start_date=date(2026, 1, 1),
        stateless_input=object(),
        valuation_points=[object()],
        stateful_input=None,
    )

    with pytest.raises(ValueError, match="Provide either stateless_input or valuation_points"):
        _validate_workspace_summary_stateless_inputs(request)


@pytest.mark.parametrize(
    ("stateless_input", "valuation_points", "has_nested", "has_legacy", "has_exactly_one"),
    [
        (object(), [], True, False, True),
        (None, [object()], False, True, True),
        (None, [], False, False, False),
        (object(), [object()], True, True, False),
    ],
)
def test_workspace_summary_stateless_payload_shape_predicates(
    stateless_input,
    valuation_points,
    has_nested,
    has_legacy,
    has_exactly_one,
):
    request = WorkspaceSummaryRequest.model_construct(
        input_mode=TWRInputMode.STATELESS,
        performance_start_date=date(2026, 1, 1),
        stateless_input=stateless_input,
        valuation_points=valuation_points,
        stateful_input=None,
    )

    assert _has_nested_workspace_summary_stateless_input(request) is has_nested
    assert _has_legacy_workspace_summary_valuation_points(request) is has_legacy
    assert _has_exactly_one_workspace_summary_stateless_payload(request) is has_exactly_one


def test_workspace_summary_stateless_envelope_issue_requires_exactly_one_payload_shape():
    assert _workspace_summary_stateless_envelope_issue(has_nested=True, has_legacy=False) is None
    assert _workspace_summary_stateless_envelope_issue(has_nested=False, has_legacy=True) is None
    assert _workspace_summary_stateless_envelope_issue(has_nested=True, has_legacy=True) == (
        "Provide either stateless_input or valuation_points, not both, for stateless mode"
    )
    assert _workspace_summary_stateless_envelope_issue(has_nested=False, has_legacy=False) == (
        "stateless_input or valuation_points is required when input_mode=stateless"
    )


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


def test_workspace_summary_request_forces_include_benchmark_when_benchmark_or_attribution_present():
    payload = _base_stateful_payload()
    payload["benchmark"] = {"input_mode": "stateful", "stateful_input": {}}
    request = WorkspaceSummaryRequest.model_validate(payload)

    assert request.include_benchmark is True


def test_resolve_workspace_summary_include_benchmark_promotes_present_benchmark():
    request = WorkspaceSummaryRequest.model_construct(include_benchmark=False, benchmark=object())

    assert _resolve_workspace_summary_include_benchmark(request) is True


def test_validate_workspace_summary_benchmark_request_rejects_stateless_missing_benchmark():
    request = WorkspaceSummaryRequest.model_construct(
        include_benchmark=True,
        input_mode=TWRInputMode.STATELESS,
        benchmark=None,
    )

    with pytest.raises(ValueError, match="benchmark configuration is required"):
        _validate_workspace_summary_benchmark_request(request)


def test_workspace_summary_request_resolves_legacy_stateless_valuation_points():
    payload = _base_stateless_payload()
    legacy_points = [{"perf_date": "2026-03-31", "begin_mv": 1000000.0, "end_mv": 1008500.0}]
    payload.pop("stateless_input")
    payload["valuation_points"] = legacy_points

    request = WorkspaceSummaryRequest.model_validate(payload)

    assert request.resolved_stateless_valuation_points()[0].perf_date.isoformat() == "2026-03-31"


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


def test_workspace_benchmark_payload_helpers_preserve_mode_policy():
    stateless_request = WorkspaceBenchmarkRequest.model_construct(
        input_mode=BenchmarkInputMode.STATELESS,
        benchmark_id="BMK_1",
        stateless_input=object(),
        stateful_input=None,
    )
    stateful_request = WorkspaceBenchmarkRequest.model_construct(
        input_mode=BenchmarkInputMode.STATEFUL,
        stateless_input=None,
        stateful_input=None,
    )

    _validate_workspace_stateless_benchmark_payload(stateless_request)
    _validate_workspace_stateful_benchmark_payload(stateful_request)

    assert stateful_request.stateful_input is not None


def test_workspace_benchmark_payload_helpers_reject_cross_mode_payloads():
    with pytest.raises(ValueError, match="benchmark.benchmark_id is required"):
        _validate_workspace_stateless_benchmark_payload(
            WorkspaceBenchmarkRequest.model_construct(
                input_mode=BenchmarkInputMode.STATELESS,
                benchmark_id=None,
                stateless_input=object(),
                stateful_input=None,
            )
        )
    with pytest.raises(ValueError, match="benchmark.stateless_input must be null"):
        _validate_workspace_stateful_benchmark_payload(
            WorkspaceBenchmarkRequest.model_construct(
                input_mode=BenchmarkInputMode.STATEFUL,
                stateless_input=object(),
                stateful_input=None,
            )
        )
