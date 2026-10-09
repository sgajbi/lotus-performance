"""Synthetic result-authority fixture over actual materialization and capture owners."""

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.adapters.composite_principal_credentials import CredentialTrust, PrincipalGrants, VerifiedCompositePrincipal
from app.adapters.composite_result_authority.repository import CompositeAuthorityRepository
from app.adapters.composite_result_authority.verification import SignedFinancialAuthorityVerifier
from app.api.endpoints.composites import calculate_composite_twr
from app.core.config import get_settings
from app.models.composite_authority import authority_digest
from app.models.composite_result_authority import (
    AuthorityApplyRequest,
    AuthorityApprovalRequest,
    AuthorityProposalRequest,
)
from app.models.composite_result_candidates import CompositeResultCandidateResponse
from app.services.async_result_store import AsyncResultStore
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.composite_result_authority.application import CompositeAuthorityApplication
from app.services.compute_job_store import ComputeJobStore


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class SyntheticPrincipalAuthority:
    def revoked(self, subject, credential_id):
        return False

    def tenant_member(self, subject, tenant_id):
        return subject in {"maker", "checker"} and tenant_id in {"tenant-a", "tenant-b"}

    def grants(self, subject, tenant_id):
        return PrincipalGrants(
            frozenset({"operations.runtime.manage", "operations.runtime.read"}), frozenset({"A", "B", "C"})
        )

    def application_grants(self, application, tenant_id):
        return self.grants(application, tenant_id)


