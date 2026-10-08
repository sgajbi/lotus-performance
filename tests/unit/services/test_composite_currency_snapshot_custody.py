"""True distinct retrieval identities must not hide conflicting pair/date economics."""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from app.models.composite_currency_normalization import CompositeFXMemberSource
from app.services.composite_materialization.currency_snapshot_custody import require_fx_snapshot_custody
from tests.composite_currency_normalization_helpers import normalization_wire


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _retrieval(calculation_id, *, start, end, rates):
    request = {"from_currency": "EUR", "to_currency": "USD", "start_date": start, "end_date": end}
    response = {
        "from_currency": "EUR",
        "to_currency": "USD",
        "rates": [{"rate_date": day, "rate": rate} for day, rate in rates],
    }
    request_hash, response_hash = _hash(request), _hash(response)
    snapshot = {
        "snapshot_id": hashlib.sha256(f"{calculation_id}:fx_rates:EUR/USD:{request_hash}".encode()).hexdigest(),
        "upstream_endpoint": "fx_rates",
        "source_identifier": "EUR/USD",
        "as_of_date": "2026-01-05",
        "request_fingerprint": request_hash,
        "response_fingerprint": response_hash,
        "retrieval_status": "200",
        "paging_metadata": request,
        "created_at_utc": "2026-01-06T01:00:00Z",
    }
    return {"request_wire": request, "response_wire": response}, snapshot


def _member(retrievals):
    row = deepcopy(normalization_wire()["members"][0])
    response_hash = _hash(retrievals[0]["response_wire"])
    row["retrieval_wires"] = retrievals
    for fixing in row["fixings"]:
        fixing["retrieval_response_fingerprint"] = response_hash
    return CompositeFXMemberSource.model_validate(row)


@pytest.mark.parametrize("overlap", [None, "1.3", "1.31"])
def test_distinct_overlapping_retrievals_refuse_conflicting_rates_and_accept_agreeing_rates(overlap):
    calculation_id = uuid4()
    first, first_snapshot = _retrieval(
        calculation_id, start="2026-01-04", end="2026-01-05", rates=[("2026-01-04", "1.3"), ("2026-01-05", "1.4")]
    )
    retrievals, snapshots = [first], [first_snapshot]
    if overlap is not None:
        second, second_snapshot = _retrieval(
            calculation_id, start="2026-01-03", end="2026-01-04", rates=[("2026-01-04", overlap)]
        )
        assert second_snapshot["snapshot_id"] != first_snapshot["snapshot_id"]
        retrievals.append(second)
        snapshots.append(second_snapshot)
    member = _member(retrievals)
    if overlap == "1.31":
        with pytest.raises(ValueError, match="Conflicting FX economics"):
            require_fx_snapshot_custody(
                member, reporting_currency="USD", calculation_id=calculation_id, snapshots=snapshots
            )
    else:
        assert len(
            require_fx_snapshot_custody(
                member, reporting_currency="USD", calculation_id=calculation_id, snapshots=snapshots
            )
        ) == len(snapshots)


def test_identical_responses_for_distinct_requests_agree_without_losing_request_custody():
    calculation_id = uuid4()
    first, one = _retrieval(
        calculation_id, start="2026-01-03", end="2026-01-05", rates=[("2026-01-04", "1.3"), ("2026-01-05", "1.4")]
    )
    second, two = _retrieval(
        calculation_id, start="2026-01-04", end="2026-01-05", rates=[("2026-01-04", "1.3"), ("2026-01-05", "1.4")]
    )
    assert one["snapshot_id"] != two["snapshot_id"] and one["response_fingerprint"] == two["response_fingerprint"]
    assert (
        len(
            require_fx_snapshot_custody(
                _member([first, second]), reporting_currency="USD", calculation_id=calculation_id, snapshots=[one, two]
            )
        )
        == 2
    )
