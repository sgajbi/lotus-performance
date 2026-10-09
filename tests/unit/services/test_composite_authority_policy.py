"""No database or runtime allocation: authority policy and application boundaries."""

import base64
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.composite_principal_credentials import CredentialTrust, PrincipalGrants, VerifiedCompositePrincipal
from app.adapters.composite_result_authority.verification import SignedFinancialAuthorityVerifier
from app.models.composite_result_authority import (
    AuthorityAction,
    AuthorityActor,
    AuthorityApplyRequest,
    AuthorityApprovalRequest,
    AuthorityImpact,
    AuthorityProposalRequest,
    AuthorityProposalResponse,
    AuthorityScope,
    AuthoritySelection,
    AuthorityVector,
    AuthorityWindow,
)
from app.services.composite_result_authority.application import CompositeAuthorityApplication
from app.services.composite_result_authority.policy import changed_dependency, next_selection, validate_transition
from core.errors import APIError

DIGEST = "sha256:" + "1" * 64
OTHER = "sha256:" + "2" * 64
ID = UUID(int=1)
NOW = datetime(2026, 10, 10, tzinfo=UTC)


def vector(*, digest=DIGEST, end=date(2026, 1, 31)):
    return AuthorityVector(
        scope=AuthorityScope(
            scope_id=DIGEST,
            base_id=DIGEST,
            composite_id="COMPOSITE",
            period_start=date(2026, 1, 1),
            period_end=end,
            return_view="GROSS",
            reporting_currency="USD",
            method_family="ASSET_WEIGHTED_COMPOSITE_TWR",
        ),
        candidate_id=ID,
        original_response_digest=DIGEST,
        vector_digest=digest,
        windows=[
            AuthorityWindow(
                period_start=date(2026, 1, 1), period_end=end, materialization_id=ID, retained_digest=digest
            )
        ],
        maker_subjects=["maker"],
    )


def selected(*, frozen=False, current_use="SELECTED"):
    return AuthoritySelection(
        scope=vector().scope,
        revision=4,
        candidate_id=ID,
        vector_digest=DIGEST,
        frozen=frozen,
        current_use=current_use,
        bundle_id=None,
    )


# This independent acceptance matrix includes frozen withdrawals: original
# custody/protection remains while current financial use can be withdrawn.
@pytest.mark.parametrize(
    "frozen,state,allowed",
    [
        (False, "SELECTED", {"REPLACE", "FREEZE", "RESTORE_PRIOR", "WITHDRAW_CURRENT_USE"}),
        (True, "SELECTED", {"REOPEN", "WITHDRAW_CURRENT_USE"}),
        (False, "STALE", {"REPLACE", "RESTORE_PRIOR", "WITHDRAW_CURRENT_USE"}),
        (False, "WITHDRAWN", {"REPLACE", "RESTORE_PRIOR"}),
        (True, "WITHDRAWN", {"REOPEN"}),
    ],
)
@pytest.mark.parametrize("action", list(AuthorityAction))
def test_financial_state_acceptance(action, frozen, state, allowed):
    previous = selected(frozen=frozen, current_use=state)
    if action.value in allowed:
        validate_transition(action, vector(), 4, previous)
        result = next_selection(action, vector(), previous, None)
        assert result.revision == 5
        assert result.candidate_id == ID
        if action == AuthorityAction.WITHDRAW_CURRENT_USE:
            assert result.current_use == "WITHDRAWN" and result.frozen == frozen
    else:
        with pytest.raises(APIError) as refusal:
            validate_transition(action, vector(), 4, previous)
        assert refusal.value.status_code == 409


@pytest.mark.parametrize("action", list(AuthorityAction))
def test_absent_scope_only_accepts_initial_zero_revision(action):
    if action == AuthorityAction.SELECT_INITIAL:
        validate_transition(action, vector(), 0, None)
        assert next_selection(action, vector(), None, None).revision == 1
    else:
        with pytest.raises(APIError):
            validate_transition(action, vector(), 0, None)
    with pytest.raises(APIError):
        validate_transition(action, vector(), 1, None)


@pytest.mark.parametrize("action", list(AuthorityAction))
def test_stale_cas_refuses_every_action(action):
    with pytest.raises(APIError):
        validate_transition(action, vector(), 3, selected())


@pytest.mark.parametrize(
    "action", [AuthorityAction.FREEZE, AuthorityAction.REOPEN, AuthorityAction.WITHDRAW_CURRENT_USE]
)
def test_protection_cannot_substitute_a_different_original(action):
    with pytest.raises(APIError):
        validate_transition(action, vector(digest=OTHER), 4, selected(frozen=action == AuthorityAction.REOPEN))


def test_replacement_proposal_can_expose_frozen_impact_but_cannot_apply():
    validate_transition(AuthorityAction.REPLACE, vector(digest=OTHER), 4, selected(frozen=True), applying=False)
    with pytest.raises(APIError):
        validate_transition(AuthorityAction.REPLACE, vector(digest=OTHER), 4, selected(frozen=True))


