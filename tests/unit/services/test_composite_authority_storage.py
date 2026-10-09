"""Actual owner transactions and custody; execution needs reviewed runtime resources."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.composite_result_authority import AuthorityApplyRequest
from app.services.composite_result_authority.application import CompositeAuthorityApplication
from core.errors import APIError
from tests.composite_result_authority_helpers import AuthorityFixture


@pytest.fixture
def authority(tmp_path, monkeypatch):
    fixture = AuthorityFixture("sqlite:///" + (tmp_path / "authority.db").as_posix(), monkeypatch)
    try:
        yield fixture
    finally:
        fixture.close()


def test_independent_approval_does_not_select_and_original_replays_after_expiry(authority):
    candidate = authority.candidate()
    proposal = authority.proposal(candidate)
    approval = authority.approval(proposal)
    scope = proposal.targets[0].scope.scope_id
    with pytest.raises(APIError) as absent:
        authority.application.read(authority.principal("checker"), scope, mode="LATEST_APPROVED")
    assert absent.value.status_code == 404
    request = AuthorityApplyRequest(decision_id=uuid4(), approval_id=approval.approval_id)
    decision = authority.decide(proposal, approval, request=request)
    authority.now += timedelta(days=1)
    assert authority.decide(proposal, approval, request=request) == decision
    for mode, selector in (
        ("LATEST_APPROVED", {}),
        ("EXACT", {"decision_id": decision.decision_id}),
        ("AS_REPORTED", {"decision_id": decision.decision_id}),
        ("COMMITTED_TOKEN", {"token": decision.snapshot_token}),
    ):
        read = authority.application.read(authority.principal("checker"), scope, mode=mode, **selector)
        assert read.original.model_dump(mode="json") == candidate
        assert read.pending_impact_count == 0
        assert read.institution_activation == "UNAVAILABLE"


def test_frozen_replacement_requires_reopen_new_revision_and_new_approval(authority):
    old, corrected = authority.candidate(), authority.candidate(corrected=True)
    first = authority.decide(authority.proposal(old))
    frozen = authority.decide(authority.proposal(old, "FREEZE", 1))
    replacement = authority.proposal(corrected, "REPLACE", 2)
    approval = authority.approval(replacement)
    with pytest.raises(APIError) as refused:
        authority.decide(replacement, approval)
    assert refused.value.status_code == 409
    scope = first.selections[0].scope.scope_id
    read = authority.application.read(authority.principal("checker"), scope, mode="LATEST_APPROVED")
    assert read.decision == frozen and read.pending_impact_count == 1
    reopened = authority.decide(authority.proposal(old, "REOPEN", 2))
    assert reopened.selections[0].revision == 3
    with pytest.raises(APIError):
        authority.decide(replacement, approval)
    changed = authority.decide(authority.proposal(corrected, "REPLACE", 3))
    assert changed.selections[0].candidate_id != first.selections[0].candidate_id
    restored = authority.decide(authority.proposal(old, "RESTORE_PRIOR", 4))
    assert restored.selections[0].candidate_id == first.selections[0].candidate_id
    withdrawn = authority.decide(authority.proposal(old, "WITHDRAW_CURRENT_USE", 5))
    assert withdrawn.selections[0].current_use == "WITHDRAWN"
    historical = authority.application.read(
        authority.principal("checker"), scope, mode="AS_REPORTED", decision_id=first.decision_id
    )
    assert historical.original.model_dump(mode="json") == old
    assert historical.current_use == "WITHDRAWN"


def test_verified_other_tenant_and_missing_financial_trust_cannot_write(authority):
    candidate = authority.candidate()
    proposal = authority.proposal(candidate)
    unavailable = CompositeAuthorityApplication(authority.repository)
    with pytest.raises(APIError):
        unavailable.apply(
            authority.principal("checker", "tenant-b"),
            proposal.proposal_id,
            AuthorityApplyRequest(decision_id=uuid4(), approval_id=uuid4()),
        )
    with authority.store._engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM composite_authority_decisions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM composite_authority_approvals")) == 0


@pytest.mark.parametrize("table", ["proposals", "approvals", "decisions", "revisions", "proposal_scopes"])
@pytest.mark.parametrize("mutation", ["DELETE FROM", "UPDATE"])
def test_raw_sql_cannot_mutate_append_only_workflow(authority, table, mutation):
    candidate = authority.candidate()
    decision = authority.decide(authority.proposal(candidate))
    table_name = "composite_authority_" + table
    statement = (
        f"DELETE FROM {table_name}" if mutation == "DELETE FROM" else f"UPDATE {table_name} SET tenant_id = tenant_id"
    )
    with pytest.raises(IntegrityError):
        with authority.store._engine.begin() as connection:
            connection.execute(text(statement))
    read = authority.application.read(
        authority.principal("checker"), decision.selections[0].scope.scope_id, mode="LATEST_APPROVED"
    )
    assert read.decision == decision
