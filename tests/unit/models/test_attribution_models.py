# tests/unit/models/test_attribution_models.py
import pytest
from pydantic import ValidationError

from app.models.attribution_analytics_requests import AttributionAnalyticsRequest
from app.models.attribution_requests import AttributionRequest, BenchmarkGroup, PortfolioGroup
from app.models.attribution_responses import SinglePeriodAttributionResult
from common.enums import PeriodType


@pytest.fixture
def base_attribution_payload():
    """Provides a base payload for attribution requests, excluding period definitions."""
    return {
        "portfolio_id": "ATTRIB_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "mode": "by_group",
        "group_by": ["assetClass"],
        "portfolio_groups_data": [],
        "benchmark_groups_data": [
            {
                "key": {"assetClass": "Equity"},
                "observations": [{"date": "2025-01-31", "return_base": 0.05, "weight_bop": 1.0}],
            }
        ],
    }


def test_attribution_request_with_analyses_passes(base_attribution_payload):
    """Tests that a request using the new 'analyses' array is valid."""
    payload = base_attribution_payload.copy()
    payload["analyses"] = [{"period": PeriodType.YTD, "frequencies": ["monthly"]}]
    try:
        AttributionRequest.model_validate(payload)
    except ValidationError as e:
        pytest.fail(f"Validation failed unexpectedly with 'analyses': {e}")


def test_attribution_request_with_empty_analyses_fails(base_attribution_payload):
    """Tests that validation fails if 'analyses' is an empty list."""
    payload = base_attribution_payload.copy()
    payload["analyses"] = []
    with pytest.raises(ValidationError, match="analyses list cannot be empty"):
        AttributionRequest.model_validate(payload)


def test_attribution_request_with_no_analyses_fails(base_attribution_payload):
    """Tests that validation fails if the 'analyses' field is missing entirely."""
    with pytest.raises(ValidationError, match="Field required"):
        AttributionRequest.model_validate(base_attribution_payload)


def test_single_period_attribution_result_schema_excludes_dead_currency_totals_field():
    schema = SinglePeriodAttributionResult.model_json_schema()

    assert "currency_attribution_totals" not in schema.get("properties", {})


def test_attribution_analytics_request_rejects_stateful_and_legacy_conflicts(base_attribution_payload):
    payload = {
        **base_attribution_payload,
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
        "input_mode": "stateful",
        "stateful_input": {},
        "portfolio_groups_data": [],
    }

    with pytest.raises(ValidationError, match="legacy attribution input fields must be null when input_mode=stateful"):
        AttributionAnalyticsRequest.model_validate(payload)

    with pytest.raises(ValidationError, match="stateful_input is required when input_mode=stateful"):
        AttributionAnalyticsRequest.model_validate(
            {
                **base_attribution_payload,
                "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
                "input_mode": "stateful",
                "portfolio_groups_data": None,
                "benchmark_groups_data": [],
            }
        )


def test_attribution_analytics_request_rejects_partial_legacy_by_instrument(base_attribution_payload):
    with pytest.raises(ValidationError, match="portfolio_data and instruments_data must be provided together"):
        AttributionAnalyticsRequest.model_validate(
            {
                **base_attribution_payload,
                "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
                "portfolio_groups_data": None,
                "benchmark_groups_data": [],
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [],
                },
            }
        )


def test_attribution_analytics_request_rejects_stateful_input_in_stateless_mode(base_attribution_payload):
    with pytest.raises(ValidationError, match="stateful_input must be null when input_mode=stateless"):
        AttributionAnalyticsRequest.model_validate(
            {
                **base_attribution_payload,
                "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
                "stateful_input": {},
            }
        )


def test_attribution_analytics_request_rejects_missing_stateless_payload():
    with pytest.raises(ValidationError, match="stateless_input or legacy attribution input fields are required"):
        AttributionAnalyticsRequest.model_validate(
            {
                "portfolio_id": "ATTRIB_STATELESS",
                "report_start_date": "2025-01-01",
                "report_end_date": "2025-01-31",
                "mode": "by_group",
                "group_by": ["assetClass"],
                "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
                "benchmark_groups_data": [],
            }
        )


def test_attribution_analytics_request_rejects_mixed_stateless_shapes(base_attribution_payload):
    with pytest.raises(ValidationError, match="Provide either stateless_input or legacy attribution input fields"):
        AttributionAnalyticsRequest.model_validate(
            {
                **base_attribution_payload,
                "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
                "stateless_input": {
                    "portfolio_groups_data": [],
                    "benchmark_groups_data": [
                        {
                            "key": {"assetClass": "Equity"},
                            "observations": [{"date": "2025-01-31", "return_base": 0.05, "weight_bop": 1.0}],
                        }
                    ],
                },
            }
        )


def test_attribution_analytics_request_to_stateless_prefers_explicit_override(base_attribution_payload):
    request = AttributionAnalyticsRequest.model_validate(
        {
            **base_attribution_payload,
            "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
        }
    )

    stateless = request.to_stateless_attribution_request(
        portfolio_groups_data=[PortfolioGroup.model_validate({"key": {"assetClass": "Bond"}, "observations": []})],
        benchmark_groups_data=[
            BenchmarkGroup.model_validate(
                {
                    "key": {"assetClass": "Bond"},
                    "observations": [{"date": "2025-01-31", "return_base": 0.03, "weight_bop": 1.0}],
                }
            )
        ],
    )

    assert stateless.portfolio_groups_data is not None
    assert stateless.portfolio_groups_data[0].key["assetClass"] == "Bond"
    assert stateless.benchmark_groups_data[0].key["assetClass"] == "Bond"


def test_attribution_analytics_request_builds_nested_stateless_request():
    request = AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_NESTED",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "mode": "by_group",
            "group_by": ["assetClass"],
            "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_groups_data": [{"key": {"assetClass": "Equity"}, "observations": []}],
                "benchmark_groups_data": [
                    {
                        "key": {"assetClass": "Equity"},
                        "observations": [{"date": "2025-01-31", "return_base": 0.05, "weight_bop": 1.0}],
                    }
                ],
            },
        }
    )

    stateless = request.to_stateless_attribution_request()

    assert stateless.portfolio_groups_data is not None
    assert stateless.portfolio_groups_data[0].key["assetClass"] == "Equity"
    assert stateless.benchmark_groups_data[0].key["assetClass"] == "Equity"


def test_attribution_analytics_request_to_stateless_requires_benchmark_groups():
    request = AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_STATEFUL",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "mode": "by_group",
            "group_by": ["assetClass"],
            "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    with pytest.raises(ValueError, match="No stateless benchmark_groups_data are available"):
        request.to_stateless_attribution_request()
