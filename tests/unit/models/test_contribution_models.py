# tests/unit/models/test_contribution_models.py
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import ContributionResponse


@pytest.fixture
def minimal_contribution_request_payload():
    """Provides a minimal valid payload for a contribution request."""
    return {
        "portfolio_id": "CONTRIB_001",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [],
        },
        "positions_data": [{"position_id": "Stock_A", "meta": {"sector": "Tech"}, "valuation_points": []}],
    }


@pytest.fixture
def base_response_footer():
    """Provides a valid shared response footer (meta, diagnostics, audit)."""
    calc_id = uuid4()
    return {
        "meta": {
            "calculation_id": str(calc_id),
            "engine_version": "1.0.0",
            "precision_mode": "FLOAT64",
            "annualization": {"enabled": False},
            "calendar": {"type": "BUSINESS"},
            "periods": {},
        },
        "diagnostics": {
            "nip_days": 0,
            "reset_days": 0,
            "effective_period_start": "2025-01-01",
        },
        "audit": {"counts": {"input_rows": 10}},
    }


def test_contribution_request_with_analyses_passes(minimal_contribution_request_payload):
    """Tests that a request using the new 'analyses' field is valid."""
    try:
        req = ContributionRequest.model_validate(minimal_contribution_request_payload)
        assert req.portfolio_id == "CONTRIB_001"
        assert len(req.analyses) == 1
    except ValidationError as e:
        pytest.fail(f"Validation failed unexpectedly with 'analyses': {e}")


def test_contribution_request_multi_level_happy_path(minimal_contribution_request_payload):
    """
    Tests that a multi-level contribution request with a hierarchy
    and other options is parsed correctly.
    """
    payload = minimal_contribution_request_payload.copy()
    payload["hierarchy"] = ["assetClass", "sector"]
    payload["weighting_scheme"] = "AVG_CAPITAL"
    payload["emit"] = {"by_level": True}

    try:
        req = ContributionRequest.model_validate(payload)
        assert req.hierarchy == ["assetClass", "sector"]
        assert req.weighting_scheme == "AVG_CAPITAL"
        assert req.emit.by_level is True
    except ValidationError as e:
        pytest.fail(f"Validation failed unexpectedly for multi-level request: {e}")


def test_contribution_request_invalid_weighting_scheme(minimal_contribution_request_payload):
    """
    Tests that the model raises a validation error for an invalid weighting_scheme.
    """
    payload = minimal_contribution_request_payload.copy()
    payload["weighting_scheme"] = "INVALID_SCHEME"

    with pytest.raises(ValidationError):
        ContributionRequest.model_validate(payload)


def test_contribution_request_rejects_empty_analyses(minimal_contribution_request_payload):
    payload = minimal_contribution_request_payload.copy()
    payload["analyses"] = []

    with pytest.raises(ValidationError, match="analyses list cannot be empty"):
        ContributionRequest.model_validate(payload)


def test_contribution_response_new_structure_passes(base_response_footer):
    """Tests that a valid multi-period contribution response is parsed correctly."""
    single_period_payload = {
        "summary": {"portfolio_contribution": 1.82, "coverage_mv_pct": 100.0, "weighting_scheme": "BOD"},
        "levels": [],
    }
    payload = {
        "calculation_id": base_response_footer["meta"]["calculation_id"],
        "portfolio_id": "HIERARCHY_01",
        "results_by_period": {"YTD": single_period_payload, "MTD": single_period_payload},
        **base_response_footer,
    }

    try:
        resp = ContributionResponse.model_validate(payload)
        assert "YTD" in resp.results_by_period
        assert resp.results_by_period["YTD"].summary.portfolio_contribution == 1.82
    except ValidationError as e:
        pytest.fail(f"Validation failed for new response structure: {e}")


def test_contribution_response_legacy_structure_fails(base_response_footer):
    """Tests that legacy top-level contribution fields are rejected."""
    payload = {
        "calculation_id": base_response_footer["meta"]["calculation_id"],
        "portfolio_id": "HIERARCHY_01",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "summary": {
            "portfolio_contribution": 1.82,
            "coverage_mv_pct": 99.7,
            "weighting_scheme": "BOD",
        },
        "levels": [],
        **base_response_footer,
    }

    with pytest.raises(ValidationError):
        ContributionResponse.model_validate(payload)


def test_contribution_analytics_request_requires_stateful_input_for_stateful_mode():
    payload = {
        "portfolio_id": "CONTRIB_STATEFUL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
    }

    with pytest.raises(ValidationError, match="stateful_input is required"):
        ContributionAnalyticsRequest.model_validate(payload)


def test_contribution_analytics_request_rejects_mixed_stateless_payload_shapes():
    payload = {
        "portfolio_id": "CONTRIB_STATELESS",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "stateless_input": {
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [],
            },
            "positions_data": [],
        },
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [],
        },
        "positions_data": [],
    }

    with pytest.raises(ValidationError, match="Provide either stateless_input or legacy portfolio_data/positions_data"):
        ContributionAnalyticsRequest.model_validate(payload)


def test_contribution_analytics_request_builds_legacy_stateless_request():
    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "CONTRIB_LEGACY",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [],
        },
        "positions_data": [],
    }

    request = ContributionAnalyticsRequest.model_validate(payload)
    stateless_request = request.to_stateless_contribution_request()

    assert stateless_request.portfolio_id == "CONTRIB_LEGACY"
    assert stateless_request.portfolio_data.metric_basis == "NET"
    assert stateless_request.positions_data == []
