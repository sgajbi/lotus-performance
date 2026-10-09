"""Native PostgreSQL parity of captured-original authority owner transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.composite_result_authority import AuthorityApplyRequest, AuthorityProposalRequest
from core.errors import APIError
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
from tests.composite_result_authority_helpers import AuthorityFixture
from tests.unit.services.test_composite_authority_storage import (
    test_frozen_replacement_requires_reopen_new_revision_and_new_approval as _prove_frozen_replacement,
)
from tests.unit.services.test_composite_authority_storage import (
    test_independent_approval_does_not_select_and_original_replays_after_expiry as _prove_original_replay,
)
from tests.unit.services.test_composite_authority_storage import (
    test_raw_sql_cannot_mutate_append_only_workflow as _prove_append_only,
)
from tests.unit.services.test_composite_authority_storage import (
    test_verified_other_tenant_and_missing_financial_trust_cannot_write as _prove_other_tenant,
)


@pytest.fixture
def authority(monkeypatch):
    fixture = AuthorityFixture(get_postgres_database_url(), monkeypatch)
    try:
        yield fixture
    finally:
        fixture.close()


def test_postgres_approval_original_and_committed_selectors(authority):
    _prove_original_replay(authority)


def test_postgres_freeze_reopen_replace_restore_withdraw(authority):
    _prove_frozen_replacement(authority)


def test_postgres_other_tenant_and_unavailable_authority(authority):
    _prove_other_tenant(authority)


@pytest.mark.parametrize("table", ["proposals", "approvals", "decisions", "revisions", "proposal_scopes"])
@pytest.mark.parametrize("mutation", ["DELETE FROM", "UPDATE"])
def test_postgres_append_only_custody(authority, table, mutation):
    _prove_append_only(authority, table, mutation)


@pytest.mark.parametrize("table", ["proposals", "approvals", "decisions", "revisions", "proposal_scopes", "scopes"])
def test_postgres_truncate_refuses_even_with_cascade(authority, table):
    decision = authority.decide(authority.proposal(authority.candidate()))
    with pytest.raises(IntegrityError):
        with authority.store._engine.begin() as connection:
            connection.execute(text(f"TRUNCATE composite_authority_{table} CASCADE"))
    authority.store.verify_schema()
    read = authority.application.read(
        authority.principal("checker"), decision.selections[0].scope.scope_id, mode="LATEST_APPROVED"
    )
    assert read.decision == decision


def test_postgres_equivalent_proposal_race_returns_one_original(authority):
    candidate = authority.candidate()
    request = AuthorityProposalRequest(
        proposal_id=uuid4(),
        action="SELECT_INITIAL",
        targets=[{"candidate_id": candidate["candidate_id"], "expected_revision": 0}],
        reason="Synthetic retry race",
        evidence_refs=["synthetic-evidence"],
    )
    barrier = Barrier(2)

    def propose():
        barrier.wait(timeout=10)
        return authority.application.propose(authority.principal("maker"), request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(propose) for _ in range(2)]
        first, second = [future.result(timeout=30) for future in futures]
    assert first == second
    with authority.store._engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM composite_authority_proposals")) == 1


@pytest.mark.parametrize("same_request", [True, False])
def test_postgres_apply_race_never_partially_selects(authority, same_request):
    proposal = authority.proposal(authority.candidate())
    approval = authority.approval(proposal)
    first_request = AuthorityApplyRequest(decision_id=uuid4(), approval_id=approval.approval_id)
    requests = [
        first_request,
        first_request if same_request else AuthorityApplyRequest(decision_id=uuid4(), approval_id=approval.approval_id),
    ]
    barrier = Barrier(2)

    def apply(request):
        barrier.wait(timeout=10)
        try:
            return authority.application.apply(authority.principal("checker"), proposal.proposal_id, request)
        except APIError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply, request) for request in requests]
        outcomes = [future.result(timeout=30) for future in futures]
    receipts = [value for value in outcomes if not isinstance(value, APIError)]
    assert len(receipts) == (2 if same_request else 1)
    if same_request:
        assert receipts[0] == receipts[1]
    else:
        refusals = [value for value in outcomes if isinstance(value, APIError)]
        assert len(refusals) == 1 and refusals[0].status_code == 409
    with authority.store._engine.connect() as connection:
        counts = tuple(
            connection.scalar(text(f"SELECT count(*) FROM composite_authority_{table}"))
            for table in ("decisions", "revisions", "scopes")
        )
    assert counts == (1, 1, 1)
