# tests/unit/models/test_attribution_models.py
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.attribution_analytics_requests import (
    AttributionAnalyticsRequest,
    _attribution_input_shape,
    _attribution_request_payload,
    _has_exactly_one_stateless_input_shape,
    _resolve_attribution_stateless_input,
    _stateless_input_envelope_issue,
    build_calculated_attribution_request,
)
from app.models.attribution_requests import (
    AttributionPortfolioData,
    AttributionRequest,
    BenchmarkGroup,
    InstrumentData,
    PortfolioGroup,
)
from app.models.attribution_responses import (
    AttributionLevelResult,
    AttributionLevelTotals,
    SinglePeriodAttributionResult,
    _attribution_level_totals_payload,
)
from common.enums import PeriodType
from core.errors import APIUnprocessableEntityError
from core.monetary_input import validate_calculated_money_model


@pytest.mark.parametrize("model", [AttributionPortfolioData, InstrumentData])
@pytest.mark.parametrize("amount", [True, False, None, "NaN", "Infinity", "-Infinity", float(2**53)])
def test_calculated_attribution_nested_money_preserves_admission_refusals(model, amount):
    payload = {"valuation_points": [{"perf_date": "2025-01-01", "begin_mv": "100", "end_mv": amount}]}
    if model is InstrumentData:
        payload["instrument_id"] = "SEC_1"
        payload["meta"] = {"sector": "Technology"}
    else:
        payload["metric_basis"] = "NET"
    with pytest.raises(APIUnprocessableEntityError) as failure:
        validate_calculated_money_model(model, payload)
    assert failure.value.error_code == "CALCULATED_FINANCIAL_INPUT_INVALID"
    assert failure.value.__cause__.errors()[0]["loc"] == ("valuation_points", 0, "end_mv")


@pytest.mark.parametrize("end", ["101.0000000000", "-0.00000000000000000000"])
def test_stateless_reconstruction_cannot_inherit_calculated_origin_from_nested_models(end):
    request = AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_INTERNAL",
            "mode": "by_instrument",
            "group_by": ["sector"],
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    point = {"perf_date": "2025-01-01", "begin_mv": "100.123456789012", "end_mv": end}
    portfolio = validate_calculated_money_model(
        AttributionPortfolioData, {"metric_basis": "NET", "valuation_points": [point]}
    )
    instrument = validate_calculated_money_model(
        InstrumentData, {"instrument_id": "SEC_1", "meta": {"sector": "Technology"}, "valuation_points": [point]}
    )
    benchmark = BenchmarkGroup.model_validate(
        {
            "key": {"sector": "Technology"},
            "observations": [
                {
                    "date": "2025-01-01",
                    "weight_bop": 1.0,
                    "return_base": 0.01,
                }
            ],
        }
    )
    inputs = {"portfolio_data": portfolio, "instruments_data": [instrument], "benchmark_groups_data": [benchmark]}
    with pytest.raises(ValidationError, match="scale"):
        request.to_stateless_attribution_request(**inputs)
    calculated = build_calculated_attribution_request(request=request, **inputs)
    assert calculated.portfolio_data.valuation_points[0].model_dump(mode="json")["begin_mv"] == point["begin_mv"]
    for nested in (calculated.portfolio_data, calculated.instruments_data[0]):
        assert nested.valuation_points[0].end_mv.as_tuple() == Decimal(end).as_tuple()
        assert nested.valuation_points[0].model_dump(mode="json")["end_mv"] == str(Decimal(end))
    # Reconstruct and revalidate rather than trusting possibly altered typed instances.
    altered = portfolio.model_copy(
        update={
            "valuation_points": [
                portfolio.valuation_points[0].model_copy(update={"end_mv": True}),
            ]
        }
    )
    with pytest.raises(APIUnprocessableEntityError) as failure:
        build_calculated_attribution_request(request=request, **{**inputs, "portfolio_data": altered})
    assert failure.value.error_code == "CALCULATED_FINANCIAL_INPUT_INVALID"


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


