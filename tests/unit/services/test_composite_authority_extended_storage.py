"""Actual owner overlap/bundle/tenant/rollback proofs; require reviewed DB resources."""

import json
import subprocess
import sys
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from app.adapters.composite_result_authority import transitions
from app.adapters.composite_result_authority.records import AuthorityBase
from app.adapters.composite_result_authority.repository import CompositeAuthorityRepository
from app.models.composite_result_authority import AuthorityApplyRequest, AuthorityProposalRequest
from app.models.composite_result_candidates import CompositeResultCandidateResponse
from app.services.async_result_store import AsyncResultStore
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.composite_result_authority.application import CompositeAuthorityApplication
from core.errors import APIError
from tests.composite_authority_window_helpers import FEBRUARY, JANUARY, capture_windows, materialize_window
from tests.composite_result_authority_helpers import AuthorityFixture


@pytest.fixture
def authority(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "extended.db").as_posix()
    fixture = AuthorityFixture(url, monkeypatch)
    try:
        yield fixture
    finally:
        fixture.close()


def retained_pair(authority):
    january = materialize_window(authority, *JANUARY)
    february = materialize_window(authority, *FEBRUARY)
    month = capture_windows(authority, [january])
    wider = capture_windows(authority, [january, february])
    return month, wider


def test_monthly_correction_atomically_stales_wider_projection_preserving_original(authority):
    month, wider = retained_pair(authority)
    month_receipt = authority.decide(authority.proposal(month))
    wider_receipt = authority.decide(authority.proposal(wider))
    corrected = capture_windows(authority, [materialize_window(authority, *JANUARY, corrected=True)])
    decision = authority.decide(authority.proposal(corrected, "REPLACE", 1))
    wider_scope = wider_receipt.selections[0].scope.scope_id
    assert decision.stale_scope_ids == [wider_scope]
    current = authority.application.read(authority.principal("checker"), wider_scope, mode="LATEST_APPROVED")
    assert current.selection.current_use == "STALE" and current.selection.revision == 2
    historical = authority.application.read(
        authority.principal("checker"), wider_scope, mode="EXACT", decision_id=wider_receipt.decision_id
    )
    assert historical.original.model_dump(mode="json") == wider
    assert historical.decision == wider_receipt and historical.current_use == "STALE"
    old_month = authority.application.read(
        authority.principal("checker"),
        month_receipt.selections[0].scope.scope_id,
        mode="AS_REPORTED",
        decision_id=month_receipt.decision_id,
    )
    assert old_month.original.model_dump(mode="json") == month


def test_frozen_wider_dependency_blocks_correction_until_exact_reopen_and_fresh_preview(authority):
    month, wider = retained_pair(authority)
    authority.decide(authority.proposal(month))
    authority.decide(authority.proposal(wider))
    authority.decide(authority.proposal(wider, "FREEZE", 1))
    corrected = capture_windows(authority, [materialize_window(authority, *JANUARY, corrected=True)])
    proposal = authority.proposal(corrected, "REPLACE", 1)
    approval = authority.approval(proposal)
    before = authority.counts()
    with pytest.raises(APIError) as error:
        authority.decide(proposal, approval)
    assert error.value.status_code == 409 and authority.counts() == before
    authority.decide(authority.proposal(wider, "REOPEN", 2))
    with pytest.raises(APIError):
        authority.decide(proposal, approval)
    decision = authority.decide(authority.proposal(corrected, "REPLACE", 1))
    assert len(decision.stale_scope_ids) == 1


def bundle_proposal(authority, candidates, *, action="SELECT_INITIAL", revision=0, bundle=None):
    proposal = authority.application.propose(
        authority.principal("maker"),
        AuthorityProposalRequest(
            proposal_id=uuid4(),
            action=action,
            bundle_id=bundle or uuid4(),
            targets=[
                {"candidate_id": candidate["candidate_id"], "expected_revision": revision} for candidate in candidates
            ],
            reason="Synthetic complete bundle",
            evidence_refs=["synthetic-bundle"],
        ),
    )
    authority.record("bundle_proposal", proposal)
    return proposal


