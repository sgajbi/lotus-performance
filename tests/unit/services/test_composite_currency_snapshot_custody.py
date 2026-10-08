"""True distinct retrieval identities must not hide conflicting pair/date economics."""

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.composite_currency_normalization import CompositeFXMemberSource
from app.services.composite_materialization.currency_snapshot_custody import require_fx_snapshot_custody
from app.services.stateful_input_service import StatefulInputService
from tests.composite_currency_normalization_helpers import normalization_wire


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _retrieval(calculation_id, *, start, end, rates, source_currency="EUR"):
    pair = f"{source_currency}/USD"
    request = {"from_currency": source_currency, "to_currency": "USD", "start_date": start, "end_date": end}
    response = {
        "rates": [{"rate_date": day, "rate": rate} for day, rate in rates],
    }
    request_hash, response_hash = _hash(request), _hash(response)
    snapshot = {
        "snapshot_id": hashlib.sha256(f"{calculation_id}:fx_rates:{pair}:{request_hash}".encode()).hexdigest(),
        "upstream_endpoint": "fx_rates",
        "source_identifier": pair,
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


@pytest.mark.parametrize("echo", [{}, {"from_currency": "EUR", "to_currency": "USD"}, {"from_currency": "EUR"}])
def test_native_fx_rates_only_response_retains_request_pair_and_raw_response_custody(echo):
    calculation_id = uuid4()
    response = {"rates": [{"rate_date": "2026-01-04", "rate": "1.3"}, {"rate_date": "2026-01-05", "rate": "1.4"}]}
    response.update(echo)
    snapshots = []

    async def read_fx(**kwargs):
        assert (kwargs["from_currency"], kwargs["to_currency"]) == ("EUR", "USD")
        return 200, response

    service = StatefulInputService(
        core_service=SimpleNamespace(get_fx_rates=read_fx),
        execution_store=SimpleNamespace(
            list_upstream_snapshot_ids=lambda _: set(),
            record_upstream_snapshots=lambda **kwargs: snapshots.extend(kwargs["snapshots"]),
        ),
    )
    status, payload = asyncio.run(
        service.get_fx_rates(
            from_currency="EUR",
            to_currency="USD",
            start_date=date(2026, 1, 4),
            end_date=date(2026, 1, 5),
            calculation_id=calculation_id,
        )
    )
    assert status == 200 and payload["points"] == [
        {"series_date": "2026-01-04", "fx_rate": "1.3"},
        {"series_date": "2026-01-05", "fx_rate": "1.4"},
    ]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["source_identifier"] == "EUR/USD"
    assert snapshot["response_fingerprint"] == _hash(response)
    snapshot["created_at_utc"] = "2026-01-06T01:00:00Z"
    member = _member([{"request_wire": snapshot["paging_metadata"], "response_wire": response}])
    retained = require_fx_snapshot_custody(
        member, reporting_currency="USD", calculation_id=calculation_id, snapshots=snapshots
    )
    assert len(retained) == 1 and retained[0].response_fingerprint == _hash(response)


@pytest.mark.parametrize("fault", ["request-from", "request-to", "response-from", "response-to", "response-null"])
def test_rates_only_custody_refuses_authenticated_pair_drift_and_optional_echo_contradictions(fault):
    calculation_id = uuid4()
    retrieval, snapshot = _retrieval(
        calculation_id, start="2026-01-04", end="2026-01-05", rates=[("2026-01-04", "1.3"), ("2026-01-05", "1.4")]
    )
    target, field = fault.split("-")
    retrieval[target + "_wire"]["from_currency" if field in ("from", "null") else "to_currency"] = (
        None if field == "null" else "GBP"
    )
    request_hash = _hash(retrieval["request_wire"])
    snapshot.update(
        request_fingerprint=request_hash,
        response_fingerprint=_hash(retrieval["response_wire"]),
        paging_metadata=retrieval["request_wire"],
        snapshot_id=hashlib.sha256(f"{calculation_id}:fx_rates:EUR/USD:{request_hash}".encode()).hexdigest(),
    )
    with pytest.raises(ValueError, match="quote pair is reversed or incompatible"):
        require_fx_snapshot_custody(
            _member([retrieval]), reporting_currency="USD", calculation_id=calculation_id, snapshots=[snapshot]
        )


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


def test_identity_conversion_cannot_retain_unowned_fx_snapshots():
    calculation_id = uuid4()
    wire = deepcopy(normalization_wire()["members"][0])
    wire.update(
        member_id="B",
        portfolio_reference_currency="USD",
        source_money_currency="USD",
        conversion_kind="IDENTITY",
        fixings=[],
        retrieval_wires=[],
    )
    member = CompositeFXMemberSource.model_validate(wire)
    assert member.conversion_kind == "IDENTITY" and not member.retrieval_wires
    assert (
        require_fx_snapshot_custody(member, reporting_currency="USD", calculation_id=calculation_id, snapshots=[]) == []
    )
    _, snapshot = _retrieval(
        calculation_id,
        start="2026-01-04",
        end="2026-01-05",
        source_currency="USD",
        rates=[("2026-01-04", "1"), ("2026-01-05", "1")],
    )
    with pytest.raises(ValueError, match="Identity conversion must not manufacture FX retrieval evidence"):
        require_fx_snapshot_custody(
            member, reporting_currency="USD", calculation_id=calculation_id, snapshots=[snapshot]
        )


def test_direct_conversion_requires_every_snapshot_to_have_source_owned_retrieval_wire():
    calculation_id = uuid4()
    first, one = _retrieval(
        calculation_id, start="2026-01-04", end="2026-01-05", rates=[("2026-01-04", "1.3"), ("2026-01-05", "1.4")]
    )
    extra, two = _retrieval(calculation_id, start="2026-01-03", end="2026-01-03", rates=[("2026-01-03", "1.2")])
    with pytest.raises(ValueError, match="Unconsumed FX snapshot"):
        require_fx_snapshot_custody(
            _member([first]), reporting_currency="USD", calculation_id=calculation_id, snapshots=[one, two]
        )
    assert (
        len(
            require_fx_snapshot_custody(
                _member([first, extra]), reporting_currency="USD", calculation_id=calculation_id, snapshots=[one, two]
            )
        )
        == 2
    )


@pytest.mark.parametrize(
    "fault",
    [
        "request-hash",
        "snapshot-id",
        "missing-wire",
        "duplicate-wire",
        "wrong-pair",
        "inverted-window",
        "stale-cut",
        "duplicate-rate",
        "outside-window",
        "nonpositive-rate",
        "wrong-fixing",
        "no-wires",
    ],
)
def test_direct_custody_refuses_corrupt_transport_and_observation_evidence(fault):
    calculation_id = uuid4()
    first, snapshot = _retrieval(
        calculation_id, start="2026-01-04", end="2026-01-05", rates=[("2026-01-04", "1.3"), ("2026-01-05", "1.4")]
    )
    retrievals = [first]
    if fault == "wrong-pair":
        first["response_wire"]["from_currency"] = "GBP"
    elif fault == "inverted-window":
        first["request_wire"]["start_date"] = "2026-01-06"
    elif fault in ("duplicate-rate", "outside-window", "nonpositive-rate", "wrong-fixing"):
        response = first["response_wire"]
        if fault == "duplicate-rate":
            response["rates"].append(deepcopy(response["rates"][0]))
        elif fault == "outside-window":
            response["rates"][0]["rate_date"] = "2026-01-03"
        else:
            response["rates"][0]["rate"] = "0" if fault == "nonpositive-rate" else "1.31"
    request_hash, response_hash = _hash(first["request_wire"]), _hash(first["response_wire"])
    snapshot.update(
        request_fingerprint=request_hash,
        response_fingerprint=response_hash,
        paging_metadata=first["request_wire"],
        snapshot_id=hashlib.sha256(f"{calculation_id}:fx_rates:EUR/USD:{request_hash}".encode()).hexdigest(),
    )
    member = _member(retrievals)
    if fault == "request-hash":
        snapshot["request_fingerprint"] = "1" * 64
    elif fault == "snapshot-id":
        snapshot["snapshot_id"] = "2" * 64
    elif fault == "missing-wire":
        snapshot["response_fingerprint"] = "3" * 64
    elif fault == "duplicate-wire":
        member = member.model_copy(update={"retrieval_wires": [*member.retrieval_wires, member.retrieval_wires[0]]})
    elif fault == "stale-cut":
        snapshot["as_of_date"] = "2026-01-04"
    elif fault == "no-wires":
        member = member.model_copy(update={"retrieval_wires": []})
        snapshot = None
    expected = {
        "request-hash": "Retained FX request identity differs",
        "snapshot-id": "Retained FX request identity differs",
        "missing-wire": "no unique matching FX retrieval",
        "duplicate-wire": "no unique matching FX retrieval",
        "wrong-pair": "quote pair is reversed or incompatible",
        "inverted-window": "window differs from custody",
        "stale-cut": "window differs from custody",
        "duplicate-rate": "invalid or out-of-window FX observation",
        "outside-window": "invalid or out-of-window FX observation",
        "nonpositive-rate": "invalid or out-of-window FX observation",
        "wrong-fixing": "Admitted fixing differs",
        "no-wires": "source-owned FX retrieval wires are unavailable",
    }[fault]
    with pytest.raises(ValueError, match=expected):
        require_fx_snapshot_custody(
            member,
            reporting_currency="USD",
            calculation_id=calculation_id,
            snapshots=[] if snapshot is None else [snapshot],
        )
