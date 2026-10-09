"""Registered component catalog/worker/replay/analytics with controlled synthetic financial authority."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from decimal import ROUND_DOWN, ROUND_UP, Inexact, Rounded, localcontext
from fractions import Fraction
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
from app.core.config import get_settings
from app.models.composite_materialization import CompositeMaterializationCommand
from app.ports import composite_external_evidence, composite_model_fees
from app.services.composite_materialization.model_fee_source_admission import model_fee_resolution_request
from app.services.composite_materialization.source_contract import PinnedCompositeSource
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks.test_postgres_composite_model_fee import (
    populated_model_fee_postgres as _populated_model_fee_postgres,
)
from tests.composite_component_source_helpers import (
    FrozenFinancialSupplier,
    FrozenFinancialVerifier,
    component_source_inputs,
    financial_source,
    write_component_capture,
)
from tests.composite_model_fee_helpers import model_fee_source_inputs
from tests.integration import test_composite_model_fee_materialization_api as periodic
from tests.integration.test_composite_materialization_api import install_source_wire_controls

populated_model_fee_postgres = _populated_model_fee_postgres


@pytest.fixture(autouse=True)
def component_database(monkeypatch, tmp_path, request):
    if os.environ.get("LOTUS_POSTGRES_PLAN_DATABASE_URL"):
        # The registered fixture below owns its isolated schema and runtime-store cleanup.
        _, url = request.getfixturevalue("populated_model_fee_postgres")
    else:
        url = "sqlite:///" + (tmp_path / "component.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    return url


def prepare(
    client,
    monkeypatch,
    headers,
    *,
    distinct=False,
    zero=False,
    false_base=False,
    signed_foreign=False,
    false_gross=False,
):
    packet, _, command, _ = model_fee_source_inputs()
    install_source_wire_controls(monkeypatch, tuple(packet[key] for key in ("definition", "membership", "attestation")))
    references = {
        member: periodic.create_stateful_member(client, member, basis="GROSS", precision="DECIMAL_STRICT")
        for member in ("A", "B", "C")
    }
    periodic.process_lineage(limit=100)
    command = CompositeMaterializationCommand.model_validate(
        {**command.model_dump(mode="json"), "member_calculations": list(references.values())}
    )
    outcomes = [
        RetainedCompositeMemberResultSource().read_member(
            command,
            reference,
            tenant_id=headers["X-Tenant-Id"],
            membership_snapshot_id=command.membership_content_hash,
            request_headers=headers,
        )
        for reference in command.member_calculations
    ]
    assert all(row.state == "READY" for row in outcomes), outcomes
    profile, members = component_source_inputs(
        packet,
        outcomes,
        distinct=distinct,
        zero=zero,
        false_base=false_base,
        signed_foreign=signed_foreign,
        false_gross=false_gross,
    )
    packet, profile, command, _ = model_fee_source_inputs(profile)
    install_source_wire_controls(monkeypatch, tuple(packet[key] for key in ("definition", "membership", "attestation")))
    monkeypatch.setattr(periodic, "create_stateful_member", lambda client, member, **kwargs: references[member])
    command = periodic.prepare_registered_model_fee(client, monkeypatch, packet, profile, command)
    source = PinnedCompositeSource.model_validate(
        {
            **{key: packet[key] for key in ("definition", "membership", "attestation")},
            "wire_evidence": {key: packet[key] for key in ("definition", "membership", "attestation")},
        }
    )
    request = model_fee_resolution_request(source, command, tenant_id=headers["X-Tenant-Id"])
    financial = financial_source(packet, command, members)
    supplier = FrozenFinancialSupplier(financial, request)
    verifier = FrozenFinancialVerifier(financial, request, source.definition.definition_version)
    return profile, command, financial, supplier, verifier, packet


def headers():
    packet, _, _, _ = model_fee_source_inputs()
    return {
        "X-Tenant-Id": packet["definition"]["tenant_id"],
        "X-Actor-Id": "operator",
        "X-Role": "DPM_COMPOSITE_CONSUMER",
    }


@pytest.mark.parametrize("distinct,zero", [(False, False), (True, False), (False, True)])
def test_registered_component_worker_retains_full_financial_source_and_replays(
    monkeypatch, component_database, distinct, zero, tmp_path
):
    authority = headers()
    with TestClient(app, headers=authority) as client:
        profile, command, financial, supplier, verifier, packet = prepare(
            client, monkeypatch, authority, distinct=distinct, zero=zero
        )
        monkeypatch.setattr(composite_model_fees, "composite_gross_cost_resolver", lambda: supplier)
        monkeypatch.setattr(composite_external_evidence, "composite_receipt_verifier", lambda: verifier)
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        response = client.get(accepted.json()["result_path"])
        assert response.status_code == 200, response.text
        retained = response.json()
        assert retained["state"] == "COMPLETE", retained
        assert supplier.calls == 1
        deduction = Fraction(0) if zero else Fraction(".010") if distinct else Fraction(".008")
        for row in retained["members"]:
            fact, evidence = row["fact"], row["source_evidence"]
            assert evidence["contract_version"] == "composite-member-source.v6"
            assert Fraction(evidence["deducted_fee_fraction"]) == deduction
            assert Fraction(fact["return_value"]) == (1 + Fraction(evidence["gross_return"])) * (1 - deduction) - 1
            assert evidence["gross_component_member"] == next(
                member
                for member in financial["members"]
                if member["evidence"]["scope"]["member_id"] == row["portfolio_id"]
            )
        selection = dict(
            calculation_id=str(uuid4()),
            composite_id=command.composite_id,
            period_start=str(command.period_start),
            period_end=str(command.period_end),
            return_view="NET_MODEL_FEE",
            reporting_currency="USD",
            materialization_ids=[str(command.materialization_id)],
        )
        twr = client.post("/performance/composites/twr", json=selection)
        assert twr.status_code == 200, twr.text
        analysis_request = {**selection, "metric_id": "MODEL_FEE_DRAG", "method": "ADDITIVE_GROSS_MINUS_MODEL:v1"}
        drag = client.post(
            "/performance/composites/analytics",
            json=analysis_request,
        )
        assert drag.status_code == 200, drag.text
        assert len(drag.json()["member_sources"]) == 3
        for precision, rounding in ((9, ROUND_DOWN), (150, ROUND_UP)):
            with localcontext() as caller:
                caller.prec, caller.rounding = precision, rounding
                caller.Emin, caller.Emax = -9, 9
                caller.traps[Inexact] = caller.traps[Rounded] = True
                caller.clear_flags()
                before = caller.copy()
                repeated = client.post("/performance/composites/analytics", json=analysis_request)
                assert repeated.status_code == 200, repeated.text
                assert repeated.json() == drag.json()
                assert (caller.prec, caller.rounding, caller.Emin, caller.Emax, caller.traps, caller.flags) == (
                    before.prec,
                    before.rounding,
                    before.Emin,
                    before.Emax,
                    before.traps,
                    before.flags,
                )

        class NeverReadCurrent:
            def resolve(self, request):
                raise AssertionError("Retained replay must not fetch a current financial supplier")

        monkeypatch.setattr(composite_model_fees, "composite_gross_cost_resolver", NeverReadCurrent)
        reopened = CompositeMaterializationStore(component_database)
        try:
            original = reopened.get(command.materialization_id, tenant_id=authority["X-Tenant-Id"])
            assert original.source.model_fee_wire == profile
            assert original.source.gross_component_wire["source"] == financial
            assert original.source.gross_component_wire["verification"] == verifier.receipt.model_dump(mode="json")
        finally:
            reopened.close()
        assert client.get(accepted.json()["result_path"]).json() == retained
        assert client.post("/performance/composites/twr", json=selection).json() == twr.json()
        published = client.get(
            f"/performance/composites/model-fee-profiles/{profile['profile_id']}/{profile['revision']}",
            headers={
                "X-Service-Identity": "lotus-performance",
                "X-Correlation-Id": "synthetic-profile-read",
                "X-Capabilities": "operations.runtime.read",
            },
        )
        assert published.status_code == 200, published.text
        assert published.json()["profile"] == profile
        assert published.json()["posture"] == "UNAPPROVED_METHOD_INPUT"
        capture_path = os.environ.get("LOTUS_COMPONENT_WIRE_CAPTURE")
        if capture_path and not distinct and not zero:
            write_component_capture(
                capture_path,
                dict(
                    qualification="SYNTHETIC_REGISTERED_CONSUMER_ONLY",
                    profile_request=profile,
                    profile_response=published.json(),
                    materialization_request=command.model_dump(mode="json"),
                    materialization_accepted=accepted.json(),
                    retained_response=retained,
                    financial_source=financial,
                    financial_verification=verifier.receipt.model_dump(mode="json"),
                    twr_request=selection,
                    twr_response=twr.json(),
                    analytics_request=analysis_request,
                    analytics_response=drag.json(),
                ),
            )
        probe_input = tmp_path / "retained-component-probe.json"
        probe_input.write_text(
            json.dumps(
                dict(
                    packet=packet,
                    profile=profile,
                    command=command.model_dump(mode="json"),
                    financial=financial,
                    database_url=component_database,
                    analysis_request=analysis_request,
                    analysis_response=drag.json(),
                )
            ),
            encoding="utf-8",
        )
        probe = subprocess.run(
            [sys.executable, "-m", "tests.composite_component_replay_probe", str(probe_input)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert probe.returncode == 0, probe.stdout + probe.stderr
        assert json.loads(probe.stdout)["current_source_reads"] == 0


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "method-verifier-only",
        "foreign",
        "tampered",
        "changed-cut",
        "changed-receipt",
        "false-base",
        "incomplete-zero",
        "signed-false-base",
        "signed-foreign",
        "signed-false-gross",
    ],
)
def test_component_financial_refusal_has_zero_ready_facts(monkeypatch, component_database, fault):
    authority = headers()
    with TestClient(app, headers=authority) as client:
        _, command, financial, supplier, verifier, _ = prepare(
            client,
            monkeypatch,
            authority,
            false_base=fault == "signed-false-base",
            signed_foreign=fault == "signed-foreign",
            false_gross=fault == "signed-false-gross",
        )
        if fault != "missing":
            changed = deepcopy(financial)
            if fault == "foreign":
                changed["members"][0]["evidence"]["scope"]["tenant_id"] = "foreign"
            elif fault == "tampered":
                changed["members"][0]["evidence"]["included_components"][0]["source_evidence"]["digest"] = (
                    "sha256:" + "9" * 64
                )
            elif fault == "changed-cut":
                changed["source_cut_id"] = "other.cut"
            elif fault == "changed-receipt":
                changed["members"][0]["evidence"]["scope"]["gross_receipt_digest"] = "sha256:" + "8" * 64
            elif fault == "false-base":
                changed["members"][0]["reference_wealth_amount"] = "999"
            elif fault == "incomplete-zero":
                changed["members"][0]["evidence"]["included_components"] = []
            supplier.wire = changed
            monkeypatch.setattr(composite_model_fees, "composite_gross_cost_resolver", lambda: supplier)
        if fault != "method-verifier-only":
            monkeypatch.setattr(composite_external_evidence, "composite_receipt_verifier", lambda: verifier)
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        response = client.get(accepted.json()["result_path"])
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "BLOCKED", response.text
        assert response.json()["ready_count"] == 0
        assert all(row["fact"] is None for row in response.json()["members"])
        analysis = client.post(
            "/performance/composites/analytics",
            json={
                "composite_id": command.composite_id,
                "period_start": str(command.period_start),
                "period_end": str(command.period_end),
                "return_view": "NET_MODEL_FEE",
                "reporting_currency": "USD",
                "materialization_ids": [str(command.materialization_id)],
                "metric_id": "MODEL_FEE_DRAG",
            },
        )
        assert analysis.status_code in (409, 422), analysis.text
        assert "cumulative_fee_drag" not in analysis.json()
