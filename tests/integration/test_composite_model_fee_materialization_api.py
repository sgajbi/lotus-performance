"""Registered API/worker controls with frozen synthetic authority ports."""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import (
    CompositeMaterializationStore,
    composite_materialization_store,
)
from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
from app.core.config import get_settings
from app.ports import composite_external_evidence, composite_model_fees
from app.services.composite_materialization.source_contract import PinnedCompositeSource, admit_pinned_source
from app.services.compute_job_store import compute_job_store
from app.services.reproducibility_service import generate_value_fingerprint
from app.workers.compute_executor_worker import process_pending_jobs
from app.workers.lineage_worker import process_pending_jobs as process_lineage
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_authority_helpers import command_for_packet, install_test_authorities, rehash_definition
from tests.composite_model_fee_helpers import SyntheticModelFeeApproval, model_fee_source_inputs
from tests.integration.test_composite_materialization_api import create_stateful_member, install_source_wire_controls

PATH = "/performance/composites/materializations"


@pytest.fixture(autouse=True)
def model_fee_database(monkeypatch, tmp_path):
    url = "sqlite:///" + (tmp_path / "model-fee.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    return url


@pytest.mark.parametrize("missing", ["X-Tenant-Id", "X-Actor-Id", "X-Role", "X-Capabilities", "X-Service-Identity"])
def test_profile_catalog_requires_authority_and_preserves_original_receipt(monkeypatch, missing):
    packet, wire, _, _ = model_fee_source_inputs()
    install_source_wire_controls(monkeypatch, tuple(packet[key] for key in ("definition", "membership", "attestation")))
    headers = {
        "X-Tenant-Id": wire["tenant_id"],
        "X-Actor-Id": "original-publisher",
        "X-Role": "DPM_COMPOSITE_CONSUMER",
        "X-Service-Identity": "lotus-performance",
        "X-Correlation-Id": "synthetic-catalog-control",
        "X-Capabilities": "operations.runtime.manage,operations.runtime.read",
    }
    path = "/performance/composites/model-fee-profiles"
    exact = f"{path}/{wire['profile_id']}/{wire['revision']}"
    with TestClient(app) as client:
        refused_headers = {key: value for key, value in headers.items() if key != missing}
        expected = 401 if missing == "X-Tenant-Id" else 422 if missing in ("X-Actor-Id", "X-Role") else 403
        assert client.post(path, json=wire, headers=refused_headers).status_code == expected
        assert client.get(exact, headers=refused_headers).status_code == expected
        published = client.post(path, json=wire, headers=headers)
        assert published.status_code == 200, published.text
        missing_profile = client.get(f"{path}/{wire['profile_id']}/unknown-revision", headers=headers)
        assert missing_profile.status_code == 404, missing_profile.text
        assert "profile" not in missing_profile.json()
        assert client.get(exact, headers=headers).json() == published.json()
        retry_headers = {**headers, "X-Actor-Id": "different-retry-publisher"}
        assert client.post(path, json=wire, headers=retry_headers).json() == published.json()


def prepare_registered_model_fee(client, monkeypatch, packet, wire, command, *, basis="GROSS"):
    tenant = packet["definition"]["tenant_id"]
    references = [
        create_stateful_member(client, member, basis=basis, precision="DECIMAL_STRICT") for member in ("A", "B", "C")
    ]
    process_lineage(limit=100)
    command = command.model_copy(
        update={"member_calculations": command_for_packet(packet, member_calculations=references).member_calculations}
    )
    selections = []
    for reference in command.member_calculations:
        # Actual-net refusal is checked by the producer; obtain the gross pin
        # only for the positive internal method admission.
        outcome = RetainedCompositeMemberResultSource().read_member(
            command,
            reference,
            tenant_id=tenant,
            membership_snapshot_id=command.membership_content_hash,
            request_headers={"X-Tenant-Id": tenant, "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"},
        )
        if basis == "GROSS":
            assert outcome.state == "READY", outcome
        for template in packet["definition"]["source_authority"]["payload"]["selections"]:
            item = deepcopy(template)
            owner = "lotus-performance" if template["fact"] == "MEMBER_RETURN" else "lotus-core"
            item.update(
                selection_id=f"{template['selection_id']}.{reference.portfolio_id}",
                member_ids=[reference.portfolio_id],
                provider_id=owner,
                economic_authority=owner,
                source_product="CompositeMemberSourceEvidence",
                source_contract_version="composite-member-source.v1",
                source_revision=str(reference.calculation_id),
                source_watermark=reference.input_fingerprint,
                source_digest=generate_value_fingerprint(outcome.source_evidence, "composite-member-source.v1")[0]
                if basis == "GROSS"
                else "sha256:" + "f" * 64,
            )
            selections.append(item)
    packet["definition"]["source_authority"]["payload"]["selections"] = sorted(
        selections, key=lambda item: item["selection_id"]
    )
    rehash_definition(packet["definition"])
    install_test_authorities(monkeypatch, packet)
    source = PinnedCompositeSource.model_validate(
        {
            **{key: packet[key] for key in ("definition", "membership", "attestation")},
            "wire_evidence": {key: packet[key] for key in ("definition", "membership", "attestation")},
        }
    )
    approval = SyntheticModelFeeApproval(wire, source)
    monkeypatch.setattr(composite_external_evidence, "method_approval_verifier", lambda: approval)

    # Use the real authenticated catalog publication and configured source
    # adapter. Only independent authority and upstream facts stay synthetic.
    published = client.post(
        "/performance/composites/model-fee-profiles",
        json=wire,
        headers={
            "X-Service-Identity": "lotus-performance",
            "X-Correlation-Id": "synthetic-profile-publication",
            "X-Capabilities": "operations.runtime.manage",
        },
    )
    assert published.status_code == 200, published.text
    assert published.json()["posture"] == "UNAPPROVED_METHOD_INPUT"
    assert published.json()["binding"] == command.model_fee_binding.model_dump(mode="json")
    monkeypatch.setattr(get_settings(), "COMPOSITE_MODEL_FEE_SOURCE_MODE", "LOCAL_CATALOG")
    return command_for_packet(
        packet,
        period_start="2026-01-05",
        period_end="2026-01-05",
        return_view="NET_MODEL_FEE",
        model_fee_binding=command.model_fee_binding,
        member_calculations=references,
    )


@pytest.mark.parametrize("basis", ["GROSS", "NET"])
def test_registered_model_fee_worker_retention_replay_and_actual_net_refusal(
    monkeypatch, model_fee_database, basis, capture=None
):
    packet, wire, command, _ = model_fee_source_inputs()
    install_source_wire_controls(monkeypatch, tuple(packet[key] for key in ("definition", "membership", "attestation")))
    tenant = packet["definition"]["tenant_id"]
    headers = {"X-Tenant-Id": tenant, "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        command = prepare_registered_model_fee(client, monkeypatch, packet, wire, command, basis=basis)
        admit_pinned_source(
            command=command,
            tenant_id=tenant,
            **{key: packet[key] for key in ("definition", "membership", "attestation")},
        )
        payload = command.model_dump(mode="json")
        accepted = client.post(PATH, json=payload)
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        response = client.get(accepted.json()["result_path"])
        assert response.status_code == 200, response.text
        retained = response.json()
        if basis == "NET":
            assert retained["state"] == "BLOCKED", retained
            assert retained["expected_count"] == 3
            assert all(member["fact"] is None for member in retained["members"])
            assert all(member["reason_code"] == "MEMBER_RETURN_VIEW_NOT_SUPPORTED" for member in retained["members"])
            return
        assert retained["state"] == "COMPLETE", (retained, compute_job_store.get_job(command.calculation_id))
        expected = {"A": Fraction("0.0989"), "B": Fraction("0.0479"), "C": Fraction("-0.02")}
        observed = {}
        for member in retained["members"]:
            fact, evidence = member["fact"], member["source_evidence"]
            actual = Fraction(fact["return_value"])
            gross = Fraction(evidence["gross_return"])
            fee = Fraction(evidence["fee_entry"]["period_fee_fraction"])
            assert actual == (1 + gross) * (1 - fee) - 1
            # Preserve the source engine's reported-return precision; the
            # subsequent model-fee transformation is exact on that input.
            assert abs(actual - expected[member["portfolio_id"]]) < Fraction("0.000000000001")
            observed[member["portfolio_id"]] = actual
            assert fact["return_view"] == "NET_MODEL_FEE"
            assert evidence["contract_version"] == "composite-member-source.v4"
            assert evidence["gross_evidence"]["calculation_request"]["portfolio"]["metric_basis"] == "GROSS"
        result = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": command.composite_id,
                "period_start": "2026-01-05",
                "period_end": "2026-01-05",
                "return_view": "NET_MODEL_FEE",
                "reporting_currency": "USD",
                "restatement_sequence": 1,
            },
        )
        assert result.status_code == 200, result.text
        weighted = (100 * observed["A"] + 200 * observed["B"] + 300 * observed["C"]) / 600
        reported = Decimal(str(result.json()["periods"][0]["return_value"]))
        assert abs(Fraction(reported) - weighted) <= Fraction("0.000000000001")
        reloaded = CompositeMaterializationStore(model_fee_database)
        try:
            original = reloaded.get(command.materialization_id, tenant_id=tenant)
            assert original == composite_materialization_store.get(command.materialization_id, tenant_id=tenant)
            assert original.source.model_fee_wire == wire
        finally:
            reloaded.close()

        class NoLatestResolution:
            def resolve(self, request):
                pytest.fail("Reload and replay must use the original pinned method, not resolve latest")

        monkeypatch.setattr(composite_model_fees, "composite_model_fee_resolver", NoLatestResolution)
        replay = client.post(PATH, json=payload)
        assert replay.status_code == 202, replay.text
        assert client.get(accepted.json()["result_path"]).json() == retained
        assert (
            client.get(
                accepted.json()["result_path"], headers={**headers, "X-Tenant-Id": "different-tenant"}
            ).status_code
            == 404
        )
        if capture is not None:
            capture(packet, wire, command, retained, result.json()["periods"])