def test_single_period_attribution_result_schema_documents_currency_totals_field():
    schema = SinglePeriodAttributionResult.model_json_schema()
    properties = schema["properties"]
    totals_ref = properties["currency_attribution_totals"]["anyOf"][0]["$ref"].split("/")[-1]
    totals_properties = schema["$defs"][totals_ref]["properties"]

    assert properties["currency_attribution_totals"]["description"]
    for field_name in (
        "local_allocation",
        "local_selection",
        "currency_allocation",
        "currency_selection",
        "total_effect",
        "currency_count",
    ):
        assert field_name in totals_properties
        assert totals_properties[field_name]["description"]


def test_attribution_group_result_schema_includes_side_by_side_context_fields():
    schema = SinglePeriodAttributionResult.model_json_schema()
    attribution_group_schema = schema["$defs"]["AttributionGroupResult"]
    properties = attribution_group_schema["properties"]

    assert "portfolio_weight_avg" in properties
    assert "benchmark_weight_avg" in properties
    assert "portfolio_return" in properties
    assert "benchmark_return" in properties


def test_attribution_level_result_exposes_authoritative_total_fields_from_nested_totals():
    level = AttributionLevelResult.model_validate(
        {
            "dimension": "asset_class",
            "groups": [],
            "totals": {
                "allocation": 0.31,
                "selection": 0.22,
                "interaction": 0.05,
                "total_effect": 0.58,
            },
        }
    )

    assert level.allocation_total_pct == pytest.approx(0.31)
    assert level.selection_total_pct == pytest.approx(0.22)
    assert level.interaction_total_pct == pytest.approx(0.05)
    assert level.total_effect_pct == pytest.approx(0.58)


def test_attribution_level_totals_payload_normalizes_typed_and_mapping_totals():
    totals = AttributionLevelTotals(allocation=0.31, selection=0.22, interaction=0.05, total_effect=0.58)

    assert _attribution_level_totals_payload(totals) == totals.model_dump()
    assert _attribution_level_totals_payload({"allocation": 0.31}) == {"allocation": 0.31}
    assert _attribution_level_totals_payload(None) is None


def test_attribution_level_result_schema_documents_authoritative_total_fields():
    schema = SinglePeriodAttributionResult.model_json_schema()
    properties = schema["$defs"]["AttributionLevelResult"]["properties"]

    for field_name in (
        "allocation_total_pct",
        "selection_total_pct",
        "interaction_total_pct",
        "total_effect_pct",
    ):
        assert field_name in properties
        assert properties[field_name]["description"]
        assert properties[field_name]["examples"]


def test_single_period_attribution_result_schema_documents_status_reason_and_materiality_fields():
    schema = SinglePeriodAttributionResult.model_json_schema()
    properties = schema["properties"]
    reconciliation_properties = schema["$defs"]["Reconciliation"]["properties"]

    for field_name in ("status", "reason_codes", "reasons", "supportability_evidence"):
        assert field_name in properties
        assert properties[field_name]["description"]

    assert "residual_materiality" in reconciliation_properties
    residual_schema_name = reconciliation_properties["residual_materiality"]["$ref"].split("/")[-1]
    residual_properties = schema["$defs"][residual_schema_name]["properties"]
    assert residual_properties["classification"]["description"]
    assert residual_properties["warning_threshold"]["examples"]


def test_attribution_analytics_request_rejects_stateful_and_legacy_conflicts(base_attribution_payload):
    payload = {
        **base_attribution_payload,
        "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
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
                "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
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
                "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
                "portfolio_groups_data": None,
                "benchmark_groups_data": [],
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [],
                },
            }
        )


def test_attribution_input_shape_classifies_legacy_payloads(base_attribution_payload):
    by_instrument_request = AttributionAnalyticsRequest.model_validate(
        {
            **base_attribution_payload,
            "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
            "mode": "by_instrument",
            "portfolio_groups_data": None,
            "portfolio_data": {"metric_basis": "NET", "valuation_points": []},
            "instruments_data": [
                {
                    "instrument_id": "SEC_1",
                    "meta": {"assetClass": "Equity"},
                    "valuation_points": [],
                }
            ],
        }
    )
    shape = _attribution_input_shape(by_instrument_request)

    assert shape.has_legacy_by_instrument is True
    assert shape.has_partial_legacy_by_instrument is False
    assert shape.has_legacy_by_group is False
    assert shape.has_legacy_benchmark is True
    assert shape.has_legacy_stateless is True


