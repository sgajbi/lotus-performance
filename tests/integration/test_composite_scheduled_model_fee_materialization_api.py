"""Actual scheduled catalog/API/worker/reopen path with synthetic authority only."""

from decimal import ROUND_DOWN, ROUND_UP, Inexact, Rounded, localcontext
from fractions import Fraction
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.models.composite_authority import ManageCompositeDefinitionV2
from app.ports import composite_model_fees
from app.services.composite_metadata_store import CompositeMetadataStore
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from tests.composite_model_fee_helpers import model_fee_source_inputs
from tests.composite_scheduled_model_fee_helpers import band_rule, scheduled_source_inputs
from tests.integration import test_composite_model_fee_materialization_api as periodic_controls
from tests.integration.test_composite_materialization_api import STANDARD_ASSETS, install_source_wire_controls
from tests.integration.test_composite_model_fee_materialization_api import (
    prepare_registered_model_fee,
)

model_fee_database = periodic_controls.model_fee_database


def test_scheduled_registered_worker_preserves_original_economics_and_profile(
    monkeypatch, model_fee_database, capture=None
):
    _, wire, _, _ = scheduled_source_inputs()
    entries = wire["periods"][0]["member_rates"]
    entries[1]["schedule_rule"] = band_rule("MARGINAL_TIERED", threshold="100")
    entries[2]["schedule_rule"] = band_rule("WHOLE_AUM_BAND", threshold="300")
    packet, wire, command, _ = model_fee_source_inputs(wire)
    install_source_wire_controls(monkeypatch, tuple(packet[key] for key in ("definition", "membership", "attestation")))
    tenant = packet["definition"]["tenant_id"]
    headers = {"X-Tenant-Id": tenant, "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        command = prepare_registered_model_fee(client, monkeypatch, packet, wire, command)
        payload = command.model_dump(mode="json")
        accepted = client.post("/performance/composites/materializations", json=payload)
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        response = client.get(accepted.json()["result_path"])
        assert response.status_code == 200, response.text
        retained = response.json()
        assert retained["state"] == "COMPLETE", retained
        rates = {"A": Fraction(".012"), "B": Fraction(".008"), "C": Fraction(".006")}
        weighted = Fraction(0)
        for member in retained["members"]:
            fact, evidence = member["fact"], member["source_evidence"]
            assert evidence["contract_version"] == "composite-member-source.v5"
            fraction = Fraction(evidence["derived_period_fee_fraction"])
            assert abs(fraction - rates[member["portfolio_id"]] / 365) <= Fraction("1e-78")
            assert Fraction(evidence["fee_entry"]["fee_base_amount"]) == Fraction(fact["beginning_market_value"])
            assert tuple(Fraction(fact[key]) for key in ("beginning_market_value", "ending_market_value")) == tuple(
                Fraction(value) for value in STANDARD_ASSETS[member["portfolio_id"]]
            )
            assert Fraction(fact["return_value"]) == (1 + Fraction(evidence["gross_return"])) * (1 - fraction) - 1
            weighted += Fraction(fact["beginning_market_value"]) * Fraction(fact["return_value"]) / 600
            assert evidence["gross_evidence"]["calculation_request"]["portfolio"]["metric_basis"] == "GROSS"
        twr_request = {
            key: payload[key]
            for key in (
                "composite_id",
                "period_start",
                "period_end",
                "return_view",
                "reporting_currency",
                "restatement_sequence",
            )
        }
        aggregate = client.post("/performance/composites/twr", json=twr_request)
        assert aggregate.status_code == 200, aggregate.text
        assert abs(Fraction(str(aggregate.json()["periods"][0]["return_value"])) - weighted) <= Fraction("1e-12")
        reloaded = CompositeMaterializationStore(model_fee_database)
        try:
            original = reloaded.get(command.materialization_id, tenant_id=tenant)
            assert original.source.model_fee_wire == wire
            assert [item.model_dump(mode="json") for item in original.outcomes] == retained["members"]
        finally:
            reloaded.close()

        class NoLatestResolution:
            def resolve(self, request):
                raise AssertionError("Pinned replay must not resolve latest model profile")

        monkeypatch.setattr(composite_model_fees, "composite_model_fee_resolver", NoLatestResolution)
        assert client.post("/performance/composites/materializations", json=payload).status_code == 202
        assert client.get(accepted.json()["result_path"]).json() == retained
        assert (
            client.get(
                accepted.json()["result_path"], headers={**headers, "X-Tenant-Id": "different-tenant"}
            ).status_code
            == 404
        )
        if capture is not None:
            capture(packet, wire, command, retained, aggregate.json()["periods"])


@pytest.mark.parametrize("replace_current_definition", [False, True])
def test_scheduled_twr_full_response_isolates_ambient_decimal_state(
    monkeypatch, model_fee_database, replace_current_definition
):
    captured = {}

    def capture(packet, wire, command, retained, periods):
        captured.update(packet=packet, command=command)

    test_scheduled_registered_worker_preserves_original_economics_and_profile(
        monkeypatch, model_fee_database, capture=capture
    )
    command = captured["command"]
    if replace_current_definition:
        # Historical facts retain their original method. A later definition is
        # not authority to choose the arithmetic policy for those facts.
        periodic_packet, _, _, _ = model_fee_source_inputs()
        replacement = ManageCompositeDefinitionV2.model_validate(periodic_packet["definition"]).performance_definition()
        store = CompositeMetadataStore(model_fee_database)
        try:
            store.upsert_definition(replacement, tenant_id=periodic_packet["definition"]["tenant_id"])
        finally:
            store.close()
    headers = {
        "X-Tenant-Id": captured["packet"]["definition"]["tenant_id"],
        "X-Actor-Id": "operator",
        "X-Role": "DPM_COMPOSITE_CONSUMER",
    }
    base = command.model_dump(mode="json")
    request = {
        key: base[key]
        for key in (
            "composite_id",
            "period_start",
            "period_end",
            "return_view",
            "reporting_currency",
            "restatement_sequence",
        )
    }
    with TestClient(app, headers=headers) as client:
        for pinned in (False, True):
            payload = {**request, "calculation_id": str(uuid4())}
            if pinned:
                payload.pop("restatement_sequence")
                payload["materialization_ids"] = [str(command.materialization_id)]
            baseline = client.post("/performance/composites/twr", json=payload)
            assert baseline.status_code == 200, baseline.text
            for precision, rounding in ((9, ROUND_DOWN), (150, ROUND_UP)):
                with localcontext() as caller:
                    caller.prec, caller.rounding = precision, rounding
                    caller.Emin, caller.Emax = -9, 9
                    caller.traps[Inexact] = caller.traps[Rounded] = True
                    caller.clear_flags()
                    before = caller.copy()
                    actual = client.post("/performance/composites/twr", json=payload)
                    assert actual.status_code == 200, actual.text
                    assert actual.json() == baseline.json()
                    assert (caller.prec, caller.rounding, caller.Emin, caller.Emax, caller.traps, caller.flags) == (
                        before.prec,
                        before.rounding,
                        before.Emin,
                        before.Emax,
                        before.traps,
                        before.flags,
                    )


def test_later_scheduled_definition_preserves_historical_periodic_arithmetic(monkeypatch, model_fee_database):
    captured = {}

    def capture(packet, wire, command, retained, periods):
        captured.update(packet=packet, command=command)

    periodic_controls.test_registered_model_fee_worker_retention_replay_and_actual_net_refusal(
        monkeypatch, model_fee_database, basis="GROSS", capture=capture
    )
    command = captured["command"]
    tenant = captured["packet"]["definition"]["tenant_id"]
    headers = {"X-Tenant-Id": tenant, "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    base = command.model_dump(mode="json")
    payload = {
        key: base[key]
        for key in (
            "composite_id",
            "period_start",
            "period_end",
            "return_view",
            "reporting_currency",
            "restatement_sequence",
        )
    }
    payload["calculation_id"] = str(uuid4())
    with TestClient(app, headers=headers) as client:
        with localcontext() as caller:
            caller.prec, caller.rounding = 9, ROUND_DOWN
            before = client.post("/performance/composites/twr", json=payload)
        assert before.status_code == 200, before.text
        scheduled_packet, _, _, _ = scheduled_source_inputs()
        replacement = ManageCompositeDefinitionV2.model_validate(
            scheduled_packet["definition"]
        ).performance_definition()
        store = CompositeMetadataStore(model_fee_database)
        try:
            store.upsert_definition(replacement, tenant_id=tenant)
        finally:
            store.close()
        with localcontext() as caller:
            caller.prec, caller.rounding = 9, ROUND_DOWN
            after = client.post("/performance/composites/twr", json=payload)
        assert after.status_code == 200, after.text
        assert after.json() == before.json()
