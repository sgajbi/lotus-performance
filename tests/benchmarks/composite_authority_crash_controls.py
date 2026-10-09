"""Abrupt death at actual authority writes/commit; launched inside reviewed test Job."""

import json
import os
import sys
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.adapters.composite_principal_credentials import CredentialTrust
from app.adapters.composite_result_authority.repository import CompositeAuthorityRepository
from app.adapters.composite_result_authority.verification import SignedFinancialAuthorityVerifier
from app.models.composite_result_authority import AuthorityApplyRequest
from app.services.async_result_store import AsyncResultStore
from app.services.composite_metadata_store import CompositeMetadataStore
from tests.composite_authority_helpers import install_test_authorities
from tests.composite_result_authority_helpers import SyntheticPrincipalAuthority


def main():
    packet = json.loads(Path(sys.argv[1]).read_text())
    boundary = packet["boundary"]
    if boundary not in {"decisions", "revisions", "scopes", "committed"}:
        raise ValueError("Unknown owning authority crash boundary")
    owner, results = CompositeMetadataStore(packet["database_url"]), AsyncResultStore(packet["database_url"])
    repository = CompositeAuthorityRepository(owner, results)
    from datetime import datetime

    from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal

    value = packet["principal"]
    value["capabilities"], value["portfolio_scope"] = (
        frozenset(value["capabilities"]),
        frozenset(value["portfolio_scope"]),
    )
    principal = VerifiedCompositePrincipal(**value)
    source_authorities = MonkeyPatch()
    install_test_authorities(source_authorities, packet["source_authority_packets"])
    proposal, approval, evidence, checker = repository.approval_material(principal, packet["request"]["approval_id"])
    verifier = SignedFinancialAuthorityVerifier(
        CredentialTrust(**packet["trust"]),
        SyntheticPrincipalAuthority(),
        packet["policy_digest"],
        packet["canonical_identities"],
        frozenset({"checker"}),
    )
    now = datetime.fromisoformat(packet["now"])
    verification = verifier.verify(
        proposal=proposal,
        approval_id=str(approval.approval_id),
        financial_evidence=evidence,
        checker=checker,
        actor=principal,
        now=now,
    )

    def crash(*args):
        print("reached_actual_authority_boundary=" + boundary, flush=True)
        os._exit(73)

    if boundary == "committed":
        event.listen(Session, "after_commit", crash)
    else:

        def write_boundary(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO composite_authority_" + boundary):
                crash()

        event.listen(owner._engine, "after_cursor_execute", write_boundary)
    repository.apply(
        principal, proposal.proposal_id, AuthorityApplyRequest.model_validate(packet["request"]), verification, now
    )
    raise AssertionError("Actual crash boundary was not reached")


if __name__ == "__main__":
    main()
