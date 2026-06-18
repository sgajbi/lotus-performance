# tests/unit/models/test_contribution_models.py
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.contribution_analytics_requests import (
    ContributionAnalyticsRequest,
    _complete_contribution_input_pair,
    _has_exactly_one_stateless_contribution_shape,
    _nested_contribution_input_pair,
    _resolved_stateless_contribution_inputs,
    _stateless_contribution_envelope_issue,
    _validate_stateless_contribution_payloads,
)
from app.models.contribution_requests import ContributionRequest, PortfolioData, PositionData
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
        "calculation_supportability": {
            "state": "ready",
            "reason": "calculation_complete",
            "freshness_bucket": "current",
            "input_row_count": 3,
            "resolved_period_count": 1,
            "benchmark_row_count": 0,
        },
        "source_economics_evidence": {
            "input_mode": "stateless",
            "source_owner": "caller",
            "status": "CALLER_SUPPLIED",
            "reason_codes": ["STATELESS_CALLER_SUPPLIED_SOURCE_ECONOMICS"],
            "source_contracts": ["ContributionRequest"],
            "available_economics": ["portfolio_market_values", "position_market_values"],
            "unsupported_economics": [],
            "degraded_economics": [],
            "cash_flow_type_counts": {},
            "source_snapshot_count": 0,
            "source_snapshot_endpoints": [],
            "classification_dimensions": ["sector"],
            "lineage_policy": "caller-supplied stateless payload; no upstream source snapshot is available",
        },
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


def test_contribution_lookthrough_schema_states_current_boundary():
    schema = ContributionRequest.model_json_schema()
    lookthrough_schema = schema["$defs"]["Lookthrough"]

    assert (
        "does not decompose fund or structured-product holdings"
        in lookthrough_schema["properties"]["fallback_policy"]["description"]
    )


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


def test_contribution_analytics_request_rejects_stateful_input_in_stateless_mode():
    payload = {
        "portfolio_id": "CONTRIB_STATELESS",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "stateful_input": {},
        "stateless_input": {
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [],
            },
            "positions_data": [],
        },
    }

    with pytest.raises(ValidationError, match="stateful_input must be null when input_mode=stateless"):
        ContributionAnalyticsRequest.model_validate(payload)


def test_contribution_analytics_request_rejects_missing_stateless_payload():
    payload = {
        "portfolio_id": "CONTRIB_STATELESS",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
    }

    with pytest.raises(ValidationError, match="stateless_input or legacy portfolio_data/positions_data is required"):
        ContributionAnalyticsRequest.model_validate(payload)


def test_validate_stateless_contribution_payloads_rejects_competing_stateful_payload():
    request = SimpleNamespace(
        stateful_input={},
        stateless_input=object(),
    )

    with pytest.raises(ValueError, match="stateful_input must be null when input_mode=stateless"):
        _validate_stateless_contribution_payloads(request, has_legacy_stateless=False)  # type: ignore[arg-type]


def test_stateless_contribution_envelope_issue_requires_exactly_one_payload_shape():
    assert _stateless_contribution_envelope_issue(has_nested=True, has_legacy=False) is None
    assert _stateless_contribution_envelope_issue(has_nested=False, has_legacy=True) is None
    assert _stateless_contribution_envelope_issue(has_nested=True, has_legacy=True) == (
        "Provide either stateless_input or legacy portfolio_data/positions_data, not both, for stateless mode"
    )
    assert _stateless_contribution_envelope_issue(has_nested=False, has_legacy=False) == (
        "stateless_input or legacy portfolio_data/positions_data is required when input_mode=stateless"
    )


def test_stateless_contribution_shape_predicate_requires_exactly_one_payload_shape():
    assert _has_exactly_one_stateless_contribution_shape(has_nested=True, has_legacy=False)
    assert _has_exactly_one_stateless_contribution_shape(has_nested=False, has_legacy=True)
    assert not _has_exactly_one_stateless_contribution_shape(has_nested=True, has_legacy=True)
    assert not _has_exactly_one_stateless_contribution_shape(has_nested=False, has_legacy=False)


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


def test_contribution_analytics_request_builds_nested_stateless_request():
    request = ContributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "CONTRIB_NESTED",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [],
                },
                "positions_data": [{"position_id": "POS_1", "valuation_points": []}],
            },
        }
    )

    stateless = request.to_stateless_contribution_request()

    assert stateless.portfolio_data.metric_basis == "NET"
    assert stateless.positions_data[0].position_id == "POS_1"