def test_attribution_analytics_request_rejects_stateful_input_in_stateless_mode(base_attribution_payload):
    with pytest.raises(ValidationError, match="stateful_input must be null when input_mode=stateless"):
        AttributionAnalyticsRequest.model_validate(
            {
                **base_attribution_payload,
                "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
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
                "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
                "benchmark_groups_data": [],
            }
        )


def test_stateless_input_envelope_issue_requires_exactly_one_payload_shape():
    assert _stateless_input_envelope_issue(has_nested=True, has_legacy=False) is None
    assert _stateless_input_envelope_issue(has_nested=False, has_legacy=True) is None
    assert "not both" in str(_stateless_input_envelope_issue(has_nested=True, has_legacy=True))
    assert "are required" in str(_stateless_input_envelope_issue(has_nested=False, has_legacy=False))


@pytest.mark.parametrize(
    ("has_nested", "has_legacy", "expected"),
    [
        (True, False, True),
        (False, True, True),
        (True, True, False),
        (False, False, False),
    ],
)
def test_has_exactly_one_stateless_input_shape_requires_one_payload_shape(has_nested, has_legacy, expected):
    assert _has_exactly_one_stateless_input_shape(has_nested=has_nested, has_legacy=has_legacy) is expected


def test_attribution_analytics_request_rejects_mixed_stateless_shapes(base_attribution_payload):
    with pytest.raises(ValidationError, match="Provide either stateless_input or legacy attribution input fields"):
        AttributionAnalyticsRequest.model_validate(
            {
                **base_attribution_payload,
                "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
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
            "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
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


def test_resolve_attribution_stateless_input_prefers_explicit_override(base_attribution_payload):
    request = AttributionAnalyticsRequest.model_validate(
        {
            **base_attribution_payload,
            "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
        }
    )
    override_benchmark_groups = [
        BenchmarkGroup.model_validate(
            {
                "key": {"assetClass": "Cash"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        )
    ]

    resolved = _resolve_attribution_stateless_input(
        request=request,
        benchmark_groups_data=override_benchmark_groups,
    )

    assert resolved.benchmark_groups_data is override_benchmark_groups
    assert resolved.portfolio_data is None
    assert resolved.instruments_data is None
    assert resolved.portfolio_groups_data is None


def test_resolve_attribution_stateless_input_uses_nested_payload():
    request = AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_NESTED",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "mode": "by_group",
            "group_by": ["assetClass"],
            "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
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

    resolved = _resolve_attribution_stateless_input(request=request)

    assert resolved.portfolio_groups_data is not None
    assert resolved.portfolio_groups_data[0].key["assetClass"] == "Equity"
    assert resolved.benchmark_groups_data is not None
    assert resolved.benchmark_groups_data[0].key["assetClass"] == "Equity"


def test_attribution_request_payload_serializes_resolved_groups_without_analytics_fields(base_attribution_payload):
    request = AttributionAnalyticsRequest.model_validate(
        {
            **base_attribution_payload,
            "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
        }
    )
    resolved = _resolve_attribution_stateless_input(request=request)

    payload = _attribution_request_payload(request=request, resolved_input=resolved)

    assert "input_mode" not in payload
    assert "stateless_input" not in payload
    assert "stateful_input" not in payload
    assert payload["portfolio_groups_data"] == []
    assert payload["benchmark_groups_data"][0]["key"]["assetClass"] == "Equity"


def test_attribution_analytics_request_builds_nested_stateless_request():
    request = AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_NESTED",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "mode": "by_group",
            "group_by": ["assetClass"],
            "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
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
            "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    with pytest.raises(ValueError, match="No stateless benchmark_groups_data are available"):
        request.to_stateless_attribution_request()
