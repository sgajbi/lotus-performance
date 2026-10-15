"""Actual configured adapter and retained custody against pinned producer products."""

import json
from copy import deepcopy
from datetime import date

import pytest

from app.adapters.composite_membership_source import ManageCompositeMembershipSource
from app.core.config import get_settings
from app.models.composite_authority import ControlledScenarioDefinitionV3
from app.models.composite_controlled_scenario_evidence import ControlledScenarioSubjectFinalizationReceipt
from app.services.composite_materialization.source_contract import (
    PinnedCompositeSource,
    require_pinned_source_scope,
    source_digest,
)
from core.errors import APIError
from tests.composite_authority_helpers import command_for_packet
from tests.composite_controlled_scenario_helpers import (
    graph,
    install_http_transport,
    install_independent_test_trust,
    source_packet,
)


async def read_source(command=None, packet=None):
    packet = packet or source_packet()
    return await ManageCompositeMembershipSource().read_pinned(
        command or command_for_packet(packet),
        tenant_id="synthetic-tenant",
        actor_id="reader",
        role="DPM_COMPOSITE_CONSUMER",
    )


@pytest.mark.asyncio
async def test_actual_adapter_reads_every_original_product_and_retains_full_scenario_graph(monkeypatch):
    packet = source_packet()
    trust_calls = install_independent_test_trust(monkeypatch)
    calls = install_http_transport(monkeypatch)
    source = await read_source(packet=packet)
    assert isinstance(source.definition, ControlledScenarioDefinitionV3)
    assert isinstance(source.published_eligibility.receipt, ControlledScenarioSubjectFinalizationReceipt)
    assert source.wire_evidence.model_dump() == packet
    assert source.published_eligibility.receipt.model_dump(mode="json") == graph()
    assert [request.method for request in calls] == ["GET", "GET", "GET", "POST"]
    assert all(request.headers["x-tenant-id"] == "synthetic-tenant" for request in calls)
    binding = json.loads(calls[-1].content)
    assert binding["product_name"] == "CompositeSubjectEvaluationApproval" and binding["product_version"] == "v3"
    assert any(request.purpose == "ELIGIBILITY_POLICY" for request in trust_calls)
    retained = PinnedCompositeSource.model_validate_json(source.model_dump_json())
    assert retained == source
    before = len(calls)
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    require_pinned_source_scope(retained, command=command_for_packet(packet), tenant_id="synthetic-tenant")
    assert len(calls) == before


@pytest.mark.asyncio
async def test_absent_default_configuration_refuses_before_any_request(monkeypatch):
    calls = install_http_transport(monkeypatch)
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    with pytest.raises(APIError) as refused:
        await read_source()
    assert refused.value.error_code == "COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose",
    [
        "ELIGIBILITY_POLICY",
        "ELIGIBILITY_POLICY_EVALUATION",
        "RETURN_METHOD_CALENDAR",
        "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE",
        "PROVIDER_REGISTRATION",
    ],
)
async def test_unavailable_independent_verification_refuses_actual_adapter(monkeypatch, purpose):
    install_independent_test_trust(monkeypatch, denied_purpose=purpose)
    install_http_transport(monkeypatch)
    with pytest.raises(APIError) as refused:
        await read_source()
    assert refused.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["definition", "membership", "attestation"])
async def test_actual_adapter_refuses_changed_original_product_hashes(monkeypatch, product):
    packet = deepcopy(source_packet())
    packet[product]["content_hash"] = "sha256:" + "0" * 64
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=packet)
    with pytest.raises(APIError) as refused:
        await read_source(packet=packet)
    assert refused.value.error_code == "COMPOSITE_SOURCE_HASH_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["membership", "attestation"])
async def test_actual_adapter_refuses_foreign_original_tenant(monkeypatch, product):
    packet = deepcopy(source_packet())
    packet[product]["tenant_id"] = "foreign-tenant"
    # Keeping pinned original content hashes exposes the original-wire hash guard.
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=packet)
    with pytest.raises(APIError):
        await read_source(packet=packet)


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["membership", "attestation"])
async def test_rehashed_foreign_companion_refuses_identity_join_not_only_raw_hash(monkeypatch, product):
    packet = deepcopy(source_packet())
    packet[product]["tenant_id"] = "foreign-tenant"
    packet[product]["content_hash"] = source_digest(packet[product])
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=packet)
    with pytest.raises(APIError) as refused:
        await read_source(packet=packet)
    assert refused.value.error_code == "COMPOSITE_SOURCE_SCOPE_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,tenant,reason",
    [
        ({}, "foreign-tenant", "COMPOSITE_SOURCE_SCOPE_MISMATCH"),
        ({"period_end": date(2026, 10, 1)}, "synthetic-tenant", "COMPOSITE_UNIVERSE_COVERAGE_MISMATCH"),
        ({"reporting_currency": "EUR"}, "synthetic-tenant", "COMPOSITE_SOURCE_POLICY_MISMATCH"),
        ({"definition_content_hash": "sha256:" + "0" * 64}, "synthetic-tenant", "COMPOSITE_SOURCE_HASH_MISMATCH"),
    ],
)
async def test_retained_graph_never_changes_admitted_tenant_window_currency_or_hash(
    monkeypatch, changes, tenant, reason
):
    packet = source_packet()
    install_independent_test_trust(monkeypatch)
    calls = install_http_transport(monkeypatch)
    source = await read_source(packet=packet)
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    command = command_for_packet(packet).model_copy(update=changes)
    with pytest.raises(APIError) as refused:
        require_pinned_source_scope(source, command=command, tenant_id=tenant)
    assert refused.value.error_code == reason
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_retained_typed_projection_cannot_diverge_from_original_wire(monkeypatch):
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch)
    source = await read_source()
    source.wire_evidence.membership["decided_by"] = "replaced-owner"
    with pytest.raises(APIError) as refused:
        require_pinned_source_scope(source, command=command_for_packet(source_packet()), tenant_id="synthetic-tenant")
    assert refused.value.error_code == "COMPOSITE_SOURCE_RETAINED_WIRE_MISMATCH"
