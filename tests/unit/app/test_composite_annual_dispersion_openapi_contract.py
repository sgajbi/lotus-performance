from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.api.dependencies.composite_annual_dispersion import (
    annual_comparison_openapi_examples,
    annual_dispersion_openapi_examples,
)
from app.models.composite_annual_comparison import CompositeAnnualComparisonRequest, CompositeAnnualComparisonResponse
from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest, CompositeAnnualDispersionResponse
from app.models.platform_surfaces import ErrorDetailResponse
from main import app


def test_one_analytics_operation_documents_exact_selection_and_preserves_existing_family():
    spec = app.openapi()
    operation = spec["paths"]["/performance/composites/analytics"]["post"]
    assert "non-official calculated analysis" in operation["description"]
    assert {"400", "401", "404", "409", "422", "503"} <= operation["responses"].keys()
    assert spec["paths"]["/performance/composites/twr"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/CompositeTWRResponse")
    assert "/performance/composites/inspect" in spec["paths"]
    request = spec["components"]["schemas"]["CompositeAnnualDispersionRequest"]
    assert request["additionalProperties"] is False
    assert request["properties"]["materialization_ids"]["minItems"] == 12
    assert request["properties"]["materialization_ids"]["maxItems"] == 12
    assert "return_value" not in request["properties"]
    assert "year_begin_assets" not in request["properties"]


def test_registered_comparison_operation_has_complete_typed_examples_and_bounded_authority():
    spec = app.openapi()
    operation = spec["paths"]["/performance/composites/analytics/comparison"]["post"]
    examples = annual_comparison_openapi_examples()
    assert operation["requestBody"]["content"]["application/json"]["example"] == examples["request"]
    assert operation["responses"]["200"]["content"]["application/json"]["example"] == examples["response"]
    CompositeAnnualComparisonRequest.model_validate(examples["request"])
    result = CompositeAnnualComparisonResponse.model_validate(examples["response"])
    assert result.value == 0 and result.baseline.result_fingerprint != result.candidate.result_fingerprint
    assert spec["components"]["schemas"]["CompositeAnnualComparisonRequest"]["additionalProperties"] is False
    assert "approved, frozen or official" in operation["description"]
    for code, names in (
        ("404", ["not_found"]),
        ("409", ["incomplete"]),
        ("422", ["request_validation", "domain_admission", "comparison_basis"]),
        ("503", ["retained_evidence"]),
    ):
        content = operation["responses"][code]["content"]["application/json"]
        assert content["schema"]["$ref"].endswith("/ErrorDetailResponse")
        for name in names:
            assert content["examples"][name]["value"] == examples["errors"][name]
            ErrorDetailResponse.model_validate(examples["errors"][name])


@pytest.mark.parametrize("change", ["method", "vector", "convention", "status"])
def test_comparison_example_guard_refuses_bad_contract_and_accepts_registered_payload(change):
    payload = deepcopy(annual_comparison_openapi_examples())
    if change == "method":
        payload["request"]["candidate"]["method"] = "invented"
    elif change == "vector":
        payload["request"]["baseline"]["materialization_ids"].pop()
    elif change == "convention":
        payload["response"]["convention"] = "UNROUNDED_ESTIMATOR_DIFFERENCE"
    else:
        payload["response"]["status"] = "APPROVED"
    with pytest.raises(ValidationError):
        CompositeAnnualComparisonRequest.model_validate(payload["request"])
        CompositeAnnualComparisonResponse.model_validate(payload["response"])


def test_registered_examples_validate_exact_request_and_response_schemas():
    operation = app.openapi()["paths"]["/performance/composites/analytics"]["post"]
    examples = annual_dispersion_openapi_examples()
    assert (
        operation["requestBody"]["content"]["application/json"]["examples"]["annual_member_dispersion"]["value"]
        == examples["request"]
    )
    assert (
        operation["responses"]["200"]["content"]["application/json"]["examples"]["annual_member_dispersion"]["value"]
        == examples["response"]
    )
    assert len(CompositeAnnualDispersionRequest.model_validate(examples["request"]).materialization_ids) == 12
    result = CompositeAnnualDispersionResponse.model_validate(examples["response"])
    assert str(result.value) == "0.018708286934"
    assert len(result.months) == 12
    assert result.full_year_member_count == 6
    assert result.qualification == "RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"
    for status, case in [("404", "not_found"), ("409", "incomplete"), ("503", "retained_evidence")]:
        content = operation["responses"][status]["content"]["application/json"]
        assert content["schema"]["$ref"].endswith("/ErrorDetailResponse")
        assert content["example"] == examples["errors"][case]
        assert ErrorDetailResponse.model_validate(content["example"]).retryable is False
    content = operation["responses"]["422"]["content"]["application/json"]
    assert content["schema"]["$ref"].endswith("/ErrorDetailResponse")
    assert content["examples"]["requestValidation"]["value"] == examples["errors"]["request_validation"]
    assert content["examples"]["domainAdmission"]["value"] == examples["errors"]["domain_admission"]
    assert ErrorDetailResponse.model_validate(content["examples"]["requestValidation"]["value"]).validation_errors
    assert ErrorDetailResponse.model_validate(content["examples"]["domainAdmission"]["value"]).error_code == (
        "ANNUAL_DISPERSION_MONTH_SCOPE_MISMATCH"
    )


@pytest.mark.parametrize("change", ["metric", "receipt_shape", "status"])
def test_example_schema_guard_rejects_representative_broken_examples(change):
    payload = deepcopy(annual_dispersion_openapi_examples())
    if change == "metric":
        payload["request"]["metric_id"] = "METRIC_001"
    elif change == "receipt_shape":
        payload["request"]["materialization_ids"] = ["example_materialization_ids_item"]
    else:
        payload["response"]["status"] = "pending"
    with pytest.raises(ValidationError):
        CompositeAnnualDispersionRequest.model_validate(payload["request"])
        CompositeAnnualDispersionResponse.model_validate(payload["response"])
