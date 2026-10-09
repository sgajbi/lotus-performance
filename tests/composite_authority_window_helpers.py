"""Dated synthetic source ports over the real retained materialization/capture owners."""

from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

from app.models.composite_materialization import CompositeMemberMaterializationOutcome
from app.models.composites import CompositeTWRRequest
from app.models.portfolio_asset_evidence import PortfolioSourceAssetEvidence
from app.models.twr_requests import TWRResolvedExecutionRequest
from app.services.composite_materialization.application import run_materialization_attempt
from app.services.composite_materialization.member_evidence_policy import require_member_source_evidence
from app.services.reproducibility_service import generate_value_fingerprint
from tests.composite_authority_helpers import (
    command_for_packet,
    install_test_authorities,
    internal_day_packet,
    refresh_support_bindings,
)
from tests.composite_materialization_helpers import (
    MembershipSource,
    MemberSource,
    admitted,
    controlled_member_figures,
    controlled_member_request,
    running_job,
)


def dated_request(member, calculation_id, start, end, *, corrected=False):
    request = controlled_member_request(member, calculation_id, corrected=corrected).model_dump(mode="json")
    beginning, ret = controlled_member_figures(member, corrected=corrected)
    request["portfolio"].update(
        performance_start_date=start.isoformat(),
        report_start_date=start.isoformat(),
        report_end_date=end.isoformat(),
        valuation_points=[
            {
                "perf_date": (start + timedelta(days=offset)).isoformat(),
                "begin_mv": str(beginning),
                "end_mv": str(beginning * (1 + ret) if start + timedelta(days=offset) == end else beginning),
            }
            for offset in range((end - start).days + 1)
        ],
    )
    return TWRResolvedExecutionRequest.model_validate(request)


class DatedMemberSource(MemberSource):
    def read_member(self, command, reference, **authority):
        outcome = super().read_member(command, reference, **authority)
        payload = outcome.model_dump(mode="json")
        evidence = payload["source_evidence"]
        evidence["calculation_request"] = dated_request(
            reference.portfolio_id,
            reference.calculation_id,
            command.period_start,
            command.period_end,
            corrected=self.corrected,
        ).model_dump(mode="json")
        beginning, ret = controlled_member_figures(reference.portfolio_id, corrected=self.corrected)
        assets = PortfolioSourceAssetEvidence.model_validate(
            {
                "portfolio_currency": "USD",
                "observations": [
                    {
                        "valuation_date": (command.period_start + timedelta(days=offset)).isoformat(),
                        "beginning_market_value": str(beginning),
                        "ending_market_value": str(
                            beginning * (1 + ret)
                            if command.period_start + timedelta(days=offset) == command.period_end
                            else beginning
                        ),
                    }
                    for offset in range((command.period_end - command.period_start).days + 1)
                ],
            }
        )
        evidence["source_assets"] = assets.model_dump(mode="json")
        evidence["asset_evidence_fingerprint"] = generate_value_fingerprint(assets, "portfolio-source-assets.v1")[0]
        for snapshot in evidence["core_snapshots"]:
            snapshot["request_as_of_date"] = command.period_end.isoformat()
        from app.models.composite_materialization import CompositeMemberSourceEvidence

        receipt = CompositeMemberSourceEvidence.model_validate(evidence)
        payload["fact"]["source_snapshot_id"] = generate_value_fingerprint(receipt, "composite-member-source.v1")[0]
        result = CompositeMemberMaterializationOutcome.model_validate(payload)
        require_member_source_evidence(command, result)
        return result


