"""Registered source API/worker -> retained selection -> registered fee-drag analysis.
All producer and independent-verifier controls here are synthetic, not bank approval.
"""

import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Inexact, Rounded, localcontext
from fractions import Fraction
from importlib import import_module
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.composite_fee_drag import fee_drag_openapi_examples
from app.core.config import get_settings
from app.models.composite_fee_drag import CompositeFeeDragRequest
from app.ports import composite_model_fees
from app.services.composite_fee_drag.application import calculate_model_fee_drag
from core.errors import APIError
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks import test_postgres_composite_model_fee as postgres_controls
from tests.composite_linked_contribution_helpers import linked_request
from tests.composite_model_fee_helpers import model_fee_source_inputs
from tests.composite_scheduled_model_fee_helpers import scheduled_source_inputs
from tests.integration import test_composite_linked_model_fee_api as linked_controls
from tests.integration.test_composite_linked_model_fee_api import _publish

populated_model_fee_postgres = postgres_controls.populated_model_fee_postgres


@pytest.fixture(autouse=True)
def model_fee_database(monkeypatch, tmp_path, request):
    if os.environ.get("LOTUS_POSTGRES_PLAN_DATABASE_URL"):
        _, url = request.getfixturevalue("populated_model_fee_postgres")
    else:
        url = "sqlite:///" + (tmp_path / "fee-drag.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    return url


def profile(*, scheduled, changed_binding=False, zero=False):
    _, wire, _, _ = scheduled_source_inputs() if scheduled else model_fee_source_inputs()
    first = wire["periods"][0]
    second = deepcopy(first)
    second.update(period_start="2026-01-06", period_end="2026-01-06")
    for index, period in enumerate((first, second)):
        for member, entry in enumerate(period["member_rates"]):
            entry["entry_id"] = f"period{index}." + entry["member_id"]
            rate = "0" if zero else (("0.012", "0.008", "0.006"), ("0.02", "0.01", "0.004"))[index][member]
            if scheduled:
                entry["schedule_rule"] = {"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": rate}
            else:
                entry["period_fee_fraction"] = rate
    wire.update(effective_to="2026-01-06", periods=[first, second])
    revised = deepcopy(wire)
    if changed_binding:
        revised["revision"] = "profile.2"
    return wire, revised


def oracle(receipts):
    gross_growth = model_growth = Fraction(1)
    periods = []
    for receipt in receipts:
        members = [row for row in receipt["members"] if row["state"] == "READY"]
        total = sum(Fraction(row["fact"]["beginning_market_value"]) for row in members)
        gross = model = Fraction(0)
        for row in members:
            evidence, fact = row["source_evidence"], row["fact"]
            original = Fraction(evidence["gross_return"])
            entry = evidence["fee_entry"]
            fee = (
                Fraction(entry["period_fee_fraction"])
                if "period_fee_fraction" in entry
                else (Fraction(entry["schedule_rule"]["annual_model_wealth_rate"]) / 365)
            )
            weight = Fraction(fact["beginning_market_value"]) / total
            gross += weight * original
            model += weight * ((1 + original) * (1 - fee) - 1)
        periods.append((gross, model, gross - model))
        gross_growth *= 1 + gross
        model_growth *= 1 + model
    return gross_growth - 1, model_growth - 1, gross_growth - model_growth, periods


def publish_fee_drag_example(client, monkeypatch):
    wire, _ = profile(scheduled=True)
    packets, approvals, commands = [], [], []
    original_command = linked_controls.command_for_packet
    original_member = linked_controls.create_stateful_member

    class SyntheticRetrievalClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 9, 12, tzinfo=UTC)
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    def pinned_command(packet, **overrides):
        return original_command(
            packet,
            **overrides,
            materialization_id=uuid5(NAMESPACE_URL, "fee-drag-materialization:" + example_day),
            calculation_id=uuid5(NAMESPACE_URL, "fee-drag-worker:" + example_day),
        )

    def pinned_member(client, member, **kwargs):
        return original_member(
            client,
            member,
            **kwargs,
            calculation_id=uuid5(NAMESPACE_URL, "fee-drag-native:" + kwargs["performance_day"] + ":" + member),
        )

    with monkeypatch.context() as identities:
        # Pin the synthetic capture clock before storage; never normalize or rewrite retained source digests.
        identities.setattr(import_module("app.services.execution_registry"), "datetime", SyntheticRetrievalClock)
        identities.setattr(linked_controls, "command_for_packet", pinned_command)
        identities.setattr(linked_controls.model_fee_controls, "command_for_packet", pinned_command)
        identities.setattr(linked_controls, "create_stateful_member", pinned_member)
        for index, example_day in enumerate(("2026-01-05", "2026-01-06")):
            command, _ = _publish(client, monkeypatch, wire, example_day, index + 1, packets, approvals)
            commands.append(command)
    payload = {**linked_request(commands), "metric_id": "MODEL_FEE_DRAG", "return_view": "NET_MODEL_FEE"}
    payload.pop("method")
    return payload


