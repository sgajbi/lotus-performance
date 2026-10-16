import json
from importlib.resources import files
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest, CompositeAnnualDispersionResponse


def payload():
    return {
        "composite_id": "NEUTRAL_BALANCED_USD",
        "year": 2026,
        "return_view": "NET_ACTUAL",
        "reporting_currency": "USD",
        "materialization_ids": [str(uuid4()) for _ in range(12)],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"year": True},
        {"year": 0},
        {"year": "2026"},
        {"method": "MONTHLY_STDDEV"},
        {"metric_id": "REALIZED_VOLATILITY"},
        {"return_view": "NET_MODEL_FEE"},
        {"reporting_currency": "UŚD"},
        {"tenant_id": "tenant-b"},
        {"value": ".0187"},
    ],
)
def test_annual_metric_admission_refuses_ambiguous_or_unsupported_controls(change):
    with pytest.raises(ValidationError):
        CompositeAnnualDispersionRequest.model_validate({**payload(), **change})


def test_annual_metric_requires_twelve_unique_receipts():
    data = payload()
    for ids in (data["materialization_ids"][:11], [data["materialization_ids"][0]] * 12):
        with pytest.raises(ValidationError):
            CompositeAnnualDispersionRequest.model_validate({**data, "materialization_ids": ids})
    assert CompositeAnnualDispersionRequest.model_validate(data).method == "EQUAL_WEIGHT_SAMPLE_STDDEV"


def response_payload():
    return json.loads(files("app").joinpath("api", "examples", "composite_annual_dispersion.json").read_text())[
        "response"
    ]


@pytest.mark.parametrize("applicability", ["NOT_REQUIRED_SMALL_POPULATION", "REQUIRES_PROFILE_REVIEW"])
def test_legacy_annual_response_read_preserves_fields_and_original_fingerprint(applicability):
    legacy = response_payload()
    legacy.pop("reporting_applicability_reason", None)
    legacy["reporting_applicability"] = applicability
    retained = CompositeAnnualDispersionResponse.model_validate(legacy)
    assert retained.reporting_applicability_reason is None
    assert "reporting_applicability_reason" not in retained.model_fields_set
    assert retained.result_fingerprint == legacy["result_fingerprint"]
    assert retained.model_dump(mode="json", exclude_unset=True) == legacy


@pytest.mark.parametrize("reason", ["APPROVED", True, "NOT_REQUIRED_SMALL_POPULATION"])
def test_reporting_reason_refuses_invented_authority(reason):
    with pytest.raises(ValidationError):
        CompositeAnnualDispersionResponse.model_validate(
            {**response_payload(), "reporting_applicability_reason": reason}
        )


def test_unbound_reason_requires_review_while_legacy_exemption_stays_readable():
    valid = {**response_payload(), "reporting_applicability_reason": "APPROVED_REPORTING_PROFILE_NOT_BOUND"}
    assert CompositeAnnualDispersionResponse.model_validate(valid).reporting_applicability == "REQUIRES_PROFILE_REVIEW"
    with pytest.raises(ValidationError, match="requires profile review"):
        CompositeAnnualDispersionResponse.model_validate(
            {**valid, "reporting_applicability": "NOT_REQUIRED_SMALL_POPULATION"}
        )