@pytest.mark.parametrize("fault", ["rate", "schedule", "calendar", "unconfigured"])
def test_registered_model_fee_changed_source_under_old_binding_refuses(monkeypatch, fault):
    packet, wire, command, _ = model_fee_source_inputs()
    install_source_wire_controls(monkeypatch, tuple(packet[key] for key in ("definition", "membership", "attestation")))
    headers = {
        "X-Tenant-Id": packet["definition"]["tenant_id"],
        "X-Actor-Id": "operator",
        "X-Role": "DPM_COMPOSITE_CONSUMER",
    }
    with TestClient(app, headers=headers) as client:
        command = prepare_registered_model_fee(client, monkeypatch, packet, wire, command)
        altered = deepcopy(wire)
        if fault == "rate":
            altered["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.003"
        elif fault == "schedule":
            altered["schedule_revision"] = "schedule.changed"
        else:
            altered["calendar_binding"]["revision"] = "calendar.changed"

        class ConflictingMethod:
            def resolve(self, request):
                assert request.binding == command.model_fee_binding
                return deepcopy(altered)

        if fault == "unconfigured":
            monkeypatch.setattr(get_settings(), "COMPOSITE_MODEL_FEE_SOURCE_MODE", "UNAVAILABLE")
        else:
            monkeypatch.setattr(composite_model_fees, "composite_model_fee_resolver", ConflictingMethod)
        accepted = client.post(PATH, json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        retained = client.get(accepted.json()["result_path"])
        assert retained.status_code == 200, retained.text
        receipt = retained.json()
        assert receipt["state"] == "BLOCKED" and receipt["expected_count"] == 3
        assert receipt["ready_count"] == 0 and receipt["blocked_count"] == 3
        expected_reason = (
            "COMPOSITE_MODEL_FEE_SOURCE_UNAVAILABLE"
            if fault == "unconfigured"
            else "COMPOSITE_MODEL_FEE_SOURCE_DIGEST_MISMATCH"
        )
        assert all(member["reason_code"] == expected_reason for member in receipt["members"])
        assert all(member["fact"] is None and member["source_evidence"] is None for member in receipt["members"])
