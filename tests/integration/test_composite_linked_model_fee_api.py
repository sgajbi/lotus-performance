"""Linked consumption of one complete approved fee profile, through existing native receipts."""

from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import get_composite_materialization_store
from app.core.config import get_settings
from app.ports import composite_external_evidence
from app.services.composite_materialization.source_contract import PinnedCompositeSource
from app.services.compute_job_store import compute_job_store
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_authority_helpers import (
    command_for_packet,
    install_test_authorities,
    refresh_support_bindings,
    rehash_definition,
)
from tests.composite_linked_contribution_helpers import LINKED_PATH, independent_reference, linked_request
from tests.composite_model_fee_helpers import SyntheticModelFeeApproval, model_fee_source_inputs
from tests.integration import test_composite_model_fee_materialization_api as model_fee_controls
from tests.integration.test_composite_materialization_api import create_stateful_member, install_source_wire_controls


def _move_packet(value, day, version):
    if isinstance(value, dict):
        return {key: _move_packet(item, day, version) for key, item in value.items()}
    if isinstance(value, list):
        return [_move_packet(item, day, version) for item in value]
    if value == "2026-01-05":
        return day
    if value == version:
        return version + "." + day
    return value


def _packet(wire, day):
    packet, _, command, _ = model_fee_source_inputs(wire)
    packet = _move_packet(packet, day, packet["definition"]["definition_version"])
    refresh_support_bindings(packet)
    binding = command.model_fee_binding.model_dump(mode="json")
    profile = packet["definition"]["source_authority"]["payload"]
    profile["return_method_binding"] = deepcopy(binding)
    for selection in profile["selections"]:
        if selection["fact"] == "MEMBER_RETURN":
            selection["method_profile_binding"] = deepcopy(binding)
    packet["definition"]["authority_approval"]["claims"]["method_evidence_digest"] = binding["digest"]
    rehash_definition(packet["definition"])
    return packet, command_for_packet(
        packet,
        period_start=day,
        period_end=day,
        return_view="NET_MODEL_FEE",
        model_fee_binding=command.model_fee_binding,
    )


def _publish(client, monkeypatch, wire, day, sequence, packets, approvals):
    packet, command = _packet(wire, day)
    install_source_wire_controls(
        monkeypatch, tuple(packet[key] for key in ("definition", "membership", "attestation")), performance_day=day
    )
    with monkeypatch.context() as dated:
        dated.setattr(
            model_fee_controls,
            "create_stateful_member",
            lambda *args, **kwargs: create_stateful_member(*args, **kwargs, performance_day=day),
        )
        command = model_fee_controls.prepare_registered_model_fee(client, monkeypatch, packet, wire, command)
    command = command.model_copy(
        update={
            "period_start": date.fromisoformat(day),
            "period_end": date.fromisoformat(day),
            "restatement_sequence": sequence,
        }
    )
    packets.append(packet)
    raw_source = {key: packet[key] for key in ("definition", "membership", "attestation")}
    approvals.append(
        SyntheticModelFeeApproval(
            wire, PinnedCompositeSource.model_validate({**raw_source, "wire_evidence": raw_source})
        )
    )
    install_test_authorities(monkeypatch, packets)

    class AllMethods:
        def verify(self, request):
            return any(approval.verify(request) for approval in approvals)

    monkeypatch.setattr(composite_external_evidence, "method_approval_verifier", AllMethods)
    accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
    assert accepted.status_code == 202, accepted.text
    assert process_pending_jobs(limit=1) == 1
    receipt = client.get(accepted.json()["result_path"])
    job = compute_job_store.get_job(command.calculation_id)
    assert receipt.status_code == 200 and receipt.json()["state"] == "COMPLETE", (
        job.failure.error_code if job.failure else None
    )
    return command, receipt.json()


@pytest.mark.parametrize("changed_binding", [False, True])
def test_registered_linked_one_model_fee_profile_and_changed_binding_refusal(monkeypatch, tmp_path, changed_binding):
    url = "sqlite:///" + (tmp_path / "linked-fee.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    _, wire, _, _ = model_fee_source_inputs()
    wire["effective_to"] = "2026-01-06"
    second = deepcopy(wire["periods"][0])
    second.update(period_start="2026-01-06", period_end="2026-01-06")
    for row, rate in zip(second["member_rates"], ("0.004", "0.005", "0.006"), strict=True):
        row.update(entry_id="second." + row["member_id"], period_fee_fraction=rate)
    wire["periods"].append(second)
    revised_wire = deepcopy(wire)
    if changed_binding:
        revised_wire["revision"] = "profile.2"
    headers = {"X-Tenant-Id": wire["tenant_id"], "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    packets, approvals = [], []
    with TestClient(app, headers=headers) as client:
        first_command, first_receipt = _publish(client, monkeypatch, wire, "2026-01-05", 1, packets, approvals)
        second_command, second_receipt = _publish(
            client, monkeypatch, revised_wire, "2026-01-06", 2, packets, approvals
        )
        payload = {**linked_request([first_command, second_command]), "return_view": "NET_MODEL_FEE"}
        response = client.post(LINKED_PATH, json=payload)
        if changed_binding:
            assert (
                response.status_code == 422 and response.json()["error_code"] == "COMPOSITE_VECTOR_METHOD_MISMATCH"
            ), response.text
            assert "members" not in response.json()
            return
        assert response.status_code == 200, response.text
        with localcontext() as context:
            context.prec = 90
            contributions = {member: [] for member in ("A", "B", "C")}
            period_returns = []
            for receipt in (first_receipt, second_receipt):
                members = receipt["members"]
                assets = sum((Decimal(row["fact"]["beginning_market_value"]) for row in members), Decimal(0))
                returns = []
                for row in members:
                    fact = row["fact"]
                    contribution = Decimal(fact["return_value"]) * Decimal(fact["beginning_market_value"]) / assets
                    contributions[row["portfolio_id"]].append(contribution)
                    returns.append(contribution)
                period_returns.append(sum(returns, Decimal(0)))
            expected = independent_reference(period_returns, contributions.values())
            for row, oracle in zip(response.json()["members"], expected, strict=True):
                assert abs(Decimal(row["linked_contribution"]) - oracle) < Decimal("1e-65")
        for command in (first_command, second_command):
            record = get_composite_materialization_store().get(command.materialization_id, tenant_id=wire["tenant_id"])
            assert record.source.model_fee_wire == wire
        assert [row["source_evidence"]["fee_entry"] for row in first_receipt["members"]] == wire["periods"][0][
            "member_rates"
        ]
        assert [row["source_evidence"]["fee_entry"] for row in second_receipt["members"]] == wire["periods"][1][
            "member_rates"
        ]
        mixed = client.post(LINKED_PATH, json={**payload, "return_view": "GROSS"})
        assert mixed.status_code == 422 and "members" not in mixed.json()

        class UnavailableApproval:
            def verify(self, request):
                return False

        monkeypatch.setattr(composite_external_evidence, "method_approval_verifier", UnavailableApproval)
        refused = client.post(LINKED_PATH, json=payload)
        assert refused.status_code == 503 and "members" not in refused.json(), refused.text