def test_packaged_fee_drag_full_response_replay_and_refusals_match_registered_http(monkeypatch, model_fee_database):
    wire, _ = profile(scheduled=True)
    headers = {
        "X-Tenant-Id": wire["tenant_id"],
        "X-Actor-Id": "operator",
        "X-Role": "DPM_COMPOSITE_CONSUMER",
        "X-Correlation-ID": "fee-drag-example",
        "X-Request-ID": "fee-drag-example-request",
    }
    examples = fee_drag_openapi_examples()
    with TestClient(app, headers=headers) as client:
        payload = publish_fee_drag_example(client, monkeypatch)
        assert CompositeFeeDragRequest.model_validate(payload).model_dump(mode="json") == examples["request"]
        result = client.post("/performance/composites/analytics", json=examples["request"])
        assert result.status_code == 200 and result.json() == examples["response"], result.text
        missing = client.post("/performance/composites/analytics", json=examples["missing_request"])
        assert missing.status_code == 404 and missing.json() == examples["missing_response"], missing.text
        for change in (
            {"materialization_ids": payload["materialization_ids"] * 2},
            {"materialization_ids": list(reversed(payload["materialization_ids"]))},
            {"return_view": "NET_ACTUAL"},
            {"return_view": "GROSS"},
            {"method": "ARBITRARY_FORMULA"},
            {"reporting_currency": "EUR"},
            {"composite_return_override": "0.05"},
            {"materialization_ids": None},
        ):
            refused = client.post("/performance/composites/analytics", json={**payload, **change})
            assert refused.status_code == 422, refused.text
            assert "periods" not in refused.json() and "cumulative_fee_drag" not in refused.json()
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/performance/composites/analytics"]["post"]
        assert "model_fee_drag" in operation["requestBody"]["content"]["application/json"]["examples"]
        assert "202" in operation["responses"]
    with TestClient(app, headers=headers) as reopened:
        result = reopened.post("/performance/composites/analytics", json=examples["request"])
        assert result.status_code == 200 and result.json() == examples["response"], result.text


