from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest


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