class AuthorityFixture:
    """Explicit synthetic issuer/grants, never deployment certification or fallback."""

    def __init__(self, database_url, monkeypatch):
        self.monkeypatch, self.source_packets = monkeypatch, []
        self.results = AsyncResultStore(database_url)
        self.results.create_schema()
        self.store = CompositeMetadataStore(database_url)
        self.store.create_schema()
        self.jobs = ComputeJobStore(database_url)
        self.jobs.create_schema()
        self.ledger = CompositeMaterializationStore(database_url)
        self.repository = CompositeAuthorityRepository(self.store, self.results)
        self.key = Ed25519PrivateKey.generate()
        self.now = datetime(2026, 10, 10, tzinfo=UTC)
        self.trust = CredentialTrust(
            "synthetic-authority-issuer",
            "synthetic-performance",
            {
                "keys": [
                    {
                        "kid": "synthetic",
                        "kty": "OKP",
                        "crv": "Ed25519",
                        "x": encoded(self.key.public_key().public_bytes_raw()),
                    }
                ]
            },
        )
        mapping = {
            subject: "synthetic-human-maker" for subject in ("maker", "operator", "manage-operator", "manage-attester")
        }
        mapping["checker"] = "synthetic-human-checker"
        self.verifier = SignedFinancialAuthorityVerifier(
            self.trust,
            SyntheticPrincipalAuthority(),
            authority_digest({"synthetic": "policy"}),
            mapping,
            frozenset({"checker"}),
        )
        self.application = CompositeAuthorityApplication(self.repository, self.verifier, clock=lambda: self.now)
        monkeypatch.setattr(get_settings(), "APP_GIT_COMMIT_SHA", "e67ef6dba9fe2763c828fa5aa3a2ff2ff1db0b0c")
        monkeypatch.setattr(
            "app.services.composite_calculation_service.get_composite_materialization_store", lambda: self.ledger
        )
        self.record("before_counts", self.counts())

    def record(self, kind, value):
        directory = os.getenv("LOTUS_AUTHORITY_PROOF_ARTIFACT_DIR")
        if directory is None:
            return
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        with (root / (kind + "-" + uuid4().hex + ".json")).open("x", encoding="utf-8") as stream:
            json.dump(
                {"evidence_class": "synthetic_local_conformance", "kind": kind, "payload": payload},
                stream,
                sort_keys=True,
            )
            stream.write("\n")

    def counts(self):
        tables = [
            "analytics_async_result",
            "composite_result_candidates",
            "composite_materializations",
            "composite_authority_proposals",
            "composite_authority_approvals",
            "composite_authority_decisions",
            "composite_authority_revisions",
            "composite_authority_scopes",
            "composite_authority_proposal_scopes",
        ]
        with self.store._engine.connect() as connection:
            return {table: connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in tables}

    def principal(self, subject, tenant="tenant-a"):
        grants = self.verifier.principal_authority.grants(subject, tenant)
        return VerifiedCompositePrincipal(
            "user", subject, tenant, grants.capabilities, grants.portfolio_scope, "synthetic-credential-" + subject
        )

    def candidate(self, *, corrected=False, tenant="tenant-a"):
        from datetime import date

        from tests.composite_authority_window_helpers import capture_windows, materialize_window

        command = materialize_window(self, date(2026, 1, 5), date(2026, 1, 5), corrected=corrected, tenant=tenant)
        return capture_windows(self, [command], tenant=tenant)

    def capture(self, request, *, tenant="tenant-a"):
        original = calculate_composite_twr(request, tenant)
        captured = self.store.capture_result_candidate(
            candidate_id=uuid4(),
            request=request,
            response=original,
            principal=self.principal("maker", tenant),
            result_store=self.results,
        )
        self.record("captured_original", captured)
        return CompositeResultCandidateResponse.model_validate(captured).model_dump(mode="json")

    def proposal(self, candidate, action="SELECT_INITIAL", revision=0):
        proposal = self.application.propose(
            self.principal("maker", candidate["tenant_id"]),
            AuthorityProposalRequest(
                proposal_id=uuid4(),
                action=action,
                targets=[{"candidate_id": candidate["candidate_id"], "expected_revision": revision}],
                reason="Synthetic retained-original conformance",
                evidence_refs=["synthetic-review"],
            ),
        )
        self.record("proposal", proposal)
        return proposal

    def financial_request(self, proposal, *, tenant="tenant-a", claim_changes=None):
        approval_id = uuid4()
        makers = {proposal.maker_subject} | {maker for target in proposal.targets for maker in target.maker_subjects}
        claims = {
            "iss": self.trust.expected_issuer,
            "aud": self.trust.expected_audience,
            "sub": "checker",
            "tenant": tenant,
            "jti": str(uuid4()),
            "exp": int((self.now + timedelta(hours=1)).timestamp()),
            "purpose": "COMPOSITE_FINANCIAL_RESULT_ACTION",
            "qualification": "SYNTHETIC_NON_CERTIFYING",
            "proposal_digest": proposal.proposal_digest,
            "approval_id": str(approval_id),
            "action": proposal.action.value,
            "policy_digest": self.verifier.policy_digest,
            "canonical_checker": "synthetic-human-checker",
            "canonical_makers": sorted({self.verifier.canonical_identities[maker] for maker in makers}),
        }
        claims.update(claim_changes or {})
        content = (
            encoded(json.dumps({"alg": "EdDSA", "kid": "synthetic"}).encode())
            + "."
            + encoded(json.dumps(claims).encode())
        )
        evidence = content + "." + encoded(self.key.sign(content.encode("ascii")))
        request = AuthorityApprovalRequest(approval_id=approval_id, financial_evidence=evidence)
        self.record("signed_financial_evidence", request)
        return request

    def approval(self, proposal, *, tenant="tenant-a"):
        request = self.financial_request(proposal, tenant=tenant)
        approval = self.application.approve(self.principal("checker", tenant), proposal.proposal_id, request)
        self.record("approval", approval)
        return approval

    def decide(self, proposal, approval=None, *, tenant="tenant-a", request=None):
        approval = approval or self.approval(proposal, tenant=tenant)
        request = request or AuthorityApplyRequest(decision_id=uuid4(), approval_id=approval.approval_id)
        decision = self.application.apply(self.principal("checker", tenant), proposal.proposal_id, request)
        self.record("decision", decision)
        return decision

    def close(self):
        try:
            self.record("after_counts", self.counts())
        finally:
            self.ledger.close()
            self.jobs._engine.dispose()
            self.store.close()
            self.results._engine.dispose()
