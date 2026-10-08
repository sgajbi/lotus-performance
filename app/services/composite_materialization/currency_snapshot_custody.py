"""Reconcile source-owned fixing wires with actual retained retrieval fingerprints."""

import hashlib
import json
from datetime import date
from decimal import Decimal

from pydantic import TypeAdapter

from app.models.composite_currency_normalization import CompositeFXSnapshot
from app.models.composite_external_facts import DecimalWire


def _retrieval_digest(wire):
    # This is the existing StatefulInputService snapshot codec, not source-owned content identity.
    return hashlib.sha256(json.dumps(wire, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def require_fx_snapshot_custody(member, *, reporting_currency, calculation_id, snapshots):
    snapshots = [CompositeFXSnapshot.model_validate(row) for row in snapshots]
    if member.conversion_kind == "IDENTITY":
        if member.retrieval_wires or snapshots:
            raise ValueError("Identity conversion must not manufacture FX retrieval evidence")
        return snapshots
    pair = f"{member.source_money_currency}/{reporting_currency}"
    by_request_and_response = _index_snapshots(snapshots, pair, calculation_id)
    observed, economic_rates, seen = {}, {}, set()
    for retrieval in member.retrieval_wires:
        snapshot, response_hash = _matched_retrieval(retrieval, by_request_and_response, seen)
        start, end = _require_retrieval_window(member, reporting_currency, retrieval, snapshot)
        _retain_response_rates(retrieval.response_wire, response_hash, start, end, observed, economic_rates)
    if seen != by_request_and_response.keys():
        raise ValueError("Unconsumed FX snapshot has no source-owned retrieval wire")
    _require_admitted_observations(member, observed)
    return snapshots


def _index_snapshots(snapshots, pair, calculation_id):
    by_request_and_response = {}
    for snapshot in snapshots:
        key = (snapshot.request_fingerprint, snapshot.response_fingerprint)
        if snapshot.source_identifier != pair or key in by_request_and_response:
            raise ValueError("Ambiguous FX snapshot or currency-pair custody")
        request_hash = _retrieval_digest(snapshot.paging_metadata)
        snapshot_hash = hashlib.sha256(f"{calculation_id}:fx_rates:{pair}:{request_hash}".encode("utf-8")).hexdigest()
        if (snapshot.request_fingerprint, snapshot.snapshot_id) != (request_hash, snapshot_hash):
            raise ValueError("Retained FX request identity differs")
        by_request_and_response[key] = snapshot
    return by_request_and_response


def _matched_retrieval(retrieval, snapshots, seen):
    request, response = retrieval.request_wire, retrieval.response_wire
    response_hash = _retrieval_digest(response)
    retrieval_key = (_retrieval_digest(request), response_hash)
    snapshot = snapshots.get(retrieval_key)
    if snapshot is None or retrieval_key in seen or request != snapshot.paging_metadata:
        raise ValueError("Source fixing wire has no unique matching FX retrieval")
    seen.add(retrieval_key)
    return snapshot, response_hash


def _require_retrieval_window(member, reporting_currency, retrieval, snapshot):
    request, response = retrieval.request_wire, retrieval.response_wire
    if (
        request.get("from_currency"),
        request.get("to_currency"),
        response.get("from_currency"),
        response.get("to_currency"),
    ) != (member.source_money_currency, reporting_currency, member.source_money_currency, reporting_currency):
        raise ValueError("FX retrieval quote pair is reversed or incompatible")
    start, end = date.fromisoformat(request["start_date"]), date.fromisoformat(request["end_date"])
    if start > end or snapshot.as_of_date < end.isoformat():
        raise ValueError("FX retrieval window differs from custody")
    return start, end


def _retain_response_rates(response, response_hash, start, end, observed, economic_rates):
    response_dates = set()
    for row in response["rates"]:
        day, value = _valid_response_rate(row, start, end, response_dates)
        if day in economic_rates and economic_rates[day] != value:
            raise ValueError("Conflicting FX economics across retained retrieval windows")
        # Equal overlaps agree; there is no revision or duplicate-last precedence rule here.
        economic_rates[day] = value
        observed[(response_hash, day.isoformat())] = value


def _valid_response_rate(row, start, end, response_dates):
    day = date.fromisoformat(row["rate_date"])
    value = Decimal(TypeAdapter(DecimalWire).validate_python(row["rate"]))
    if day in response_dates or not start <= day <= end or value <= 0:
        raise ValueError("Ambiguous, invalid or out-of-window FX observation")
    response_dates.add(day)
    return day, value


def _require_admitted_observations(member, observed):
    if not member.retrieval_wires:
        raise ValueError("Retained source-owned FX retrieval wires are unavailable")
    for fixing in member.fixings:
        if observed.get((fixing.retrieval_response_fingerprint, fixing.fixing_date)) != Decimal(fixing.rate):
            raise ValueError("Admitted fixing differs from its retained FX response")
