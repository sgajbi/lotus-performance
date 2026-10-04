from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.composite_annual_comparison import CompositeAnnualComparisonRequest
from tests.unit.services.test_composite_annual_dispersion_service import annual_request, year_records


def valid_payload():
    annual = annual_request(year_records()).model_dump(mode="json")
    return {"baseline": annual, "candidate": deepcopy(annual)}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("composite_id", "OTHER"),
        ("year", 2025),
        ("return_view", "GROSS"),
        ("reporting_currency", "EUR"),
        ("method", "YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV"),
    ],
)
def test_pair_requires_common_economic_scope(field, value):
    payload = valid_payload()
    payload["candidate"][field] = value
    with pytest.raises(ValidationError):
        CompositeAnnualComparisonRequest.model_validate(payload)
    assert CompositeAnnualComparisonRequest.model_validate(valid_payload()).baseline.year == 2026


@pytest.mark.parametrize("change", ["latest", "approval", "freeze", "duplicate", "missing", "extra", "year"])
def test_pair_rejects_automatic_selection_and_invalid_receipt_shapes(change):
    payload = valid_payload()
    if change in {"latest", "approval", "freeze"}:
        payload[change] = True
    elif change == "duplicate":
        payload["candidate"]["materialization_ids"][1] = payload["candidate"]["materialization_ids"][0]
    elif change == "missing":
        payload["baseline"]["materialization_ids"].pop()
    elif change == "extra":
        payload["candidate"]["value"] = "0.1"
    else:
        payload["baseline"]["year"] = True
    with pytest.raises(ValidationError):
        CompositeAnnualComparisonRequest.model_validate(payload)