@pytest.mark.parametrize("scheduled,zero", [(False, False), (True, False), (True, True)])
def test_fee_drag_unequal_member_period_oracle_original_pins_and_context(
    monkeypatch, model_fee_database, scheduled, zero
):
    wire, revised = profile(scheduled=scheduled, zero=zero)
    packets, approvals = [], []
    headers = {"X-Tenant-Id": wire["tenant_id"], "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        commands, receipts = [], []
        for index, day in enumerate(("2026-01-05", "2026-01-06")):
            command, receipt = _publish(client, monkeypatch, wire, day, index + 1, packets, approvals)
            commands.append(command)
            receipts.append(receipt)
        payload = {**linked_request(commands), "metric_id": "MODEL_FEE_DRAG", "return_view": "NET_MODEL_FEE"}
        payload.pop("method")
        request = CompositeFeeDragRequest.model_validate(payload)

        def no_new_schedule_fetch():
            raise AssertionError("Retained analysis must not construct a current schedule resolver")

        monkeypatch.setattr(composite_model_fees, "composite_model_fee_resolver", no_new_schedule_fetch)
        result = calculate_model_fee_drag(request, tenant_id=wire["tenant_id"])
        response = client.post("/performance/composites/analytics", json=payload)
        assert response.status_code == 200, response.text
        assert response.json() == result.model_dump(mode="json")
        expected = oracle(receipts)
        for actual, reference in zip(
            (result.cumulative_gross_return, result.cumulative_model_net_return, result.cumulative_fee_drag),
            expected[:3],
            strict=True,
        ):
            assert abs(Fraction(actual) - reference) <= Fraction("2e-12")
        for actual, reference in zip(result.periods, expected[3], strict=True):
            assert actual.member_count == 3 and actual.excluded_member_count == 0
            assert abs(Fraction(actual.fee_drag) - reference[2]) <= Fraction("2e-12")
        if zero:
            assert result.cumulative_fee_drag == 0
        else:
            assert result.cumulative_fee_drag != sum(row.fee_drag for row in result.periods)
        original = result.model_dump(mode="json")
        with localcontext() as caller:
            caller.prec, caller.rounding, caller.Emin, caller.Emax = 9, ROUND_DOWN, -9, 9
            caller.traps[Inexact] = caller.traps[Rounded] = True
            before = (dict(caller.flags), dict(caller.traps))
            assert calculate_model_fee_drag(request, tenant_id=wire["tenant_id"]).model_dump(mode="json") == original
            assert before == (dict(caller.flags), dict(caller.traps))
        assert result.units == "DECIMAL_RETURN_DIFFERENCE"
        assert result.gross_baseline == "ORIGINAL_GROSS_RECEIPTS_SAME_MODEL_POPULATION"
        assert [
            (row.portfolio_id, row.gross_receipt_digest, row.model_receipt_digest) for row in result.member_sources
        ] == [
            (row["portfolio_id"], row["source_evidence"]["gross_receipt_digest"], row["fact"]["source_snapshot_id"])
            for receipt in receipts
            for row in receipt["members"]
            if row["state"] == "READY"
        ]
        for index, command in enumerate(commands):
            assert (
                client.get(f"/performance/composites/materializations/{command.materialization_id}").json()
                == receipts[index]
            )
        with pytest.raises(APIError) as error:
            calculate_model_fee_drag(request, tenant_id="foreign-tenant")
        assert error.value.status_code == 404
        foreign = client.post(
            "/performance/composites/analytics", json=payload, headers={**headers, "X-Tenant-Id": "foreign-tenant"}
        )
        assert foreign.status_code == 404, foreign.text
    with TestClient(app, headers=headers) as reopened:
        replay = reopened.post("/performance/composites/analytics", json=payload)
        assert replay.status_code == 200 and replay.json() == original, replay.text


def test_fee_drag_refuses_changed_full_profile_binding(monkeypatch, model_fee_database):
    wire, revised = profile(scheduled=True, changed_binding=True)
    packets, approvals = [], []
    headers = {"X-Tenant-Id": wire["tenant_id"], "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        first, _ = _publish(client, monkeypatch, wire, "2026-01-05", 1, packets, approvals)
        second, _ = _publish(client, monkeypatch, revised, "2026-01-06", 2, packets, approvals)
        payload = {**linked_request([first, second]), "metric_id": "MODEL_FEE_DRAG", "return_view": "NET_MODEL_FEE"}
        payload.pop("method")
        with pytest.raises(APIError) as error:
            calculate_model_fee_drag(CompositeFeeDragRequest.model_validate(payload), tenant_id=wire["tenant_id"])
        assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_MISMATCH"
        response = client.post("/performance/composites/analytics", json=payload)
        assert response.status_code == 422, response.text
        assert "COMPOSITE_VECTOR_METHOD_MISMATCH" in response.text