def window_command(start, end, *, corrected=False, tenant="tenant-a"):
    def rebind(value, key=None):
        if isinstance(value, dict):
            return {name: rebind(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [rebind(item, key) for item in value]
        if value == "synthetic-tenant-a":
            return tenant
        if value == "SYNTHETIC_EXTERNAL_MONTHLY_USD":
            return "COMPOSITE"
        if value == "2026-01-05":
            return "2026-03-31" if key in {"effective_to", "coverage_to", "period_end", "end"} else "2026-01-01"
        return value

    packet = rebind(internal_day_packet())
    profile = packet["definition"]["source_authority"]["payload"]
    ending = deepcopy(next(item for item in profile["selections"] if item["fact"] == "BEGINNING_ASSETS"))
    ending.update(selection_id="ending_assets", fact="ENDING_ASSETS")
    profile["selections"].append(ending)
    profile["selections"].sort(key=lambda item: item["selection_id"])
    method = packet["supporting_payloads"]["return_method"]["payload"]
    method.update(
        fee_view="NET_ACTUAL",
        period_start="2026-01-01",
        period_end="2026-03-31",
        required_periods=[
            {"start": "2026-01-05", "end": "2026-01-05"},
            {"start": "2026-01-01", "end": "2026-01-31"},
            {"start": "2026-02-01", "end": "2026-02-28"},
            {"start": "2026-03-01", "end": "2026-03-31"},
        ],
    )
    refresh_support_bindings(packet)
    references = []
    for member in ("A", "B", "C"):
        calculation_id = uuid4()
        request = dated_request(member, calculation_id, start, end, corrected=corrected)
        fingerprint, calculation_hash = generate_value_fingerprint(request, "controlled-test-v1")
        references.append(
            {
                "portfolio_id": member,
                "calculation_id": str(calculation_id),
                "input_fingerprint": fingerprint,
                "calculation_hash": calculation_hash,
            }
        )
    command = command_for_packet(
        packet,
        period_start=start,
        period_end=end,
        member_calculations=references,
        return_view="NET_ACTUAL",
        restatement_sequence=start.month + (12 if corrected else 0),
    )
    selections = []
    for reference in command.member_calculations:
        outcome = DatedMemberSource(corrected=corrected).read_member(
            command,
            reference,
            tenant_id=tenant,
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
        )
        for original in profile["selections"]:
            selection = deepcopy(original)
            provider = "lotus-performance" if selection["fact"] == "MEMBER_RETURN" else "lotus-core"
            selection.update(
                selection_id=selection["selection_id"] + "_" + reference.portfolio_id,
                member_ids=[reference.portfolio_id],
                provider_id=provider,
                economic_authority=provider,
                source_product="CompositeMemberSourceEvidence",
                source_contract_version="composite-member-source.v1",
                source_revision=str(reference.calculation_id),
                source_watermark=reference.input_fingerprint,
                source_digest=generate_value_fingerprint(outcome.source_evidence, "composite-member-source.v1")[0],
            )
            selections.append(selection)
    profile["selections"] = sorted(selections, key=lambda item: item["selection_id"])
    refresh_support_bindings(packet)
    command = command.model_copy(
        update={
            "definition_content_hash": packet["definition"]["content_hash"],
            "membership_content_hash": packet["membership"]["content_hash"],
            "attestation_content_hash": packet["attestation"]["content_hash"],
        }
    )
    return command, packet


def materialize_window(fixture, start, end, *, corrected=False, tenant="tenant-a"):
    command, packet = window_command(start, end, corrected=corrected, tenant=tenant)
    fixture.source_packets.append(packet)
    install_test_authorities(fixture.monkeypatch, fixture.source_packets)
    for maker in (
        packet["definition"]["created_by"],
        packet["membership"]["decided_by"],
        packet["attestation"]["attested_by"],
    ):
        fixture.verifier.canonical_identities[maker] = "synthetic-human-maker"
    products = [packet[key] for key in ("definition", "membership", "attestation")]
    result = run_materialization_attempt(
        running_job(fixture.jobs, command, tenant_id=tenant),
        job_store=fixture.jobs,
        ledger=fixture.ledger,
        facts=fixture.store,
        membership_source=MembershipSource(admitted(command, products, tenant_id=tenant)),
        member_source=DatedMemberSource(corrected=corrected),
    )
    fixture.record("dated_materialization_progress", result)
    assert result.state == "COMPLETE"
    return command


def capture_windows(fixture, commands, *, tenant="tenant-a"):
    return fixture.capture(
        CompositeTWRRequest(
            composite_id=commands[0].composite_id,
            period_start=commands[0].period_start,
            period_end=commands[-1].period_end,
            return_view=commands[0].return_view,
            reporting_currency=commands[0].reporting_currency,
            materialization_ids=[command.materialization_id for command in commands],
        ),
        tenant=tenant,
    )


JANUARY = (date(2026, 1, 1), date(2026, 1, 31))
FEBRUARY = (date(2026, 2, 1), date(2026, 2, 28))
