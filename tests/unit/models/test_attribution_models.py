# tests/unit/models/test_attribution_models.py
import pytest
from pydantic import ValidationError

from app.models.attribution_requests import AttributionRequest
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