def test_contribution_analytics_request_rejects_partial_legacy_stateless_payload():
    payload = {
        "portfolio_id": "CONTRIB_PARTIAL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [],
        },
    }

    with pytest.raises(ValidationError, match="portfolio_data and positions_data must be provided together"):
        ContributionAnalyticsRequest.model_validate(payload)


def test_contribution_analytics_request_rejects_stateful_conflicts():
    payload = {
        "portfolio_id": "CONTRIB_STATEFUL",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
        "stateless_input": {
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [],
            },
            "positions_data": [],
        },
    }

    with pytest.raises(ValidationError, match="stateless_input must be null when input_mode=stateful"):
        ContributionAnalyticsRequest.model_validate(payload)

    with pytest.raises(
        ValidationError, match="portfolio_data and positions_data must be null when input_mode=stateful"
    ):
        ContributionAnalyticsRequest.model_validate(
            {
                **payload,
                "stateless_input": None,
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [],
                },
                "positions_data": [],
            }
        )


def test_contribution_analytics_request_to_stateless_prefers_override_payload():
    request = ContributionAnalyticsRequest.model_validate(
        {
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
        }
    )

    stateless = request.to_stateless_contribution_request(
        portfolio_data=PortfolioData.model_validate({"metric_basis": "GROSS", "valuation_points": []}),
        positions_data=[PositionData.model_validate({"position_id": "OVERRIDE", "valuation_points": []})],
    )

    assert stateless.portfolio_data.metric_basis == "GROSS"
    assert stateless.positions_data[0].position_id == "OVERRIDE"


def test_resolved_stateless_contribution_inputs_prefers_override_payload():
    request = ContributionAnalyticsRequest.model_validate(
        {
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
        }
    )

    portfolio_data, positions_data = _resolved_stateless_contribution_inputs(
        request,
        portfolio_data=PortfolioData.model_validate({"metric_basis": "GROSS", "valuation_points": []}),
        positions_data=[PositionData.model_validate({"position_id": "OVERRIDE", "valuation_points": []})],
    )

    assert portfolio_data.metric_basis == "GROSS"
    assert positions_data[0].position_id == "OVERRIDE"


def test_complete_contribution_input_pair_requires_both_payloads():
    portfolio_data = PortfolioData.model_validate({"metric_basis": "GROSS", "valuation_points": []})
    positions_data = [PositionData.model_validate({"position_id": "OVERRIDE", "valuation_points": []})]

    assert _complete_contribution_input_pair(portfolio_data=portfolio_data, positions_data=positions_data) == (
        portfolio_data,
        positions_data,
    )
    assert _complete_contribution_input_pair(portfolio_data=portfolio_data, positions_data=None) is None
    assert _complete_contribution_input_pair(portfolio_data=None, positions_data=positions_data) is None


def test_nested_contribution_input_pair_projects_nested_payload():
    nested_input = ContributionAnalyticsRequest.model_validate(
        {
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
                "positions_data": [{"position_id": "NESTED", "valuation_points": []}],
            },
        }
    ).stateless_input

    resolved_pair = _nested_contribution_input_pair(nested_input)

    assert resolved_pair is not None
    portfolio_data, positions_data = resolved_pair
    assert portfolio_data.metric_basis == "NET"
    assert positions_data[0].position_id == "NESTED"
    assert _nested_contribution_input_pair(None) is None


def test_resolved_stateless_contribution_inputs_ignores_partial_override():
    request = ContributionAnalyticsRequest.model_validate(
        {
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
                "positions_data": [{"position_id": "NESTED", "valuation_points": []}],
            },
        }
    )

    portfolio_data, positions_data = _resolved_stateless_contribution_inputs(
        request,
        portfolio_data=PortfolioData.model_validate({"metric_basis": "GROSS", "valuation_points": []}),
        positions_data=None,
    )

    assert portfolio_data.metric_basis == "NET"
    assert positions_data[0].position_id == "NESTED"


def test_resolved_stateless_contribution_inputs_uses_legacy_payload():
    request = ContributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "CONTRIB_LEGACY",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [],
            },
            "positions_data": [{"position_id": "POS_LEGACY", "valuation_points": []}],
        }
    )

    portfolio_data, positions_data = _resolved_stateless_contribution_inputs(
        request,
        portfolio_data=None,
        positions_data=None,
    )

    assert portfolio_data.metric_basis == "NET"
    assert positions_data[0].position_id == "POS_LEGACY"


def test_contribution_analytics_request_to_stateless_fails_without_stateless_payload():
    request = ContributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "CONTRIB_STATEFUL",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    with pytest.raises(ValueError, match="No stateless contribution inputs are available"):
        request.to_stateless_contribution_request()
