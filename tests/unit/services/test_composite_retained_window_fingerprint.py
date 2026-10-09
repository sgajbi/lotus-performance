"""Legacy replay hashes remain stable; new fee custody participates when bound."""

from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest

from app.models.composite_authority import EvidenceBinding, authority_digest
from app.models.composite_materialization import CompositeMaterializationState
from app.services.composite_calculation_service import retained_window_evidence
from app.services.composite_materialization.records import MaterializationRecord
from tests.composite_currency_normalization_helpers import normalization_wire
from tests.composite_materialization_helpers import admitted, command_for
from tests.composite_model_fee_helpers import model_fee_source_inputs


@pytest.mark.parametrize(
    "view,fx,expected",
    [
        ("NET_ACTUAL", False, "sha256:0c1321b90d0bf138afd6ebcbc17a12c2926c2a561a362393c7449e05333138cc"),
        ("NET_ACTUAL", True, "sha256:fd00161bc931bc3ad35e7cca881b369251466ce3479c2508ccb05c524ae6e7bf"),
        ("GROSS", False, "sha256:8203b3faf9f1f99b4a3508782437963bdddf8389904d0a805644b5ef2de13685"),
        ("GROSS", True, "sha256:d93de8af4fe8b740609f5ddfa3aa8d004f937b56e771ec53228dc2f847cb215c"),
    ],
)
def test_pre_model_fee_retained_window_fingerprint_matches_committed_baseline(view, fx, expected):
    # Frozen using the actual command/source models and retained_window_evidence at
    # 5fad773ac0d99ab7587e48f226fe01c99d165a21. Preserve its prior nulls,
    # executor identity and FX authority; exclude only absent new fee fields.
    command = command_for(
        calculation_id=UUID("00000000-0000-4000-8000-000000000001"),
        materialization_id=UUID("00000000-0000-4000-8000-000000000002"),
        member_calculations=[],
        return_view=view,
    )
    source = admitted(command)
    if fx:
        wire = normalization_wire()
        binding = EvidenceBinding(
            product_name=wire["product_name"],
            product_version="v1",
            revision=wire["revision"],
            digest=authority_digest(wire),
        )
        command = command.model_copy(update={"currency_normalization_binding": binding})
        source = source.model_copy(update={"currency_normalization_wire": wire})
    record = MaterializationRecord(
        command=command,
        actor_id="operator",
        source=source,
        outcomes=[],
        state=CompositeMaterializationState.COMPLETE,
        reason_code=None,
        revision=1,
    )
    assert retained_window_evidence(record, {}).retained_receipt_fingerprint == expected


@pytest.mark.parametrize("component", ["binding", "profile"])
def test_bound_model_fee_retained_window_fingerprint_detects_changed_custody(component):
    _, wire, command, source = model_fee_source_inputs()
    source = source.model_copy(update={"model_fee_wire": wire})
    record = MaterializationRecord(
        command=command,
        actor_id="operator",
        source=source,
        outcomes=[],
        state=CompositeMaterializationState.COMPLETE,
        reason_code=None,
        revision=1,
    )
    original = retained_window_evidence(record, {}).retained_receipt_fingerprint
    if component == "binding":
        changed_binding = command.model_fee_binding.model_copy(update={"revision": "profile.changed"})
        changed = replace(record, command=command.model_copy(update={"model_fee_binding": changed_binding}))
    else:
        changed_wire = deepcopy(wire)
        changed_wire["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.003"
        changed = replace(record, source=source.model_copy(update={"model_fee_wire": changed_wire}))
    assert retained_window_evidence(changed, {}).retained_receipt_fingerprint != original
    assert retained_window_evidence(record, {}).retained_receipt_fingerprint == original
