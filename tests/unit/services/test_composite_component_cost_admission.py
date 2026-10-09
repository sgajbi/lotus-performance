"""Independent financial scope and full-payload admission; synthetic test authorities only."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.composite_authority import authority_digest
from app.models.composite_component_costs import CompositeGrossCostMember
from app.ports import composite_external_evidence, composite_model_fees
from app.services.composite_materialization.component_cost_admission import admit_component_cost_source
from app.services.composite_materialization.model_fee_source_admission import model_fee_resolution_request
from app.services.composite_materialization.source_contract import PinnedCompositeSource
from core.errors import APIError
from tests.composite_component_source_helpers import (
    FrozenFinancialSupplier,
    FrozenFinancialVerifier,
    component_source_inputs,
    financial_source,
)
from tests.composite_model_fee_helpers import model_fee_source_inputs


@pytest.fixture
def case(monkeypatch):
    packet, _, _, _ = model_fee_source_inputs()
    outcomes = [
        SimpleNamespace(
            portfolio_id=member,
            fact=SimpleNamespace(
                beginning_market_value=Decimal(100),
                return_value=Decimal(".02"),
                source_snapshot_id="sha256:" + digit * 64,
            ),
        )
        for member, digit in (("A", "1"), ("B", "2"), ("C", "3"))
    ]
    profile, members = component_source_inputs(packet, outcomes)
    packet, profile, command, _ = model_fee_source_inputs(profile)
    source = PinnedCompositeSource.model_validate(
        {
            **{key: packet[key] for key in ("definition", "membership", "attestation")},
            "wire_evidence": {key: packet[key] for key in ("definition", "membership", "attestation")},
        }
    )
    request = model_fee_resolution_request(source, command, tenant_id=profile["tenant_id"])
    wire = financial_source(packet, command, members)
    supplier = FrozenFinancialSupplier(wire, request)
    verifier = FrozenFinancialVerifier(wire, request, source.definition.definition_version)
    monkeypatch.setattr(composite_model_fees, "composite_gross_cost_resolver", lambda: supplier)
    monkeypatch.setattr(composite_external_evidence, "composite_receipt_verifier", lambda: verifier)
    from app.models.composite_component_model_fees import CompositeComponentModelFeeProfile

    return source, command, CompositeComponentModelFeeProfile.model_validate(profile), supplier, verifier


def admit(case, **kwargs):
    source, command, profile, _, _ = case
    return admit_component_cost_source(source, command, profile, tenant_id=profile.tenant_id, **kwargs)


def test_complete_original_financial_payload_retained_and_source_not_refetched(case):
    receipt = admit(case)
    assert receipt.source.model_dump(mode="json") == case[3].wire
    assert receipt.verification == case[4].receipt
    case[3].wire = {"unavailable": True}
    assert admit(case, retained_wire=receipt.model_dump(mode="json")) == receipt
    assert case[3].calls == 1


@pytest.mark.parametrize(
    "fault",
    [
        "tenant",
        "member",
        "date",
        "currency",
        "method",
        "calendar",
        "base",
        "gross",
        "nested-hash",
        "missing-member",
        "duplicate-member",
        "watermark",
        "definition",
        "profile",
        "producer",
        "oversized",
    ],
)
def test_foreign_incomplete_or_changed_financial_wire_refuses(case, fault):
    wire = case[3].wire
    scope = wire["members"][0]["evidence"]["scope"]
    if fault in ("method", "calendar", "base"):
        scope[{"method": "method_binding", "calendar": "calendar_binding", "base": "reference_base"}[fault]][
            "revision"
        ] = "other"
    elif fault == "nested-hash":
        wire["members"][0]["evidence"]["included_components"][0]["source_evidence"]["digest"] = "sha256:" + "a" * 64
    elif fault in ("tenant", "member", "date", "currency", "gross"):
        field, value = {
            "tenant": ("tenant_id", "other"),
            "member": ("member_id", "other"),
            "date": ("period_end", "2026-01-06"),
            "currency": ("reporting_currency", "EUR"),
            "gross": ("gross_receipt_digest", "sha256:" + "e" * 64),
        }[fault]
        scope[field] = value
    elif fault == "missing-member":
        wire["members"].pop()
    elif fault == "duplicate-member":
        wire["members"].append(deepcopy(wire["members"][0]))
    elif fault == "profile":
        wire["model_fee_binding"]["revision"] = "other"
    elif fault == "definition":
        wire["definition_content_hash"] = "sha256:" + "b" * 64
    elif fault == "producer":
        wire["producer_id"] = "other.issuer"
    elif fault == "oversized":
        wire["unknown"] = "x" * (1024 * 1024)
    else:
        wire["source_watermark"] = "different"
    with pytest.raises(APIError):
        admit(case)


def test_financial_verification_expectation_cannot_be_method_or_foreign_issuer(case):
    receipt = admit(case)
    from dataclasses import replace

    case[4].expectation = replace(case[4].expectation, issuer_id="method.only.issuer")
    with pytest.raises(APIError):
        admit(case, retained_wire=receipt.model_dump(mode="json"))


def test_complete_zero_requires_explicit_empty_complete_declaration(case):
    member = deepcopy(case[3].wire["members"][0])
    member["evidence"]["included_components"] = []
    with pytest.raises(ValueError, match="complete-zero"):
        CompositeGrossCostMember.model_validate(member)
    member["completeness"] = "COMPLETE_ZERO"
    payload = deepcopy(member)
    del payload["evidence"]["evidence_binding"]
    member["evidence"]["evidence_binding"]["digest"] = authority_digest(payload)
    assert CompositeGrossCostMember.model_validate(member).completeness == "COMPLETE_ZERO"


def test_component_catalog_concurrent_retry_preserves_original_publisher_and_wire(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.models.composite_component_model_fees import CompositeComponentModelFeeProfile
    from app.services.composite_metadata_store import CompositeMetadataStore
    from core.errors import APIConflictError
    from scripts.durable_schema_apply import apply_durable_schema
    from tests.unit.models.test_composite_component_model_fees import component_case

    url = "sqlite:///" + (tmp_path / "catalog.db").as_posix()
    assert apply_durable_schema(database_url=url).status == "passed"
    profile = CompositeComponentModelFeeProfile.model_validate(component_case()[0])
    barrier = Barrier(2)
    store = CompositeMetadataStore(url)

    def publish(actor):
        barrier.wait(timeout=10)
        return store.publish_model_fee_profile(profile, tenant_id=profile.tenant_id, actor_id=actor)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(publish, actor) for actor in ("publisher.a", "publisher.b")]
            receipts = [future.result(timeout=30) for future in futures]
        assert receipts[0] == receipts[1]
        assert receipts[0].profile == profile
        changed = profile.model_copy(update={"bundled_fee_context": "BUNDLED"})
        with pytest.raises(APIConflictError):
            store.publish_model_fee_profile(changed, tenant_id=profile.tenant_id, actor_id="replacement")
        assert (
            store.get_model_fee_profile(
                tenant_id=profile.tenant_id, profile_id=profile.profile_id, revision=profile.revision
            )
            == receipts[0]
        )
    finally:
        store.close()


def test_component_external_capture_requires_a_new_evidence_path(tmp_path):
    import json

    from tests.composite_component_source_helpers import write_component_capture

    path = tmp_path / "captured-wire.json"
    original = {"qualification": "SYNTHETIC_TEST_ONLY", "profile_response": {"status": "REFUSED"}}
    write_component_capture(path, original)
    before = path.read_bytes()
    assert json.loads(before) == original
    with pytest.raises(FileExistsError):
        write_component_capture(path, {"profile_response": {"status": "SUCCESS"}})
    assert path.read_bytes() == before