def test_bundle_rejects_partial_protection_and_preserves_complete_membership(authority):
    month, wider = retained_pair(authority)
    proposal = bundle_proposal(authority, [month, wider])
    decision = authority.decide(proposal)
    assert len(decision.selections) == 2
    partial = authority.proposal(month, "FREEZE", 1)
    partial_approval = authority.approval(partial)
    before = authority.counts()
    with pytest.raises(APIError):
        authority.decide(partial, partial_approval)
    assert authority.counts() == before
    frozen = authority.decide(
        bundle_proposal(authority, [month, wider], action="FREEZE", revision=1, bundle=proposal.bundle_id)
    )
    assert len(frozen.selections) == 2 and all(item.frozen and item.revision == 2 for item in frozen.selections)
    reopened = authority.decide(
        bundle_proposal(authority, [month, wider], action="REOPEN", revision=2, bundle=proposal.bundle_id)
    )
    assert all(not item.frozen and item.revision == 3 for item in reopened.selections)


def test_two_populated_tenants_keep_originals_and_all_read_selectors_isolated(authority):
    first = authority.decide(authority.proposal(authority.candidate()))
    candidate_b = authority.candidate(tenant="tenant-b", corrected=True)
    proposal_b = authority.proposal(candidate_b)
    second = authority.decide(proposal_b, tenant="tenant-b")
    assert first.selections[0].scope.scope_id != second.selections[0].scope.scope_id
    read_b = authority.application.read(
        authority.principal("checker", "tenant-b"), second.selections[0].scope.scope_id, mode="LATEST_APPROVED"
    )
    assert read_b.original.model_dump(mode="json") == candidate_b
    before = authority.counts()
    for mode, selector in (
        ("LATEST_APPROVED", {}),
        ("EXACT", {"decision_id": first.decision_id}),
        ("AS_REPORTED", {"decision_id": first.decision_id}),
        ("COMMITTED_TOKEN", {"token": first.snapshot_token}),
    ):
        with pytest.raises(APIError) as error:
            authority.application.read(
                authority.principal("checker", "tenant-b"), first.selections[0].scope.scope_id, mode=mode, **selector
            )
        assert error.value.status_code == 404
    assert authority.counts() == before


def test_failure_after_history_and_pointer_write_rolls_back_whole_owner_transaction(authority, monkeypatch):
    proposal = authority.proposal(authority.candidate())
    approval = authority.approval(proposal)
    before = authority.counts()
    move = transitions._move_pointer

    def interrupted(*args, **kwargs):
        move(*args, **kwargs)
        raise RuntimeError("Synthetic failure after pointer admission")

    with monkeypatch.context() as failure:
        failure.setattr(transitions, "_move_pointer", interrupted)
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            authority.decide(proposal, approval)
    assert authority.counts() == before
    assert authority.decide(proposal, approval).selections[0].revision == 1


def test_independent_restarted_owners_replay_committed_original_after_approval_expiry(authority):
    original = authority.candidate()
    proposal = authority.proposal(original)
    approval = authority.approval(proposal)
    request = AuthorityApplyRequest(decision_id=uuid4(), approval_id=approval.approval_id)
    decision = authority.decide(proposal, approval, request=request)
    before = authority.counts()
    url = authority.store._engine.url.render_as_string(hide_password=False)
    authority.store.close()
    authority.results._engine.dispose()
    owner, results = CompositeMetadataStore(url), AsyncResultStore(url)
    try:
        owner.verify_schema()
        restarted = CompositeAuthorityApplication(
            CompositeAuthorityRepository(owner, results),
            authority.verifier,
            clock=lambda: authority.now + timedelta(days=1),
        )
        replay = restarted.apply(authority.principal("checker"), proposal.proposal_id, request)
        assert replay.model_dump(mode="json") == decision.model_dump(mode="json")
        read = restarted.read(
            authority.principal("checker"),
            decision.selections[0].scope.scope_id,
            mode="COMMITTED_TOKEN",
            token=decision.snapshot_token,
        )
        assert read.original.model_dump(mode="json") == original
        assert authority.counts() == before
    finally:
        owner.close()
        results._engine.dispose()


