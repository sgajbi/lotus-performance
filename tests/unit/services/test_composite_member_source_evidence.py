"""Independent receipt controls; controlled producer fixtures are not live QA."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.composite_authority import EvidenceBinding
from app.models.composite_materialization import CompositeMemberMaterializationOutcome
from app.services.composite_materialization.member_evidence_policy import require_member_source_evidence
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIConflictError, APIError
from tests.composite_materialization_helpers import MemberSource, command_for


@pytest.mark.parametrize("retryable, state", [(None, "BLOCKED"), (False, "BLOCKED"), (True, "WAITING")])
def test_member_source_api_refusal_preserves_disposition_without_financial_evidence(monkeypatch, retryable, state):
    from app.adapters import composite_member_result_source as adapter

    command = command_for()
    reference = command.member_calculations[0]
    execution = SimpleNamespace(response_payload={})
    monkeypatch.setattr(adapter.execution_registry, "get_execution_for_tenant", lambda *args, **kwargs: execution)
    monkeypatch.setattr(adapter, "authorize_calculation_result_access", lambda **kwargs: None)
    monkeypatch.setattr(adapter, "_execution_refusal", lambda *args, **kwargs: None)

    def refuse(*args, **kwargs):
        raise APIError(422, "Controlled evidence refusal", retryable=retryable)

    monkeypatch.setattr(adapter.PerformanceResponse, "model_validate", refuse)
    outcome = adapter.RetainedCompositeMemberResultSource().read_member(
        command,
        reference,
        tenant_id="tenant-a",
        membership_snapshot_id=command.membership_content_hash,
        request_headers={},
    )
    assert outcome.state == state
    assert outcome.retryable is bool(retryable)
    assert outcome.reason_code == "MEMBER_FINANCIAL_EVIDENCE_REFUSED"
    assert outcome.fact is None and outcome.source_evidence is None


def member_receipt():
    command = command_for()
    outcome = MemberSource().read_member(
        command,
        command.member_calculations[0],
        tenant_id="tenant-a",
        membership_snapshot_id=command.membership_content_hash,
        request_headers={"x-tenant-id": "tenant-a"},
    )
    return command, outcome


def test_retained_receipt_accepts_actual_source_and_calculation_identity():
    command, outcome = member_receipt()
    require_member_source_evidence(command, outcome)
    assert outcome.fact.beginning_market_value == 100
    assert outcome.fact.ending_market_value == 110
    assert outcome.fact.return_value == Decimal("0.10")
    assert outcome.fact.source_snapshot_id != command.membership_content_hash


@pytest.mark.parametrize("restored", [False, True], ids=["alternative-adapter", "restored-legacy-wire"])
def test_fx_bound_member_cannot_downgrade_to_valid_legacy_evidence(restored):
    command, outcome = member_receipt()
    if restored:
        outcome = CompositeMemberMaterializationOutcome.model_validate(outcome.model_dump(mode="json"))
    # Even an identity member with money already in USD must retain its v3 proof.
    require_member_source_evidence(command, outcome)
    assert outcome.fact.reporting_currency == outcome.source_evidence.source_assets.portfolio_currency == "USD"
    bound = command.model_copy(
        update={
            "currency_normalization_binding": EvidenceBinding(
                product_name="CompositeCurrencyNormalization",
                product_version="v1",
                revision="fx-r1",
                digest="sha256:" + "a" * 64,
            )
        }
    )
    with pytest.raises(APIConflictError) as refused:
        require_member_source_evidence(bound, outcome, tenant_id="tenant-a", currency_normalization_wire={})
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_MEMBER_EVIDENCE_REFUSED"
    # The immutable legacy receipt is still valid for its original unbound command.
    require_member_source_evidence(command, outcome)


@pytest.mark.parametrize(
    "path,value",
    [
        (("membership_snapshot_id",), "sha256:" + "c" * 64),
        (("engine_version",), "different-engine"),
        (("precision_mode",), "DECIMAL_STRICT"),
        (("calculation_request", "portfolio", "portfolio_id"), "foreign-member"),
        (("source_assets", "portfolio_currency"), "EUR"),
        (("source_assets", "observations", 0, "valuation_date"), "2026-01-06"),
        (("source_assets", "observations", 0, "beginning_market_value"), "99"),
        (("source_assets", "observations", 0, "ending_market_value"), "111"),
        (("core_snapshots", 0, "source_identifier"), "foreign-member"),
        (("core_snapshots", 0, "request_as_of_date"), "2026-01-06"),
    ],
)
def test_individually_rehashed_conflicting_receipt_cannot_support_a_fact(path, value):
    command, outcome = member_receipt()
    payload = deepcopy(outcome.model_dump(mode="json"))
    target = payload["source_evidence"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    changed = CompositeMemberMaterializationOutcome.model_validate(payload)
    evidence = changed.source_evidence
    # An attacker changing the outer hashes cannot rewrite the pinned engine,
    # source scope or fact economics. Exercise the guards beyond byte integrity.
    evidence.asset_evidence_fingerprint = generate_value_fingerprint(
        evidence.source_assets, "portfolio-source-assets.v1"
    )[0]
    changed.fact.source_snapshot_id = generate_value_fingerprint(evidence, "composite-member-source.v1")[0]
    with pytest.raises(APIConflictError) as refused:
        require_member_source_evidence(command, changed)
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_MEMBER_EVIDENCE_REFUSED"


def test_receipt_byte_integrity_and_duplicate_snapshot_guards():
    command, outcome = member_receipt()
    outcome.source_evidence.core_snapshots[0].response_fingerprint = "c" * 64
    with pytest.raises(APIConflictError):
        require_member_source_evidence(command, outcome)
    outcome.source_evidence.core_snapshots.append(outcome.source_evidence.core_snapshots[0])
    outcome.fact.source_snapshot_id = generate_value_fingerprint(outcome.source_evidence, "composite-member-source.v1")[
        0
    ]
    with pytest.raises(APIConflictError):
        require_member_source_evidence(command, outcome)


@pytest.mark.parametrize("change", ["missing-fact", "missing-receipt", "missing-reference", "asset-digest"])
def test_retained_evidence_boundary_refuses_missing_authority_and_individually_rehashed_asset_digest(change):
    command, outcome = member_receipt()
    if change == "missing-fact":
        outcome = outcome.model_copy(update={"fact": None})
    elif change == "missing-receipt":
        outcome = outcome.model_copy(update={"source_evidence": None})
    elif change == "missing-reference":
        command = command.model_copy(update={"member_calculations": []})
    else:
        outcome.source_evidence.asset_evidence_fingerprint = "sha256:" + "c" * 64
        outcome.fact.source_snapshot_id = generate_value_fingerprint(
            outcome.source_evidence, "composite-member-source.v1"
        )[0]
    with pytest.raises(APIConflictError) as refused:
        require_member_source_evidence(command, outcome)
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_MEMBER_EVIDENCE_REFUSED"


@pytest.mark.parametrize("mutation", ["missing-receipt", "missing-snapshots", "nonfinite-money", "naive-clock"])
def test_missing_or_malformed_source_receipt_is_not_a_ready_outcome(mutation):
    _, outcome = member_receipt()
    payload = outcome.model_dump(mode="json")
    if mutation == "missing-receipt":
        payload["source_evidence"] = None
    elif mutation == "missing-snapshots":
        payload["source_evidence"]["core_snapshots"] = []
    elif mutation == "nonfinite-money":
        payload["source_evidence"]["source_assets"]["observations"][0]["beginning_market_value"] = "NaN"
    else:
        payload["source_evidence"]["core_snapshots"][0]["retrieved_at_utc"] = "2026-01-06T00:00:00"
    with pytest.raises(ValidationError):
        CompositeMemberMaterializationOutcome.model_validate(payload)
