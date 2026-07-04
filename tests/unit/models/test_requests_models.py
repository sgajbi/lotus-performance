# tests/unit/models/test_requests_models.py
import pytest
from pydantic import ValidationError

from app.models.requests import PerformanceRequest
from common.enums import PeriodType


@pytest.fixture
def base_twr_payload():
    """Provides a base payload for TWR requests, excluding period definitions."""
    return {
        "portfolio_id": "VALIDATION_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-31",
        "valuation_points": [],
    }


def test_performance_request_with_analyses_passes(base_twr_payload):
    """Tests that validation succeeds when the new 'analyses' field is used."""
    payload = base_twr_payload.copy()
    payload["analyses"] = [{"period": "YTD", "frequencies": ["monthly"]}]
    try:
        PerformanceRequest.model_validate(payload)
    except ValidationError as e:
        pytest.fail(f"Validation failed unexpectedly with 'analyses': {e}")


@pytest.mark.parametrize("period_alias", ["ITD", "INCEPTION_TO_DATE", "SINCE_INCEPTION"])
def test_performance_request_normalizes_since_inception_aliases_to_si(base_twr_payload, period_alias):
    payload = base_twr_payload.copy()
    payload["analyses"] = [{"period": period_alias, "frequencies": ["monthly"]}]

    request = PerformanceRequest.model_validate(payload)

    assert request.analyses[0].period == PeriodType.SI
    assert request.analyses[0].period.value == "SI"


def test_performance_request_with_empty_analyses_list_fails(base_twr_payload):
    """Tests that validation fails if 'analyses' is an empty list."""
    payload = base_twr_payload.copy()
    payload["analyses"] = []
    with pytest.raises(ValidationError, match="analyses list cannot be empty"):
        PerformanceRequest.model_validate(payload)


def test_performance_request_with_empty_frequencies_list_fails(base_twr_payload):
    """Tests that validation fails if a frequency list within 'analyses' is empty."""
    payload = base_twr_payload.copy()
    payload["analyses"] = [{"period": "YTD", "frequencies": []}]
    with pytest.raises(ValidationError, match="frequencies list cannot be empty"):
        PerformanceRequest.model_validate(payload)


def test_performance_request_without_analyses_fails(base_twr_payload):
    """Tests that validation fails if the 'analyses' field is missing."""
    with pytest.raises(ValidationError, match="Field required"):
        PerformanceRequest.model_validate(base_twr_payload)
