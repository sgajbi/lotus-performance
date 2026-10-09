"""Registered scheduled multiwindow economics and immutable method compatibility."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.services.composite_materialization.model_fee_calculation import selected_facts_use_scheduled_model_fee
from core.errors import APIUnprocessableEntityError
from main import app
from tests.composite_linked_contribution_helpers import LINKED_PATH, independent_reference, linked_request
from tests.composite_scheduled_model_fee_helpers import band_rule, scheduled_source_inputs
from tests.integration import test_composite_model_fee_materialization_api as periodic_controls
from tests.integration.test_composite_linked_model_fee_api import _publish
from tests.integration.test_composite_scheduled_model_fee_materialization_api import (
    test_scheduled_registered_worker_preserves_original_economics_and_profile as publish_scheduled_control,
)

model_fee_database = periodic_controls.model_fee_database


@pytest.mark.parametrize("changed_binding", [False, True])
def test_registered_scheduled_history_unequal_rates_and_full_binding(monkeypatch, model_fee_database, changed_binding):
    _, wire, _, _ = scheduled_source_inputs()
    first = wire["periods"][0]
    first["member_rates"][1]["schedule_rule"] = band_rule("MARGINAL_TIERED", threshold="100")
    first["member_rates"][2]["schedule_rule"] = band_rule("WHOLE_AUM_BAND", threshold="300")
    second = deepcopy(first)
    second.update(period_start="2026-01-06", period_end="2026-01-06")
    for row, annual_rate in zip(second["member_rates"], ("0.02", "0.01", "0.004"), strict=True):
        row.update(
            entry_id="second." + row["member_id"],
            schedule_rule={"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": annual_rate},
        )
    wire.update(effective_to="2026-01-06", periods=[first, second])
    revised = deepcopy(wire)
    if changed_binding:
        revised["revision"] = "profile.2"
    headers = {"X-Tenant-Id": wire["tenant_id"], "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    packets, approvals = [], []
    with TestClient(app, headers=headers) as client:
        first_command, first_receipt = _publish(client, monkeypatch, wire, "2026-01-05", 1, packets, approvals)
        second_command, second_receipt = _publish(client, monkeypatch, revised, "2026-01-06", 2, packets, approvals)
        store = CompositeMaterializationStore(model_fee_database)
        try:
            records = [
                store.get(command.materialization_id, tenant_id=wire["tenant_id"])
                for command in (first_command, second_command)
            ]
            facts = [outcome.fact for record in records for outcome in record.outcomes if outcome.fact is not None]
            selected = store.get_for_member_return_facts(facts, tenant_id=wire["tenant_id"])
            if changed_binding:
                with pytest.raises(APIUnprocessableEntityError) as error:
                    selected_facts_use_scheduled_model_fee(facts, selected)
                assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_MISMATCH"
            else:
                assert selected_facts_use_scheduled_model_fee(facts, selected)
        finally:
            store.close()
        linked_payload = {**linked_request([first_command, second_command]), "return_view": "NET_MODEL_FEE"}
        twr_payload = {key: value for key, value in linked_payload.items() if key not in {"method", "metric_id"}}
        twr = client.post("/performance/composites/twr", json=twr_payload)
        linked = client.post(LINKED_PATH, json=linked_payload)
        if changed_binding:
            for response in (twr, linked):
                assert response.status_code == 422, response.text
                assert response.json()["error_code"] == "COMPOSITE_VECTOR_METHOD_MISMATCH"
                assert "members" not in response.json() and "periods" not in response.json()
            return
        assert twr.status_code == linked.status_code == 200, (twr.text, linked.text)
        expected_periods = []
        contributions = {member: [] for member in ("A", "B", "C")}
        actual_periods = []
        with localcontext() as context:
            context.prec = 100
            for receipt, annual in zip(
                (first_receipt, second_receipt),
                ((".012", ".008", ".006"), (".02", ".01", ".004")),
                strict=True,
            ):
                period = Fraction(0)
                actual_period = Decimal(0)
                for row, rate, assets, gross in zip(
                    receipt["members"], annual, (100, 200, 300), (".1", ".05", "-.02"), strict=True
                ):
                    fact, evidence = row["fact"], row["source_evidence"]
                    # The original engine's retained gross Decimal is the
                    # authority; its float-derived source must not be silently
                    # replaced with the ideal fixture ratio.
                    original_gross = Fraction(evidence["gross_return"])
                    assert abs(original_gross - Fraction(gross)) <= Fraction("1e-12")
                    model = (1 + original_gross) * (1 - Fraction(rate) / 365) - 1
                    assert abs(Fraction(fact["return_value"]) - model) < Fraction("1e-75")
                    assert Fraction(fact["beginning_market_value"]) == assets
                    assert Fraction(fact["ending_market_value"]) == assets * (1 + Fraction(gross))
                    assert evidence["fee_entry"]["fee_base_amount"] == str(assets)
                    period += Fraction(assets, 600) * model
                    contribution = Decimal(fact["return_value"]) * Decimal(assets) / Decimal(600)
                    contributions[row["portfolio_id"]].append(contribution)
                    actual_period += contribution
                expected_periods.append(period)
                actual_periods.append(actual_period)
            expected_linked = independent_reference(actual_periods, contributions.values())
            for row, expected in zip(linked.json()["members"], expected_linked, strict=True):
                assert abs(Decimal(row["linked_contribution"]) - expected) < Decimal("1e-65")
        body = twr.json()
        for row, expected in zip(body["periods"], expected_periods, strict=True):
            assert abs(Fraction(row["return_value"]) - expected) <= Fraction("1e-12")
            assert Fraction(row["beginning_market_value"]) == 600
            assert Fraction(row["ending_market_value"]) == 614
        cumulative = (1 + expected_periods[0]) * (1 + expected_periods[1]) - 1
        assert abs(Fraction(body["cumulative_return"]) - cumulative) <= Fraction("1e-12")
        assert body["selection_manifest"]["windows"][0]["method_binding"] == first_command.model_fee_binding.model_dump(
            mode="json"
        )
        assert linked.json()["qualification"] == "RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"


def test_selected_model_fee_method_requires_exact_tenant_scope_and_retained_outcomes(monkeypatch, model_fee_database):
    captured = {}

    def capture(packet, wire, command, retained, periods):
        captured.update(tenant=wire["tenant_id"], command=command)

    publish_scheduled_control(monkeypatch, model_fee_database, capture=capture)
    store = CompositeMaterializationStore(model_fee_database)
    try:
        record = store.get(captured["command"].materialization_id, tenant_id=captured["tenant"])
        facts = [outcome.fact for outcome in record.outcomes if outcome.fact is not None]
        selected = store.get_for_member_return_facts(facts, tenant_id=captured["tenant"])
        assert selected_facts_use_scheduled_model_fee(facts, selected)
        with pytest.raises(APIUnprocessableEntityError) as error:
            selected_facts_use_scheduled_model_fee(facts, [replace(record, state="PUBLISHING")])
        assert error.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_CONTEXT_UNAVAILABLE"
        for tenant, selected_facts in (
            ("different-tenant", facts),
            (captured["tenant"], [fact.model_copy(update={"restatement_sequence": 2}) for fact in facts]),
        ):
            with pytest.raises(APIUnprocessableEntityError) as error:
                store.get_for_member_return_facts(selected_facts, tenant_id=tenant)
            assert error.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_CONTEXT_UNAVAILABLE"
        for selected_facts in (
            facts[:-1],
            [facts[0].model_copy(update={"beginning_market_value": Decimal("101")}), *facts[1:]],
            [facts[0].model_copy(update={"return_value": Decimal("0.01")}), *facts[1:]],
        ):
            with pytest.raises(APIUnprocessableEntityError) as error:
                selected_facts_use_scheduled_model_fee(selected_facts, selected)
            assert error.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_CONTEXT_UNAVAILABLE"
    finally:
        store.close()
