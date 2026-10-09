from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models.composite_analytics import CompositeAnalyticsRequest
from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest


def _annual():
    return {
        "composite_id": "COMPOSITE",
        "year": 2026,
        "return_view": "GROSS",
        "reporting_currency": "USD",
        "materialization_ids": [str(UUID(int=index)) for index in range(1, 13)],
    }


def test_original_annual_default_and_contract_are_unchanged():
    payload = _annual()
    actual = TypeAdapter(CompositeAnalyticsRequest).validate_python(payload)
    assert actual.model_dump(mode="json") == CompositeAnnualDispersionRequest.model_validate(payload).model_dump(
        mode="json"
    )


@pytest.mark.parametrize("change", [{"materialization_ids": []}, {"year": 0}, {"surplus": 1}])
def test_annual_validation_errors_preserve_original_locations(change):
    payload = {**_annual(), **change}
    with pytest.raises(ValidationError) as baseline:
        CompositeAnnualDispersionRequest.model_validate(payload)
    with pytest.raises(ValidationError) as actual:
        TypeAdapter(CompositeAnalyticsRequest).validate_python(payload)
    assert actual.value.errors(include_url=False) == baseline.value.errors(include_url=False)


@pytest.mark.parametrize("value", [None, [], "unsupported", 1, {"metric_id": "ARBITRARY_FORMULA"}])
def test_invalid_dispatch_is_validation_refusal(value):
    with pytest.raises(ValidationError):
        TypeAdapter(CompositeAnalyticsRequest).validate_python(value)