def test_populated_predecessor_migration_retains_originals_and_is_repeatable(authority):
    candidate = authority.candidate()
    before = authority.counts()
    with authority.store._engine.begin() as connection:
        AuthorityBase.metadata.drop_all(connection)
    authority.store.create_schema()
    authority.store.create_schema()
    authority.store.verify_schema()
    assert authority.counts() == before
    retained = authority.store.get_result_candidate(
        candidate_id=candidate["candidate_id"],
        tenant_id="tenant-a",
        result_store=authority.results,
        principal=authority.principal("checker"),
    )
    assert CompositeResultCandidateResponse.model_validate(retained).model_dump(mode="json") == candidate
    assert retained["response"] == candidate["response"]
    assert authority.decide(authority.proposal(candidate)).selections[0].revision == 1


def test_read_only_schema_verification_refuses_missing_guard_without_repair(authority):
    from app.adapters.durable_schema.catalog import DurableSchemaMigrationRequiredError

    decision = authority.decide(authority.proposal(authority.candidate()))
    trigger = "trg_composite_authority_decisions_update"
    with authority.store._engine.begin() as connection:
        suffix = " ON composite_authority_decisions" if connection.dialect.name == "postgresql" else ""
        connection.exec_driver_sql("DROP TRIGGER " + trigger + suffix)
    with pytest.raises(DurableSchemaMigrationRequiredError):
        authority.store.verify_schema()
    with pytest.raises(DurableSchemaMigrationRequiredError):
        authority.application.read(
            authority.principal("checker"), decision.selections[0].scope.scope_id, mode="LATEST_APPROVED"
        )
    with authority.store._engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            count = connection.scalar(
                text("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name=:name"), {"name": trigger}
            )
        else:
            count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname=:name AND tgrelid = "
                    "'composite_authority_decisions'::regclass"
                ),
                {"name": trigger},
            )
        assert count == 0
        assert inspect(connection).has_table("composite_authority_decisions")


@pytest.mark.parametrize("boundary", ["decisions", "revisions", "scopes", "committed"])
def test_abrupt_process_death_at_actual_owner_boundaries(authority, tmp_path, boundary):
    candidate = authority.candidate()
    proposal = authority.proposal(candidate)
    approval = authority.approval(proposal)
    request = AuthorityApplyRequest(decision_id=uuid4(), approval_id=approval.approval_id)
    before = authority.counts()
    principal = asdict(authority.principal("checker"))
    principal["capabilities"], principal["portfolio_scope"] = (
        sorted(principal["capabilities"]),
        sorted(principal["portfolio_scope"]),
    )
    packet = {
        "boundary": boundary,
        "database_url": authority.store._engine.url.render_as_string(hide_password=False),
        "principal": principal,
        "trust": asdict(authority.trust),
        "policy_digest": authority.verifier.policy_digest,
        "canonical_identities": dict(authority.verifier.canonical_identities),
        "source_authority_packets": authority.source_packets,
        "request": request.model_dump(mode="json"),
        "now": authority.now.isoformat(),
    }
    path = tmp_path / "crash-request.json"
    path.write_text(json.dumps(packet), encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-m", "tests.benchmarks.composite_authority_crash_controls", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    authority.record(
        "abrupt_owner_crash",
        {
            "boundary": boundary,
            "exit_code": run.returncode,
            "stdout": run.stdout,
            "stderr": run.stderr,
            "before": before,
            "after": authority.counts(),
        },
    )
    assert run.returncode == 73 and "reached_actual_authority_boundary=" + boundary in run.stdout, run.stderr
    after = authority.counts()
    if boundary != "committed":
        assert after == before
    else:
        for table in ("decisions", "revisions", "scopes"):
            assert after["composite_authority_" + table] == before["composite_authority_" + table] + 1
    authority.now += timedelta(days=1)
    if boundary != "committed":
        authority.now -= timedelta(days=1)
    recovered = authority.decide(proposal, approval, request=request)
    read = authority.application.read(
        authority.principal("checker"),
        recovered.selections[0].scope.scope_id,
        mode="COMMITTED_TOKEN",
        token=recovered.snapshot_token,
    )
    assert read.decision == recovered and read.original.model_dump(mode="json") == candidate
