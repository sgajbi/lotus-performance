"""Controlled daily monthly custody using the shipped engine and snapshot codec."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.composite_authority import EvidenceBinding, authority_digest
from app.models.composite_materialization import CompositeMemberSourceEvidence
from app.models.portfolio_asset_evidence import PortfolioSourceAssetEvidence
from app.models.twr_requests import TWRResolvedExecutionRequest
from app.services.composite_materialization.currency_normalization import normalize_member_money
from app.services.composite_materialization.currency_source_admission import (
    admit_composite_fx_source,
    fx_resolution_for_command,
)
from app.services.reproducibility_service import generate_value_fingerprint
from app.services.stateful_input_service import StatefulInputService
from tests.composite_currency_normalization_helpers import normalization_wire, synthetic_fx_verification
from tests.unit.services.test_composite_annual_dispersion_service import month_record, year_records


def normalized_year_records(monkeypatch, *, mismatch=None):
    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
        lambda: SimpleNamespace(verify=synthetic_fx_verification),
    )
    records = year_records()
    if mismatch == "membership":
        records = [month_record(month, count=6 if month < 7 else 7) for month in range(1, 13)]
    return [normalized_month_record(record, mismatch) for record in records]


def _daily_native(record, outcome, currency):
    original = outcome.source_evidence
    days = [
        record.command.period_start + timedelta(days=index)
        for index in range((record.command.period_end - record.command.period_start).days + 1)
    ]
    points = [{"perf_date": day, "begin_mv": "100", "end_mv": "100"} for day in days]
    points[-1]["end_mv"] = str(outcome.fact.ending_market_value)
    reference = next(ref for ref in record.command.member_calculations if ref.portfolio_id == outcome.portfolio_id)
    portfolio = {
        **original.calculation_request.portfolio.model_dump(),
        "calculation_id": reference.calculation_id,
        "currency": currency,
        "report_start_date": record.command.period_start,
        "report_end_date": record.command.period_end,
        "rounding_precision": 12,
        "valuation_points": points,
    }
    if currency != record.command.reporting_currency:
        rate_days = [days[0] - timedelta(days=1), *days]
        portfolio.update(
            currency_mode="BOTH",
            report_ccy=record.command.reporting_currency,
            fx={"rates": [{"date": day, "ccy": currency, "rate": "1"} for day in rate_days]},
        )
    request = TWRResolvedExecutionRequest.model_validate({"portfolio": portfolio})
    fingerprint, calculation_hash = generate_value_fingerprint(request, original.engine_version)
    assets = PortfolioSourceAssetEvidence(
        portfolio_currency=currency,
        observations=[
            {
                "valuation_date": point["perf_date"],
                "beginning_market_value": point["begin_mv"],
                "ending_market_value": point["end_mv"],
            }
            for point in points
        ],
    )
    return CompositeMemberSourceEvidence.model_validate(
        {
            **original.model_dump(),
            "calculation_request": request,
            "input_fingerprint": fingerprint,
            "calculation_hash": calculation_hash,
            "source_assets": assets,
            "asset_evidence_fingerprint": generate_value_fingerprint(assets, "portfolio-source-assets.v1")[0],
        }
    )


def _member_wire(command, native, identity, template):
    member = {
        "member_id": identity,
        "portfolio_reference_currency": "USD",
        "source_money_currency": native.source_assets.portfolio_currency,
        "input_fingerprint": native.input_fingerprint,
        "calculation_hash": native.calculation_hash,
        "conversion_kind": "IDENTITY",
        "fixings": [],
        "retrieval_wires": [],
    }
    if member["source_money_currency"] == command.reporting_currency:
        return member, []
    start, end = command.period_start - timedelta(days=1), command.period_end
    days = [start + timedelta(days=index) for index in range((end - start).days + 1)]
    currency = member["source_money_currency"]
    request = {
        "from_currency": currency,
        "to_currency": command.reporting_currency,
        "start_date": str(start),
        "end_date": str(end),
    }
    response = {
        "from_currency": currency,
        "to_currency": command.reporting_currency,
        "rates": [{"rate_date": str(day), "rate": "1"} for day in days],
    }
    snapshot = StatefulInputService(core_service=SimpleNamespace())._build_snapshot(
        calculation_id=native.calculation_request.portfolio.calculation_id,
        upstream_endpoint="fx_rates",
        source_identifier=currency + "/" + command.reporting_currency,
        as_of_date=end,
        request_payload=request,
        response=(200, response),
    )
    snapshot["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    member.update(
        conversion_kind="DIRECT",
        retrieval_wires=[{"request_wire": request, "response_wire": response}],
        fixings=[
            {
                **template,
                "fixing_date": str(day),
                "source_currency": currency,
                "reporting_currency": command.reporting_currency,
                "rate": "1",
                "observed_at": str(day) + "T21:00:00Z",
                "revision_available_at": str(day) + "T21:01:00Z",
                "retrieval_response_fingerprint": snapshot["response_fingerprint"],
            }
            for day in days
        ],
    )
    return member, [snapshot]


def normalized_month_record(record, mismatch=None):
    command = record.command
    natives = {
        item.portfolio_id: _daily_native(
            record,
            item,
            "EUR"
            if mismatch == "member-regime" and command.period_start.month >= 7 and item.portfolio_id == "1"
            else "USD",
        )
        for item in record.outcomes
    }
    references = [
        {
            **ref.model_dump(),
            "input_fingerprint": natives[ref.portfolio_id].input_fingerprint,
            "calculation_hash": natives[ref.portfolio_id].calculation_hash,
        }
        for ref in command.member_calculations
    ]
    command = type(command).model_validate({**command.model_dump(), "member_calculations": references})
    wire = normalization_wire()
    template = deepcopy(wire["members"][0]["fixings"][0])
    wire.update(
        tenant_id="tenant-a",
        composite_id=command.composite_id,
        definition_content_hash=command.definition_content_hash,
        membership_content_hash=command.membership_content_hash,
        attestation_content_hash=command.attestation_content_hash,
        return_view=str(command.return_view),
        period_start=str(command.period_start),
        period_end=str(command.period_end),
        reporting_currency=command.reporting_currency,
        source_as_of_cut="2027-01-01T01:00:00Z",
    )
    wire["method"].update(
        effective_to="2026-12-31",
        revision="method2" if mismatch == "method" and command.period_start.month >= 7 else "method1",
    )
    wire["method_binding"].update(revision=wire["method"]["revision"], digest=authority_digest(wire["method"]))
    members_and_snapshots = [
        _member_wire(command, natives[item.portfolio_id], item.portfolio_id, template) for item in record.outcomes
    ]
    wire["members"] = [item[0] for item in members_and_snapshots]
    binding = EvidenceBinding(
        product_name=wire["product_name"],
        product_version="v1",
        revision=wire["revision"],
        digest=authority_digest(wire),
    )
    command = type(command).model_validate({**command.model_dump(), "currency_normalization_binding": binding})
    admitted = admit_composite_fx_source(fx_resolution_for_command(command, tenant_id="tenant-a"), retained_wire=wire)
    outcomes = []
    for original, (_, snapshots) in zip(record.outcomes, members_and_snapshots, strict=True):
        evidence = normalize_member_money(
            command, natives[original.portfolio_id], admitted, member_id=original.portfolio_id, fx_snapshots=snapshots
        )
        fact = original.fact.model_copy(
            update={
                "reporting_currency": command.reporting_currency,
                "period_start": command.period_start,
                "period_end": command.period_end,
                "calculation_id": str(evidence.native_evidence.calculation_request.portfolio.calculation_id),
                "source_fingerprint": evidence.native_evidence.calculation_hash,
                "source_snapshot_id": generate_value_fingerprint(evidence, "composite-member-source.v3")[0],
            }
        )
        outcomes.append(original.model_copy(update={"fact": fact, "source_evidence": evidence}))
    return replace(
        record,
        command=command,
        outcomes=outcomes,
        source=record.source.model_copy(update={"currency_normalization_wire": wire}),
    )
