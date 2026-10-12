"""Retained receipt corruption and exact selector contracts without a live store."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.adapters.composite_result_authority import codec, context, proposals, reads, repository, transitions, vector
from app.models.composite_result_authority import (
    AuthorityActor,
    AuthorityApprovalResponse,
    AuthorityDecisionResponse,
    AuthorityImpact,
    AuthorityProposalResponse,
    AuthorityScope,
    AuthoritySelection,
    AuthorityVector,
    AuthorityWindow,
)
from core.errors import APIError

DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def receipts():
    scope = AuthorityScope(
        scope_id=DIGEST,
        base_id=DIGEST,
        composite_id="CMP-CUSTODY",
        period_start="2026-01-01",
        period_end="2026-01-31",
        return_view="GROSS",
        reporting_currency="USD",
        method_family="ASSET_WEIGHTED_COMPOSITE_TWR",
    )
    selection = AuthoritySelection(
        scope=scope,
        revision=1,
        candidate_id=uuid4(),
        vector_digest=DIGEST,
        frozen=False,
        current_use="SELECTED",
        bundle_id=None,
    )
    actor = AuthorityActor(subject="maker", principal_kind="user", credential_id="credential")
    proposal = AuthorityProposalResponse(
        proposal_id=uuid4(),
        proposal_digest=DIGEST,
        maker_subject="maker",
        maker=actor,
        action="SELECT_INITIAL",
        targets=[
            AuthorityVector(
                scope=scope,
                candidate_id=selection.candidate_id,
                original_response_digest=DIGEST,
                vector_digest=DIGEST,
                maker_subjects=["maker"],
                windows=[
                    AuthorityWindow(
                        period_start=scope.period_start,
                        period_end=scope.period_end,
                        materialization_id=uuid4(),
                        retained_digest=DIGEST,
                    )
                ],
            )
        ],
        expected_revisions={scope.scope_id: 0},
        bundle_id=None,
        reason="Retained custody contract",
        evidence_refs=["review"],
        impact=AuthorityImpact(affected_scope_ids=[], dependency_revision_digest=DIGEST),
        created_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )
    proposal = proposal.model_copy(
        update={"proposal_digest": codec.digest(proposal.model_dump(mode="json", exclude={"proposal_digest"}))}
    )
    approval = AuthorityApprovalResponse(
        approval_id=uuid4(),
        proposal_id=proposal.proposal_id,
        proposal_digest=proposal.proposal_digest,
        checker_subject="checker",
        canonical_checker="checker-person",
        policy_digest=DIGEST,
        evidence_digest=codec.digest({"financial_evidence": "signed-evidence"}),
        valid_until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    decision = AuthorityDecisionResponse(
        decision_id=uuid4(),
        proposal_id=proposal.proposal_id,
        approval_id=approval.approval_id,
        action="SELECT_INITIAL",
        actor=actor,
        selections=[selection],
        stale_scope_ids=[],
        snapshot_token="pending",
        recorded_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )
    decision = decision.model_copy(update={"snapshot_token": codec.snapshot_token(decision)})
    return proposal, approval, decision, selection


def retained_row(kind, receipt):
    payload = {"response_json": codec.wire(receipt)}
    for key in ("proposal_id", "approval_id", "decision_id"):
        if hasattr(receipt, key):
            payload[key] = str(getattr(receipt, key))
    if kind == "proposal":
        payload["content_digest"] = receipt.proposal_digest
    elif kind == "approval":
        payload["financial_evidence"] = "signed-evidence"
    elif kind == "decision":
        payload["receipt_digest"] = codec.digest(receipt)
    else:
        payload = dict(
            selection_json=codec.wire(receipt),
            scope_id=receipt.scope.scope_id,
            revision=receipt.revision,
            candidate_id=str(receipt.candidate_id),
        )
    return SimpleNamespace(**payload)


@pytest.mark.parametrize("index,kind", enumerate(("proposal", "approval", "decision", "selection")))
def test_retained_receipt_roundtrip_and_invalid_json_refusal(receipts, index, kind):
    receipt = receipts[index]
    row = retained_row(kind, receipt)
    reader = getattr(codec, kind + "_response")
    assert reader(row) == receipt
    setattr(row, "selection_json" if kind == "selection" else "response_json", "{broken")
    with pytest.raises(APIError) as error:
        reader(row)
    assert error.value.error_code == "COMPOSITE_RESULT_CUSTODY_REFUSED"
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "index,kind,field,value",
    [
        (0, "proposal", "content_digest", "sha256:" + "b" * 64),
        (0, "proposal", "proposal_id", "different"),
        (1, "approval", "approval_id", "different"),
        (1, "approval", "proposal_id", "different"),
        (1, "approval", "financial_evidence", "substituted-evidence"),
        (2, "decision", "receipt_digest", "sha256:" + "b" * 64),
        (2, "decision", "decision_id", "different"),
        (2, "decision", "proposal_id", "different"),
        (2, "decision", "approval_id", "different"),
        (3, "selection", "scope_id", "sha256:" + "b" * 64),
        (3, "selection", "revision", 2),
        (3, "selection", "candidate_id", "different"),
    ],
)
def test_retained_receipt_identity_and_digest_cannot_be_substituted(receipts, index, kind, field, value):
    row = retained_row(kind, receipts[index])
    setattr(row, field, value)
    with pytest.raises(APIError, match="custody"):
        getattr(codec, kind + "_response")(row)


def test_resealed_decision_still_requires_valid_snapshot_token_and_selection_state(receipts):
    decision = receipts[2].model_copy(update={"snapshot_token": "authority:v1:forged"})
    with pytest.raises(APIError, match="custody"):
        codec.decision_response(retained_row("decision", decision))
    selection = receipts[3].model_copy(update={"frozen": True, "current_use": "STALE"})
    with pytest.raises(APIError, match="custody"):
        codec.selection_response(retained_row("selection", selection))


@pytest.mark.parametrize(
    "mode,identity,token",
    [
        ("LATEST_APPROVED", uuid4(), None),
        ("LATEST_APPROVED", None, "token"),
        ("EXACT", None, None),
        ("EXACT", uuid4(), "token"),
        ("AS_REPORTED", None, None),
        ("AS_REPORTED", uuid4(), "token"),
        ("unknown", uuid4(), None),
        ("COMMITTED_TOKEN", uuid4(), "token"),
        ("COMMITTED_TOKEN", None, None),
        ("COMMITTED_TOKEN", None, "authority:v2:x:" + "a" * 64),
        ("COMMITTED_TOKEN", None, "authority:v1:not-a-uuid:" + "a" * 64),
        ("COMMITTED_TOKEN", None, "authority:v1:" + str(uuid4()) + ":short"),
    ],
)
def test_authority_selectors_refuse_ambiguous_or_malformed_input(receipts, mode, identity, token):
    session = Mock()
    with pytest.raises(APIError) as error:
        reads._resolve_selector(session, "tenant", receipts[3], mode, identity, token)
    assert error.value.status_code == 422
    assert error.value.error_code == "COMPOSITE_AUTHORITY_UNSUPPORTED"
    session.get.assert_not_called()


def test_valid_exact_and_committed_selectors_preserve_decision_identity(receipts):
    session = Mock()
    identity = receipts[2].decision_id
    for mode in ("EXACT", "AS_REPORTED"):
        assert reads._resolve_selector(session, "tenant", receipts[3], mode, identity, None) == identity
    assert (
        reads._resolve_selector(session, "tenant", receipts[3], "COMMITTED_TOKEN", None, receipts[2].snapshot_token)
        == identity
    )


def test_authority_read_requires_present_decision_exact_token_and_revision_custody(receipts):
    decision, selection = receipts[2:]
    session = Mock()
    session.get.return_value = None
    with pytest.raises(APIError) as error:
        reads._decision(session, "tenant", decision.decision_id, "EXACT", None)
    assert error.value.status_code == 404
    session.get.return_value = retained_row("decision", decision)
    with pytest.raises(APIError) as error:
        reads._decision(session, "tenant", decision.decision_id, "COMMITTED_TOKEN", "different")
    assert error.value.status_code == 422
    assert (
        reads._decision(session, "tenant", decision.decision_id, "COMMITTED_TOKEN", decision.snapshot_token) == decision
    )
    with pytest.raises(APIError) as error:
        reads._selection(session, "tenant", "sha256:" + "b" * 64, decision)
    assert error.value.status_code == 404
    session.get.return_value = None
    with pytest.raises(APIError, match="custody"):
        reads._selection(session, "tenant", selection.scope.scope_id, decision)
    row = retained_row("selection", selection)
    row.decision_id = str(decision.decision_id)
    session.get.return_value = row
    assert reads._selection(session, "tenant", selection.scope.scope_id, decision) == selection
    row.decision_id = str(uuid4())
    with pytest.raises(APIError, match="custody"):
        reads._selection(session, "tenant", selection.scope.scope_id, decision)


@pytest.mark.parametrize(
    "field,value",
    [("base_id", "sha256:" + "b" * 64), ("bundle_id", str(uuid4())), ("period_start", None), ("period_end", None)],
)
def test_current_pointer_cannot_disagree_with_immutable_revision(receipts, field, value):
    selection = receipts[3]
    pointer = SimpleNamespace(
        revision=1,
        base_id=selection.scope.base_id,
        bundle_id=None,
        period_start=selection.scope.period_start,
        period_end=selection.scope.period_end,
    )
    setattr(pointer, field, value)
    session = Mock()
    session.get.side_effect = [pointer, retained_row("selection", selection)]
    with pytest.raises(APIError, match="custody"):
        context.current_selection(session, "tenant", selection.scope.scope_id)


def test_missing_current_revision_is_custody_failure(receipts):
    session = Mock()
    session.get.side_effect = [SimpleNamespace(revision=1), None]
    with pytest.raises(APIError, match="custody"):
        context.current_selection(session, "tenant", receipts[3].scope.scope_id)


def test_original_candidate_absence_is_tenant_scoped(monkeypatch):
    reader = Mock(return_value=None)
    monkeypatch.setattr(vector, "read_candidate", reader)
    principal, session, identity = SimpleNamespace(tenant_id="tenant-a"), Mock(), uuid4()
    with pytest.raises(APIError) as error:
        vector.original_candidate(session, principal, identity)
    assert error.value.status_code == 404
    reader.assert_called_once_with(session, tenant_id="tenant-a", candidate_id=identity, principal=principal)


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        codec.wire(
            dict(
                principal_kind="user",
                subject="checker",
                tenant_id="other",
                credential_id="credential",
                delegated_actor=None,
                capabilities=[],
                portfolio_scope=[],
            )
        ),
        codec.wire(
            dict(
                principal_kind="user",
                subject="different",
                tenant_id="tenant",
                credential_id="credential",
                delegated_actor=None,
                capabilities=[],
                portfolio_scope=[],
            )
        ),
    ],
)
def test_retained_checker_cannot_rehydrate_wrong_tenant_or_identity(receipts, payload):
    with pytest.raises(APIError, match="custody"):
        repository._retained_checker(SimpleNamespace(checker_json=payload), receipts[1], "tenant")


@pytest.mark.parametrize("reader", [proposals.get_proposal, proposals.get_approval])
def test_proposal_and_approval_absence_preserves_not_found_contract(reader):
    session = Mock()
    session.get.return_value = None
    with pytest.raises(APIError) as error:
        reader(session, SimpleNamespace(tenant_id="tenant"), uuid4())
    assert error.value.status_code == 404
    session.add.assert_not_called()


def test_existing_proposal_rejects_changed_retry_content():
    session = Mock()
    session.get.return_value = SimpleNamespace(request_digest="original")
    with pytest.raises(APIError, match="retry content changed"):
        proposals._existing_proposal(
            session, SimpleNamespace(tenant_id="tenant"), SimpleNamespace(proposal_id=uuid4()), "substituted"
        )
    session.add.assert_not_called()


def test_approval_cannot_bind_a_different_retained_proposal(receipts, monkeypatch):
    session = Mock()
    session.get.return_value = retained_row("approval", receipts[1])
    monkeypatch.setattr(
        proposals,
        "get_proposal",
        lambda *args: receipts[0].model_copy(update={"proposal_digest": "sha256:" + "b" * 64}),
    )
    with pytest.raises(APIError) as error:
        proposals.get_approval(session, SimpleNamespace(tenant_id="tenant"), receipts[1].approval_id)
    assert error.value.status_code == 403


@pytest.mark.parametrize("same_digest", [False, True])
def test_approval_retry_requires_both_original_content_and_proposal(receipts, same_digest):
    from app.models.composite_result_authority import AuthorityApprovalRequest

    request = AuthorityApprovalRequest(approval_id=receipts[1].approval_id, financial_evidence="signed-evidence")
    principal = SimpleNamespace(tenant_id="tenant", subject="checker")
    session = Mock()
    session.get.return_value = SimpleNamespace(
        request_digest=codec.digest({"request": request.model_dump(mode="json"), "checker": "checker"})
        if same_digest
        else "changed",
        proposal_id=str(uuid4()),
    )
    with pytest.raises(APIError, match="retry content changed"):
        proposals.existing_approval(session, principal, receipts[0].proposal_id, request)


def test_second_approval_cannot_overwrite_immutable_approval(receipts, monkeypatch):
    principal, session = SimpleNamespace(tenant_id="tenant", subject="checker"), Mock()
    monkeypatch.setattr(proposals, "existing_approval", lambda *args: None)
    monkeypatch.setattr(proposals, "get_proposal", lambda *args: receipts[0])
    fence = Mock()
    monkeypatch.setattr(proposals, "fence_scopes", fence)
    session.scalar.return_value = str(receipts[1].approval_id)
    with pytest.raises(APIError, match="immutable approval"):
        proposals.approve(session, principal, receipts[0].proposal_id, None, None, datetime.now(UTC))
    session.add.assert_not_called()
    fence.assert_called_once()


def test_approval_impact_preview_drift_requires_new_exact_proposal(receipts, monkeypatch):
    principal, session = SimpleNamespace(tenant_id="tenant", subject="checker"), Mock()
    monkeypatch.setattr(proposals, "existing_approval", lambda *args: None)
    monkeypatch.setattr(proposals, "get_proposal", lambda *args: receipts[0])
    monkeypatch.setattr(proposals, "fence_scopes", Mock())
    monkeypatch.setattr(proposals, "overlapping_selections", lambda *args: [receipts[3]])
    monkeypatch.setattr(proposals, "current_selection", lambda *args: None)
    session.scalar.return_value = None
    with pytest.raises(APIError, match="Impact preview changed"):
        proposals.approve(session, principal, receipts[0].proposal_id, None, None, datetime.now(UTC))
    session.add.assert_not_called()


def test_decision_retry_and_duplicate_decision_never_replace_original(receipts, monkeypatch):
    principal, session = SimpleNamespace(tenant_id="tenant"), Mock()
    request = SimpleNamespace(decision_id=uuid4())
    session.get.return_value = SimpleNamespace(request_digest="other", proposal_id=str(receipts[0].proposal_id))
    monkeypatch.setattr(transitions, "digest", lambda value: "request-digest")
    with pytest.raises(APIError, match="retry content changed"):
        transitions.existing_decision(session, principal, receipts[0].proposal_id, request)
    monkeypatch.setattr(transitions, "get_proposal", lambda *args: receipts[0])
    monkeypatch.setattr(transitions, "fence_scopes", Mock())
    monkeypatch.setattr(transitions, "existing_decision", lambda *args: None)
    session.scalar.return_value = str(receipts[2].decision_id)
    with pytest.raises(APIError, match="immutable decision"):
        transitions.apply_decision(session, principal, receipts[0].proposal_id, request, None, datetime.now(UTC))
    session.add.assert_not_called()


def test_apply_rejects_approval_for_another_exact_proposal(receipts, monkeypatch):
    session = Mock()
    session.scalar.return_value = None
    monkeypatch.setattr(transitions, "get_proposal", lambda *args: receipts[0])
    monkeypatch.setattr(transitions, "fence_scopes", Mock())
    monkeypatch.setattr(transitions, "existing_decision", lambda *args: None)
    monkeypatch.setattr(
        transitions,
        "get_approval",
        lambda *args: (None, receipts[1], receipts[0].model_copy(update={"reason": "different"})),
    )
    with pytest.raises(APIError, match="exact proposal"):
        transitions.apply_decision(
            session,
            SimpleNamespace(tenant_id="tenant"),
            receipts[0].proposal_id,
            SimpleNamespace(approval_id=receipts[1].approval_id),
            SimpleNamespace(receipt=receipts[1]),
            datetime.now(UTC),
        )
    session.add.assert_not_called()


def test_missing_vector_or_excess_window_budget_refuses_before_authority_write():
    session, principal = Mock(), SimpleNamespace(tenant_id="tenant")
    target = SimpleNamespace(candidate_id=uuid4())
    session.get.return_value = None
    with pytest.raises(APIError) as error:
        vector.require_vector_budget(session, principal, [target])
    assert error.value.status_code == 404
    session.get.return_value = SimpleNamespace(materialization_vector_json=codec.wire(["window"] * 121))
    with pytest.raises(APIError) as error:
        vector.require_vector_budget(session, principal, [target])
    assert error.value.status_code == 422
    session.add.assert_not_called()


def test_missing_or_incomplete_retained_materialization_refuses_custody(monkeypatch):
    session = Mock()
    session.get.return_value = None
    with pytest.raises(APIError, match="custody"):
        vector._captured_record(session, "tenant", uuid4())
    session.get.return_value = object()
    monkeypatch.setattr(
        vector, "read_retained_record", lambda *args, **kwargs: SimpleNamespace(state="PENDING", source=None)
    )
    with pytest.raises(APIError, match="custody"):
        vector._captured_record(session, "tenant", uuid4())


def test_restore_requires_an_original_previously_selected_in_this_scope(receipts, monkeypatch):
    session = Mock()
    session.scalar.return_value = None
    monkeypatch.setattr(proposals, "current_selection", lambda *args: receipts[3])
    monkeypatch.setattr(proposals, "validate_transition", Mock())
    request = SimpleNamespace(action="RESTORE_PRIOR", targets=[SimpleNamespace(expected_revision=1)])
    with pytest.raises(APIError, match="previously selected"):
        proposals._admit_targets(session, SimpleNamespace(tenant_id="tenant"), request, receipts[0].targets)


def test_atomic_bundle_cannot_select_two_originals_for_same_scope(receipts, monkeypatch):
    from app.models.composite_result_authority import AuthorityProposalRequest

    request = AuthorityProposalRequest(
        proposal_id=uuid4(),
        action="SELECT_INITIAL",
        targets=[dict(candidate_id=uuid4(), expected_revision=0), dict(candidate_id=uuid4(), expected_revision=0)],
        bundle_id=uuid4(),
        reason="atomic contract",
        evidence_refs=["review"],
    )
    monkeypatch.setattr(proposals, "_existing_proposal", lambda *args: None)
    monkeypatch.setattr(proposals, "require_vector_budget", Mock())
    monkeypatch.setattr(proposals, "captured_vector", lambda *args: receipts[0].targets[0])
    session = Mock()
    with pytest.raises(APIError, match="same scope"):
        proposals.propose(session, SimpleNamespace(tenant_id="tenant"), request, datetime.now(UTC))
    session.add.assert_not_called()


@pytest.mark.parametrize(
    "changed,bundle,frozen,action",
    [(True, uuid4(), False, "REPLACE"), (True, None, True, "REPLACE"), (True, None, False, "FREEZE")],
)
def test_overlapping_dependencies_require_complete_mutable_replacement(receipts, changed, bundle, frozen, action):
    selection = receipts[3].model_copy(update={"bundle_id": bundle, "frozen": frozen})
    with pytest.raises(APIError):
        transitions._propagate_dependency(selection, action, changed)
    assert transitions._propagate_dependency(receipts[3], "FREEZE", False) is None


def test_authority_pointer_compare_and_swap_cannot_lose_expected_revision(receipts):
    session = Mock()
    session.execute.return_value.rowcount = 0
    with pytest.raises(APIError, match="compare-and-swap"):
        transitions._move_pointer(session, "tenant", receipts[3], 1)


def test_impact_closure_limit_and_retained_vector_drift_refuse(receipts, monkeypatch):
    session = Mock()
    session.scalars.return_value.all.return_value = [object()] * 121
    with pytest.raises(APIError, match="120-scope"):
        context.overlapping_selections(session, SimpleNamespace(tenant_id="tenant"), receipts[0].targets)
    monkeypatch.setattr(
        context,
        "captured_vector",
        lambda *args: receipts[0].targets[0].model_copy(update={"vector_digest": "sha256:" + "b" * 64}),
    )
    with pytest.raises(APIError, match="custody"):
        context.require_retained_vectors(session, SimpleNamespace(tenant_id="tenant"), receipts[0])


def test_read_refuses_rehydrated_scope_that_disagrees_with_retained_vector(receipts, monkeypatch):
    monkeypatch.setattr(reads, "current_selection", lambda *args: receipts[3])
    monkeypatch.setattr(reads, "_decision", lambda *args: receipts[2])
    monkeypatch.setattr(reads, "_selection", lambda *args: receipts[3])
    monkeypatch.setattr(
        reads,
        "captured_vector",
        lambda *args: receipts[0].targets[0].model_copy(update={"vector_digest": "sha256:" + "b" * 64}),
    )
    with pytest.raises(APIError, match="custody"):
        reads.read_authority(
            Mock(),
            SimpleNamespace(tenant_id="tenant"),
            receipts[3].scope.scope_id,
            mode="EXACT",
            decision_id=receipts[2].decision_id,
        )
