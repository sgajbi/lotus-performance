from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.adapters import composite_provider_member_source as provider_adapter
from app.core.config import get_settings
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_authority_helpers import command_for_packet, install_test_authorities, observation_packet


@pytest.fixture(autouse=True)
def isolated_provider_metadata(monkeypatch, tmp_path):
    url = "sqlite:///" + (tmp_path / "metadata.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "https://manage.test")


def install_provider_wires(monkeypatch, packets, observations):
    by_version = {packet["definition"]["definition_version"]: packet for packet in packets}

    async def read(**kwargs):
        from urllib.parse import unquote, urlsplit

        url = kwargs["url"]
        assert kwargs["headers"]["X-Tenant-Id"] == "synthetic-tenant-a"
        segments = [unquote(segment) for segment in urlsplit(url).path.split("/")]
        packet = next(packet for version, packet in by_version.items() if version in segments)
        product = (
            "attestation" if "universe-attestations" in url else "membership" if "/membership/" in url else "definition"
        )
        return 200, packet[product]

    class Observations:
        def read(self, *, tenant_id, selection):
            assert tenant_id == "synthetic-tenant-a"
            return next(wire for wire in observations if wire["revision"] == selection.source_revision)

    def no_internal_read(*args, **kwargs):
        raise AssertionError("External-only admission must not require Core or internal calculation identity")

    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", read)
    monkeypatch.setattr(provider_adapter, "provider_observation_source", Observations)
    monkeypatch.setattr(provider_adapter.RetainedCompositeMemberResultSource, "read_member", no_internal_read)


def request_for(command, sequence=None):
    return {
        "composite_id": command.composite_id,
        "period_start": str(command.period_start),
        "period_end": str(command.period_end),
        "return_view": str(command.return_view),
        "reporting_currency": command.reporting_currency,
        "restatement_sequence": sequence,
    }


HEADERS = {"X-Tenant-Id": "synthetic-tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}


@pytest.mark.parametrize("independent_ending", [False, True])
def test_registered_external_default_worker_original_correction_and_replay(monkeypatch, independent_ending):
    from tests.composite_authority_helpers import independent_ending_packet

    original, original_wire = observation_packet()
    wires = [original_wire]
    if independent_ending:
        original, original_wire, ending_wire = independent_ending_packet()
        wires = [original_wire, ending_wire]
    corrected, corrected_wire = observation_packet(corrected=True)
    install_test_authorities(monkeypatch, [original, corrected])
    install_provider_wires(monkeypatch, [original, corrected], [*wires, corrected_wire])
    with TestClient(app, headers=HEADERS) as client:
        commands = [command_for_packet(original), command_for_packet(corrected, restatement_sequence=2)]
        for command, expected_return, end_assets in zip(
            commands,
            [Decimal(1) / Decimal(60), Decimal(49) / Decimal(3050)],
            [Decimal(640), Decimal("649.8")],
            strict=True,
        ):
            accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
            assert accepted.status_code == 202, accepted.text
            assert process_pending_jobs(limit=10) == 1
            receipt_response = client.get(accepted.json()["result_path"])
            assert receipt_response.status_code == 200, receipt_response.text
            receipt = receipt_response.json()
            assert receipt["state"] == "COMPLETE", receipt
            assert receipt["ready_count"] == 3
            for member in receipt["members"]:
                assert member["fact"]["calculation_id"] is None
                assert member["fact"]["source_authority_identity"]["source_kind"] == "EXTERNAL_PROVIDER"
                assert member["source_evidence"]["qualification"] == "SYNTHETIC_TEST_ONLY"
            result = client.post("/performance/composites/twr", json=request_for(command, command.restatement_sequence))
            assert result.status_code == 200, result.text
            period = result.json()["periods"][0]
            assert abs(Decimal(str(period["return_value"])) - expected_return) < Decimal("1e-12")
            assert Decimal(str(period["ending_market_value"])) == end_assets
            assert (
                client.post(
                    "/performance/composites/materializations", json=command.model_dump(mode="json")
                ).status_code
                == 202
            )
        retained = client.post("/performance/composites/twr", json=request_for(commands[0], 1))
        assert retained.status_code == 200, retained.text
        assert Decimal(str(retained.json()["periods"][0]["ending_market_value"])) == Decimal(640)


@pytest.mark.parametrize("unselected_ending_present", [False, True])
def test_missing_ending_assets_are_retained_but_dependent_calculation_refuses(monkeypatch, unselected_ending_present):
    packet, wire = observation_packet(ending_assets=False)
    if unselected_ending_present:
        from app.models.composite_authority import authority_digest
        from tests.composite_authority_helpers import rehash_definition

        _, complete_wire = observation_packet()
        wire["rows"] = complete_wire["rows"]
        for selection in packet["definition"]["source_authority"]["payload"]["selections"]:
            selection["source_digest"] = authority_digest(wire)
        rehash_definition(packet["definition"])
    install_test_authorities(monkeypatch, packet)
    install_provider_wires(monkeypatch, [packet], [wire])
    command = command_for_packet(packet)
    with TestClient(app, headers=HEADERS) as client:
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        receipt = client.get(accepted.json()["result_path"]).json()
        assert receipt["state"] == "COMPLETE", receipt
        assert all(member["fact"]["ending_market_value"] is None for member in receipt["members"])
        result = client.post("/performance/composites/twr", json=request_for(command))
        assert result.status_code == 422, result.text
        assert "COMPOSITE_ENDING_ASSETS_UNAVAILABLE" in result.text
        pinned = client.post(
            "/performance/composites/twr",
            json={**request_for(command), "materialization_ids": [str(command.materialization_id)]},
        )
        assert pinned.status_code == 422, pinned.text
        assert pinned.json()["error_code"] == "COMPOSITE_ENDING_ASSETS_UNAVAILABLE"
        assert "cumulative_return" not in pinned.json()


def test_production_default_refuses_unsigned_provider_trust(monkeypatch):
    packet, wire = observation_packet()
    install_provider_wires(monkeypatch, [packet], [wire])
    command = command_for_packet(packet)
    with TestClient(app, headers=HEADERS) as client:
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202
        assert process_pending_jobs(limit=10) == 1
        receipt = client.get(accepted.json()["result_path"]).json()
        assert receipt["state"] == "BLOCKED", receipt
        assert receipt["reason_code"] == "COMPOSITE_SOURCE_REFUSED"
        assert receipt["members"] == []


def test_two_member_independent_reference_is_one_percent_with_actual_ending_wealth(monkeypatch):
    packet, wire = observation_packet(two_members=True)
    install_test_authorities(monkeypatch, packet)
    install_provider_wires(monkeypatch, [packet], [wire])
    command = command_for_packet(packet)
    with TestClient(app, headers=HEADERS) as client:
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        receipt = client.get(accepted.json()["result_path"]).json()
        assert receipt["state"] == "COMPLETE", receipt
        assert receipt["ready_count"] == 2
        result = client.post("/performance/composites/twr", json=request_for(command))
        assert result.status_code == 200, result.text
        period = result.json()["periods"][0]
        assert Decimal(str(period["return_value"])) == Decimal("0.01")
        assert Decimal(str(period["ending_market_value"])) == Decimal(469)


def test_registered_external_month_matches_independent_or01(monkeypatch):
    from tests.composite_authority_helpers import numerical_oracles, oracle_month_packet

    packet, wire = oracle_month_packet(1)
    install_test_authorities(monkeypatch, packet)
    install_provider_wires(monkeypatch, [packet], [wire])
    command = command_for_packet(packet, period_start=wire["period_start"], period_end=wire["period_end"])
    with TestClient(app, headers=HEADERS) as client:
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=1) == 1
        result = client.post("/performance/composites/twr", json=request_for(command))
        assert result.status_code == 200, result.text
        spec = numerical_oracles()["fixtures"][0]
        period = result.json()["periods"][0]
        assert Decimal(str(period["return_value"])) == Decimal(spec["expected"]["return"])
        assert [Decimal(str(row["beginning_asset_weight"])) for row in period["member_contributions"]] == [
            Decimal(value) for value in spec["expected"]["weights"]
        ]
        assert [Decimal(str(row["contribution"])) for row in period["member_contributions"]] == [
            Decimal(value) for value in spec["expected"]["contributions"]
        ]


def test_registered_external_missing_eligible_member_month_cannot_publish_survivor_chain(monkeypatch):
    from sqlalchemy import text

    from app.services.composite_metadata_store import composite_metadata_store
    from tests.composite_authority_helpers import oracle_month_packet

    pairs = [oracle_month_packet(month, missing_member=month == 2) for month in (1, 2, 3)]
    packets, wires = map(list, zip(*pairs, strict=True))
    install_test_authorities(monkeypatch, packets)
    install_provider_wires(monkeypatch, packets, wires)
    with TestClient(app, headers=HEADERS) as client:
        identities = []
        for month, packet in enumerate(packets, 1):
            wire = wires[month - 1]
            command = command_for_packet(
                packet, period_start=wire["period_start"], period_end=wire["period_end"], restatement_sequence=month
            )
            accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
            assert accepted.status_code == 202, accepted.text
            identities.append(str(command.materialization_id))
            assert process_pending_jobs(limit=1) == 1
            receipt = client.get(accepted.json()["result_path"]).json()
            assert receipt["expected_count"] == 2
            if month == 2:
                assert receipt["state"] == "BLOCKED" and receipt["ready_count"] == receipt["blocked_count"] == 1
                assert receipt["members"][1]["fact"] is None
            else:
                assert receipt["state"] == "COMPLETE"
        with composite_metadata_store._engine.connect() as connection:
            for table in ("composite_member_return_facts", "composite_member_return_fact_publications"):
                assert (
                    connection.execute(text(f"SELECT count(*) FROM {table} WHERE restatement_sequence=2")).scalar_one()
                    == 0
                )
        result = client.post(
            "/performance/composites/twr",
            json={
                **request_for(command),
                "period_start": wires[0]["period_start"],
                "restatement_sequence": None,
                "materialization_ids": identities,
            },
        )
        assert result.status_code == 409 and result.json()["error_code"] == "REQUIRED_PERIOD_UNAVAILABLE"
        assert "cumulative_return" not in result.json()


def test_registered_external_two_month_chain_matches_independent_or02(monkeypatch):
    from tests.composite_authority_helpers import numerical_oracles, oracle_month_packet

    pairs = [oracle_month_packet(month) for month in (1, 2)]
    corrected_packet, corrected_wire = oracle_month_packet(1, corrected=True)
    packets, wires = map(list, zip(*pairs, strict=True))
    install_test_authorities(monkeypatch, [*packets, corrected_packet])
    install_provider_wires(monkeypatch, [*packets, corrected_packet], [*wires, corrected_wire])
    with TestClient(app, headers=HEADERS) as client:
        identities = []
        for month, packet in enumerate(packets, 1):
            wire = wires[month - 1]
            command = command_for_packet(
                packet, period_start=wire["period_start"], period_end=wire["period_end"], restatement_sequence=month
            )
            accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
            assert accepted.status_code == 202, accepted.text
            identities.append(str(command.materialization_id))
            assert process_pending_jobs(limit=1) == 1
            retained = client.get(accepted.json()["result_path"])
            assert retained.status_code == 200 and retained.json()["state"] == "COMPLETE", retained.text
            assert all(member["fact"]["calculation_id"] is None for member in retained.json()["members"])
        payload = {
            **request_for(command),
            "period_start": wires[0]["period_start"],
            "restatement_sequence": None,
            "materialization_ids": identities,
            "calculation_id": str(command.calculation_id),
        }
        result = client.post("/performance/composites/twr", json=payload)
        assert result.status_code == 200, result.text
        spec = numerical_oracles()
        expected = Decimal(spec["fixtures"][1]["expected"]["cumulative_return"])
        assert abs(Decimal(str(result.json()["cumulative_return"])) - expected) <= Decimal(
            spec["numeric_comparison_absolute_tolerance"]
        )
        windows = result.json()["selection_manifest"]["windows"]
        assert [window["materialization_id"] for window in windows] == identities
        assert [window["restatement_sequence"] for window in windows] == [1, 2]
        correction = command_for_packet(
            corrected_packet, period_start="2026-01-01", period_end="2026-01-31", restatement_sequence=3
        )
        admitted = client.post("/performance/composites/materializations", json=correction.model_dump(mode="json"))
        assert admitted.status_code == 202
        assert client.post("/performance/composites/twr", json=payload).json() == result.json()
        latest = {key: value for key, value in payload.items() if key != "materialization_ids"}
        assert client.post("/performance/composites/twr", json=latest).status_code == 409
        assert process_pending_jobs(limit=1) == 1
        corrected_receipt = client.get(admitted.json()["result_path"])
        assert corrected_receipt.status_code == 200, corrected_receipt.text
        assert corrected_receipt.json()["state"] == "COMPLETE", corrected_receipt.text
        assert all(member["fact"] is not None for member in corrected_receipt.json()["members"]), corrected_receipt.text
        assert client.post("/performance/composites/twr", json=payload).json() == result.json()
        revised = client.post(
            "/performance/composites/twr",
            json={**request_for(correction), "materialization_ids": [str(correction.materialization_id)]},
        )
        assert revised.status_code == 200 and Decimal(str(revised.json()["cumulative_return"])) == Decimal("0.035")
        overlapping = client.post(
            "/performance/composites/twr",
            json={**payload, "materialization_ids": [identities[0], str(correction.materialization_id), identities[1]]},
        )
        assert overlapping.status_code == 422, overlapping.text
        assert overlapping.json()["error_code"] == "COMPOSITE_VECTOR_WINDOW_MISMATCH"
        assert "cumulative_return" not in overlapping.json()


@pytest.mark.parametrize(
    "fault", ["gap", "order", "currency", "fee", "foreign", "duplicate", "empty", "oversized", "sequence", "method"]
)
def test_pinned_external_vector_refuses_invalid_selection(monkeypatch, fault):
    from uuid import uuid4

    from tests.composite_authority_helpers import oracle_month_packet

    pairs = [
        oracle_month_packet(
            month,
            calendar="SYNTHETIC_OTHER_CALENDAR" if fault == "method" and month == 2 else "SYNTHETIC_CALENDAR_MONTH",
        )
        for month in (1, 2, 3)
    ]
    packets, wires = map(list, zip(*pairs, strict=True))
    install_test_authorities(monkeypatch, packets)
    install_provider_wires(monkeypatch, packets, wires)
    identities = []
    with TestClient(app, headers=HEADERS) as client:
        for month, (packet, wire) in enumerate(pairs, 1):
            command = command_for_packet(
                packet, period_start=wire["period_start"], period_end=wire["period_end"], restatement_sequence=month
            )
            assert (
                client.post(
                    "/performance/composites/materializations", json=command.model_dump(mode="json")
                ).status_code
                == 202
            )
            assert process_pending_jobs(limit=1) == 1
            identities.append(str(command.materialization_id))
        payload = {**request_for(command), "period_start": "2026-01-01", "materialization_ids": identities}
        headers = HEADERS
        if fault == "gap":
            payload["materialization_ids"] = [identities[0], identities[2]]
        elif fault == "order":
            payload["materialization_ids"] = list(reversed(identities))
        elif fault == "currency":
            payload["reporting_currency"] = "EUR"
        elif fault == "fee":
            payload["return_view"] = "NET_ACTUAL"
        elif fault == "foreign":
            headers = {**HEADERS, "X-Tenant-Id": "synthetic-tenant-b"}
        elif fault == "duplicate":
            payload["materialization_ids"] = [identities[0], identities[0]]
        elif fault == "empty":
            payload["materialization_ids"] = []
        elif fault == "oversized":
            payload["materialization_ids"] = [str(uuid4()) for _ in range(121)]
        elif fault == "sequence":
            payload["restatement_sequence"] = 1
        response = client.post("/performance/composites/twr", json=payload, headers=headers)
        expected = 409 if fault == "gap" else 404 if fault == "foreign" else 422
        assert response.status_code == expected, response.text
        assert "cumulative_return" not in response.json()
        if fault == "method":
            assert response.json()["error_code"] == "COMPOSITE_VECTOR_METHOD_MISMATCH"


def test_pinned_vector_refuses_mixed_retained_manifest(monkeypatch):
    from dataclasses import replace

    from app.adapters import composite_materialization_repository as repository
    from tests.composite_authority_helpers import oracle_month_packet

    pairs = [oracle_month_packet(month) for month in (1, 2)]
    packets, wires = map(list, zip(*pairs, strict=True))
    install_test_authorities(monkeypatch, packets)
    install_provider_wires(monkeypatch, packets, wires)
    with TestClient(app, headers=HEADERS) as client:
        commands = []
        for month, (packet, wire) in enumerate(pairs, 1):
            command = command_for_packet(
                packet, period_start=wire["period_start"], period_end=wire["period_end"], restatement_sequence=month
            )
            assert (
                client.post(
                    "/performance/composites/materializations", json=command.model_dump(mode="json")
                ).status_code
                == 202
            )
            assert process_pending_jobs(limit=1) == 1
            commands.append(command)
        store = repository.get_composite_materialization_store()
        original = store.get(commands[0].materialization_id, tenant_id=HEADERS["X-Tenant-Id"])
        decode = repository._materialization_record

        def corrupted_manifest(row):
            record = decode(row)
            return (
                replace(record, source=original.source)
                if record.command.materialization_id == commands[1].materialization_id
                else record
            )

        monkeypatch.setattr(repository, "_materialization_record", corrupted_manifest)
        result = client.post(
            "/performance/composites/twr",
            json={
                **request_for(commands[1]),
                "period_start": "2026-01-01",
                "materialization_ids": [str(command.materialization_id) for command in commands],
            },
        )
        assert (
            result.status_code == 503
            and result.json()["error_code"] == "COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED"
        )
        assert "cumulative_return" not in result.json()


@pytest.mark.parametrize("external_fact", [None, "MEMBER_RETURN", "BEGINNING_ASSETS"])
def test_registered_internal_and_hybrid_v2_without_ending_selection(monkeypatch, external_fact):
    from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
    from app.models.composite_authority import authority_digest
    from app.services.reproducibility_service import generate_value_fingerprint
    from app.workers.lineage_worker import process_pending_jobs as process_lineage
    from tests.composite_authority_helpers import internal_day_packet, rehash_definition
    from tests.composite_materialization_helpers import source_products
    from tests.integration.test_composite_materialization_api import (
        create_stateful_member,
        install_source_wire_controls,
    )

    packet = internal_day_packet()
    install_source_wire_controls(monkeypatch, source_products(tenant_id="synthetic-tenant-a"))

    # The Core helper asserts the owning tenant; adapt only its HTTP header check through
    # a separately scoped client tenant, then rebind the new synthetic authority profile.
    replacements = {
        "synthetic-tenant-a": "tenant-a",
        "2026-09-01": "2026-01-05",
        "2026-09-30": "2026-01-05",
        "external-member-a": "A",
        "external-member-b": "B",
        "external-member-c": "C",
    }

    def tenant_rebind(value):
        if isinstance(value, dict):
            return {key: tenant_rebind(item) for key, item in value.items()}
        if isinstance(value, list):
            return [tenant_rebind(item) for item in value]
        return replacements.get(value, value)

    packet = tenant_rebind(packet)
    from tests.composite_authority_helpers import refresh_support_bindings

    refresh_support_bindings(packet)
    external_wire = None
    if external_fact:
        external_packet, external_wire = observation_packet(ending_assets=False)
        external_packet, external_wire = tenant_rebind(external_packet), tenant_rebind(external_wire)
        external_wire["method_profile_binding"] = deepcopy(
            packet["definition"]["source_authority"]["payload"]["return_method_binding"]
        )
        profile = packet["definition"]["source_authority"]["payload"]
        provider = deepcopy(external_packet["definition"]["source_authority"]["payload"]["providers"][0])
        record = external_packet["supporting_payloads"]["registry"]
        provider["registry_digest"] = authority_digest(record)
        profile["providers"].append(provider)
        profile["mode"] = "HYBRID"
        packet["supporting_payloads"]["registries"].append(record)

        class Observations:
            def read(self, *, tenant_id, selection):
                assert tenant_id == "tenant-a"
                return external_wire

        monkeypatch.setattr(provider_adapter, "provider_observation_source", Observations)
    headers = {**HEADERS, "X-Tenant-Id": "tenant-a"}
    with TestClient(app, headers=headers) as client:
        references = [
            create_stateful_member(client, member, basis="GROSS", precision="DECIMAL_STRICT")
            for member in ("A", "B", "C")
        ]
        process_lineage(limit=100)
        command = command_for_packet(
            packet, period_start="2026-01-05", period_end="2026-01-05", member_calculations=references
        )
        selections = []
        for reference in command.member_calculations:
            outcome = RetainedCompositeMemberResultSource().read_member(
                command,
                reference,
                tenant_id="tenant-a",
                membership_snapshot_id=command.membership_content_hash,
                request_headers=headers,
            )
            assert outcome.state == "READY", outcome
            for original in packet["definition"]["source_authority"]["payload"]["selections"]:
                selected = deepcopy(original)
                if selected["fact"] == external_fact:
                    selected.update(
                        selection_id=selected["selection_id"] + "_" + reference.portfolio_id,
                        member_ids=[reference.portfolio_id],
                        provider_id=external_wire["provider_id"],
                        economic_authority=external_wire["provider_id"],
                        source_product=external_wire["product_name"],
                        source_contract_version=external_wire["product_version"],
                        source_revision=external_wire["revision"],
                        source_watermark=external_wire["watermark"],
                        source_digest=authority_digest(external_wire),
                    )
                    selections.append(selected)
                    continue
                provider = "lotus-performance" if selected["fact"] == "MEMBER_RETURN" else "lotus-core"
                selected.update(
                    selection_id=selected["selection_id"] + "_" + reference.portfolio_id,
                    member_ids=[reference.portfolio_id],
                    provider_id=provider,
                    economic_authority=provider,
                    source_product="CompositeMemberSourceEvidence",
                    source_contract_version="composite-member-source.v1",
                    source_revision=str(reference.calculation_id),
                    source_watermark=reference.input_fingerprint,
                    source_digest=generate_value_fingerprint(outcome.source_evidence, "composite-member-source.v1")[0],
                )
                selections.append(selected)
        packet["definition"]["source_authority"]["payload"]["selections"] = sorted(
            selections, key=lambda s: s["selection_id"]
        )
        rehash_definition(packet["definition"])
        install_test_authorities(monkeypatch, packet)

        async def manage_read(**kwargs):
            product = (
                "attestation"
                if "universe-attestations" in kwargs["url"]
                else ("membership" if "/membership/" in kwargs["url"] else "definition")
            )
            return 200, packet[product]

        monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", manage_read)
        command = command_for_packet(
            packet, period_start="2026-01-05", period_end="2026-01-05", member_calculations=references
        )
        from app.services.composite_materialization.source_contract import admit_pinned_source

        admit_pinned_source(
            command=command,
            tenant_id="tenant-a",
            definition=packet["definition"],
            membership=packet["membership"],
            attestation=packet["attestation"],
        )
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        receipt_response = client.get(accepted.json()["result_path"])
        assert receipt_response.status_code == 200, receipt_response.text
        receipt = receipt_response.json()
        assert receipt["state"] == "COMPLETE", receipt
        for member in receipt["members"]:
            assert member["fact"]["ending_market_value"] is None
            assert member["fact"]["source_authority_identity"]["source_kind"] == (
                "HYBRID" if external_fact else "INTERNAL"
            )
            if external_fact == "MEMBER_RETURN":
                assert member["fact"]["calculation_id"] is None
            else:
                assert member["fact"]["calculation_id"] in [ref["calculation_id"] for ref in references]
            assert len(member["source_evidence"]["observation_wires"]) == (1 if external_fact else 0)
            assert member["source_evidence"]["internal_member_evidence"]["core_snapshots"]
        from app.models.composite_authority import ManageCompositeDefinitionV2
        from app.models.composite_materialization import CompositeMemberSourceEvidence
        from app.services.composite_materialization.internal_authority_policy import require_internal_selection_bindings
        from core.errors import APIUnprocessableEntityError

        reference = command.member_calculations[0]
        evidence = CompositeMemberSourceEvidence.model_validate(
            receipt["members"][0]["source_evidence"]["internal_member_evidence"]
        )
        internal_fact = "BEGINNING_ASSETS" if external_fact == "MEMBER_RETURN" else "MEMBER_RETURN"
        for field, wrong_value in (
            ("source_revision", "different-revision"),
            ("source_watermark", "different-input-fingerprint"),
            ("source_digest", "sha256:" + "f" * 64),
            ("source_cut_id", "different-Manage-cut"),
        ):
            changed = deepcopy(packet["definition"])
            selection = next(
                s
                for s in changed["source_authority"]["payload"]["selections"]
                if s["fact"] == internal_fact and s["member_ids"] == [reference.portfolio_id]
            )
            selection[field] = wrong_value
            with pytest.raises(APIUnprocessableEntityError) as refused:
                require_internal_selection_bindings(
                    ManageCompositeDefinitionV2.model_validate(changed),
                    command,
                    reference,
                    evidence,
                    facts=[internal_fact],
                )
            assert refused.value.error_code == "COMPOSITE_INTERNAL_RECEIPT_BINDING_MISMATCH"
        result = client.post("/performance/composites/twr", json=request_for(command))
        assert result.status_code == 422, result.text
        assert "COMPOSITE_ENDING_ASSETS_UNAVAILABLE" in result.text