def test_dependency_pins_detect_changes_and_refuse_partition_substitution():
    assert not changed_dependency(vector(), vector())
    assert changed_dependency(vector(), vector(digest=OTHER))
    with pytest.raises(APIError):
        changed_dependency(vector(), vector(end=date(2026, 1, 30)))


def test_later_partition_disagreement_cannot_hide_behind_an_earlier_changed_pin():
    old, new = vector(), vector(digest=OTHER)
    old.windows.append(
        AuthorityWindow(
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28), materialization_id=ID, retained_digest=DIGEST
        )
    )
    new.windows.append(
        AuthorityWindow(
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 27), materialization_id=ID, retained_digest=OTHER
        )
    )
    with pytest.raises(APIError):
        changed_dependency(old, new)


def test_request_rejects_scope_assertions_duplicate_targets_and_missing_bundle():
    body = dict(
        proposal_id=ID,
        action="SELECT_INITIAL",
        targets=[dict(candidate_id=ID, expected_revision=0)],
        reason="Initial review",
        evidence_refs=["evidence-1"],
    )
    AuthorityProposalRequest(**body)
    for extra in ({"tenant_id": "caller-tenant"}, {"authorizedScope": ["book"]}):
        with pytest.raises(ValueError):
            AuthorityProposalRequest(**body, **extra)
    with pytest.raises(ValueError):
        AuthorityProposalRequest(**{**body, "targets": body["targets"] * 2, "bundle_id": ID})
    with pytest.raises(ValueError):
        AuthorityProposalRequest(
            **{**body, "targets": body["targets"] + [dict(candidate_id=UUID(int=2), expected_revision=0)]}
        )


def test_default_financial_trust_refuses_before_approval_or_decision_writes():
    repository = Mock()
    repository.existing_approval.return_value = None
    repository.existing_decision.return_value = None
    proposal = SimpleNamespace(proposal_id=ID)
    repository.proposal.return_value = proposal
    repository.approval_material.return_value = proposal, object(), "evidence", object()
    application = CompositeAuthorityApplication(repository, clock=lambda: NOW)
    with pytest.raises(APIError) as approval:
        application.approve(object(), ID, AuthorityApprovalRequest(approval_id=ID, financial_evidence="evidence"))
    assert approval.value.status_code == 503
    with pytest.raises(APIError) as decision:
        application.apply(object(), ID, AuthorityApplyRequest(decision_id=ID, approval_id=ID))
    assert decision.value.status_code == 503
    repository.approve.assert_not_called()
    repository.apply.assert_not_called()


def _encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@pytest.fixture
def signed_financial_case():
    key = Ed25519PrivateKey.generate()
    authority = Mock()
    authority.revoked.return_value = False
    authority.tenant_member.return_value = True
    authority.grants.return_value = PrincipalGrants(frozenset({"operations.runtime.manage"}), frozenset({"portfolio"}))
    authority.application_grants.return_value = authority.grants.return_value
    trust = CredentialTrust(
        "synthetic-financial-issuer",
        "synthetic-performance-consumer",
        {
            "keys": [
                {
                    "kid": "synthetic-key",
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "x": _encoded(key.public_key().public_bytes_raw()),
                }
            ]
        },
    )
    checker = VerifiedCompositePrincipal(
        "user",
        "checker",
        "tenant-a",
        frozenset({"operations.runtime.manage"}),
        frozenset({"portfolio"}),
        "checker-credential",
    )
    proposal = AuthorityProposalResponse(
        proposal_id=ID,
        proposal_digest=DIGEST,
        maker_subject="maker",
        maker=AuthorityActor(subject="maker", principal_kind="user", credential_id="maker-credential"),
        action=AuthorityAction.SELECT_INITIAL,
        targets=[vector()],
        expected_revisions={DIGEST: 0},
        bundle_id=None,
        reason="Synthetic policy proof",
        evidence_refs=["synthetic-evidence"],
        impact=AuthorityImpact(affected_scope_ids=[], dependency_revision_digest=DIGEST),
        created_at_utc=NOW,
    )
    verifier = SignedFinancialAuthorityVerifier(
        trust, authority, DIGEST, {"maker": "human-1", "checker": "human-2"}, frozenset({"checker"})
    )
    claims = {
        "iss": trust.expected_issuer,
        "aud": trust.expected_audience,
        "sub": "checker",
        "jti": "financial-evidence-1",
        "tenant": "tenant-a",
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
        "purpose": "COMPOSITE_FINANCIAL_RESULT_ACTION",
        "qualification": "SYNTHETIC_NON_CERTIFYING",
        "proposal_digest": DIGEST,
        "approval_id": str(ID),
        "action": "SELECT_INITIAL",
        "policy_digest": DIGEST,
        "canonical_checker": "human-2",
        "canonical_makers": ["human-1"],
    }

    def sign(overrides=None):
        header = _encoded(json.dumps({"alg": "EdDSA", "kid": "synthetic-key"}).encode())
        payload = _encoded(json.dumps({**claims, **(overrides or {})}).encode())
        content = f"{header}.{payload}"
        return content + "." + _encoded(key.sign(content.encode("ascii")))

    def verify(*, evidence=None, **overrides):
        return verifier.verify(
            proposal=proposal,
            approval_id=str(ID),
            financial_evidence=evidence or sign(),
            checker=overrides.get("checker", checker),
            actor=overrides.get("actor", checker),
            now=NOW,
        )

    return SimpleNamespace(
        verifier=verifier, authority=authority, checker=checker, proposal=proposal, sign=sign, verify=verify
    )


def test_real_ed25519_financial_purpose_has_only_noncertifying_posture(signed_financial_case):
    case = signed_financial_case
    result = case.verify()
    assert result.receipt.qualification == "SYNTHETIC_NON_CERTIFYING"
    assert result.receipt.canonical_checker == "human-2"
    assert result.receipt.proposal_digest == DIGEST
    assert result.receipt.valid_until == NOW + timedelta(hours=1)


@pytest.mark.parametrize(
    "claim,value",
    [
        ("purpose", "ECONOMIC_SOURCE_AUTHORITY"),
        ("qualification", "INSTITUTION_APPROVED"),
        ("tenant", "tenant-b"),
        ("sub", "maker"),
        ("proposal_digest", OTHER),
        ("approval_id", str(UUID(int=2))),
        ("action", "FREEZE"),
        ("policy_digest", OTHER),
        ("canonical_checker", "human-1"),
        ("canonical_makers", []),
        ("iss", "untrusted"),
        ("aud", "unrelated-consumer"),
        ("exp", int(NOW.timestamp())),
    ],
)
def test_valid_signature_cannot_grant_wrong_financial_purpose_or_binding(signed_financial_case, claim, value):
    case = signed_financial_case
    with pytest.raises(APIError) as refusal:
        case.verify(evidence=case.sign({claim: value}))
    assert refusal.value.status_code == 403


def test_signature_tampering_and_same_human_alias_are_refused(signed_financial_case):
    case = signed_financial_case
    token = case.sign()
    header, payload, signature = token.split(".")
    replacement = _encoded(json.dumps({"purpose": "COMPOSITE_FINANCIAL_RESULT_ACTION"}).encode())
    with pytest.raises(APIError):
        case.verify(evidence=f"{header}.{replacement}.{signature}")
    case.verifier.canonical_identities["checker"] = "human-1"
    with pytest.raises(APIError):
        case.verify(evidence=case.sign({"canonical_checker": "human-1"}))


@pytest.mark.parametrize(
    "failure", ["revoked", "membership", "capability", "portfolio", "delegated", "service", "tenant", "actor"]
)
def test_financial_admission_rechecks_current_identity_and_grants(signed_financial_case, failure):
    case = signed_financial_case
    overrides = {}
    if failure == "revoked":
        case.authority.revoked.return_value = True
    elif failure == "membership":
        case.authority.tenant_member.return_value = False
    elif failure in {"capability", "portfolio"}:
        case.authority.grants.return_value = PrincipalGrants(
            frozenset() if failure == "capability" else frozenset({"operations.runtime.manage"}),
            frozenset() if failure == "portfolio" else frozenset({"portfolio"}),
        )
    else:
        from dataclasses import replace

        if failure == "delegated":
            overrides["checker"] = replace(case.checker, delegated_actor="application", principal_kind="delegated")
            case.authority.application_grants.return_value = PrincipalGrants(frozenset(), frozenset())
        elif failure == "service":
            overrides["checker"] = replace(case.checker, principal_kind="service")
        elif failure == "tenant":
            overrides["actor"] = replace(case.checker, tenant_id="tenant-b")
        elif failure == "actor":
            overrides["actor"] = replace(case.checker, subject="unapproved-actor")
    with pytest.raises(APIError):
        case.verify(**overrides)


def test_original_idempotent_receipts_do_not_require_expired_financial_evidence_again():
    repository, verifier = Mock(), Mock()
    original = SimpleNamespace(valid_until=NOW - timedelta(days=1))
    repository.existing_approval.return_value = original
    repository.existing_decision.return_value = original
    application = CompositeAuthorityApplication(repository, verifier, clock=lambda: NOW)
    assert (
        application.approve(object(), ID, AuthorityApprovalRequest(approval_id=ID, financial_evidence="evidence"))
        is original
    )
    assert application.apply(object(), ID, AuthorityApplyRequest(decision_id=ID, approval_id=ID)) is original
    verifier.verify.assert_not_called()
    repository.approve.assert_not_called()
    repository.apply.assert_not_called()
