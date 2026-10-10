"""Synthetic BF source and signed purpose evidence over real captured originals."""

import base64
import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.composite_result_authority.vector import captured_vector
from app.models.composite_attribution import AttributionApproval, AttributionMember, AttributionMemberGroup
from app.models.composite_authority import authority_digest
from app.ports.composite_attribution import AttributionAdmissionError
from tests.composite_attribution_helpers import controlled_financial_case, seal
from tests.composite_authority_window_helpers import capture_windows, materialize_window


def capture_or17(fixture, monkeypatch, *, tenant="tenant-a", corrected=False):
    from tests import composite_authority_window_helpers, composite_materialization_helpers

    def figures(member, *, corrected=False):
        return Decimal({"A": "100", "B": "200", "C": "300"}[member]), Decimal(".068")

    monkeypatch.setattr(composite_materialization_helpers, "controlled_member_figures", figures)
    monkeypatch.setattr(composite_authority_window_helpers, "controlled_member_figures", figures)
    command = materialize_window(fixture, date(2026, 1, 5), date(2026, 1, 5), tenant=tenant, corrected=corrected)
    fixture.jobs.mark_complete(
        command.calculation_id, response_payload={"fixture_materialization": "complete"}, worker_id="worker-a"
    )
    candidate = capture_windows(fixture, [command], tenant=tenant)
    assert float(candidate["response"]["periods"][0]["return_value"]) == 0.068
    with fixture.store._session() as session:
        vector = captured_vector(session, fixture.principal("maker", tenant), UUID(candidate["candidate_id"]))
    request, bundle, *_ = controlled_financial_case()
    request = request.model_copy(
        update={
            "candidate_id": UUID(candidate["candidate_id"]),
            "composite_id": "COMPOSITE",
            "period_start": command.period_start,
            "period_end": command.period_end,
            "return_view": "NET_ACTUAL",
        }
    )
    period = candidate["response"]["periods"][0]
    members = tuple(
        AttributionMember(
            portfolio_id=row["portfolio_id"],
            status="INCLUDED",
            effective_from=command.period_start,
            effective_to=command.period_end,
            reason="actual-retained-included",
            composite_weight=row["beginning_asset_weight"],
            actual_return=row["return_value"],
            source_row_id=row["portfolio_id"] + "-member",
        )
        for row in period["member_contributions"]
    )
    groups = tuple(
        AttributionMemberGroup(
            portfolio_id=member.portfolio_id,
            group_id=group.group_id,
            member_weight=group.portfolio_weight,
            actual_return=group.portfolio_return,
            source_row_id=member.portfolio_id + "-" + group.group_id,
        )
        for member in members
        for group in bundle.groups
    )
    bundle = bundle.model_copy(
        update={
            "policy": bundle.policy.model_copy(
                update={"return_view": "NET_ACTUAL", "fee_basis": "actual-net-source-basis"}
            ),
            "tenant_id": tenant,
            "composite_id": "COMPOSITE",
            "candidate_id": request.candidate_id,
            "original_response_digest": candidate["original_response_digest"],
            "vector_digest": vector.vector_digest,
            "membership_digest": command.membership_content_hash,
            "period_start": command.period_start,
            "period_end": command.period_end,
            "return_view": "NET_ACTUAL",
            "members": members,
            "member_groups": groups,
            "expected_portfolio_ids": tuple(member.portfolio_id for member in members),
        }
    )
    bundle, _ = seal(bundle)
    return request, bundle, candidate


class ControlledAttributionReader:
    def __init__(self, bundle):
        self.bundles = {bundle.source_manifest_id: bundle}
        self.metadata_reads, self.financial_reads = 0, 0
        self.available = True

    def _bundle(self, request, tenant_id):
        bundle = self.bundles.get(request.source_manifest_id)
        if not self.available or bundle is None or bundle.tenant_id != tenant_id:
            raise AttributionAdmissionError(
                "SOURCE_AUTHORITY_UNAVAILABLE", "Controlled historical source is unavailable."
            )
        return bundle

    def read_population_scope(self, request, *, tenant_id):
        self.metadata_reads += 1
        return self._bundle(request, tenant_id).expected_portfolio_ids

    def read_pinned(self, request, *, tenant_id):
        self.financial_reads += 1
        return self._bundle(request, tenant_id)


class SignedSyntheticBFVerifier:
    """An isolated synthetic issuer, never a production approval fallback."""

    def __init__(self, bundle):
        self.key = Ed25519PrivateKey.generate()
        self.evidence = {}
        self.authorize(bundle)

    def authorize(self, bundle, *, purpose="COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER"):
        claims = {
            "purpose": purpose,
            "bundle_digest": authority_digest(bundle.model_dump(mode="json")),
            "policy_digest": authority_digest(bundle.policy.model_dump(mode="json")),
            "canonical_maker": "synthetic-human-maker",
            "canonical_checker": "synthetic-human-checker",
            "qualification": "SYNTHETIC_NON_CERTIFYING",
        }
        payload = json.dumps(claims, sort_keys=True, separators=(",", ":"))
        wire = json.dumps({"payload": payload, "signature": base64.b64encode(self.key.sign(payload.encode())).decode()})
        self.evidence[claims["bundle_digest"]] = wire

    def verify(self, request, bundle):
        digest = authority_digest(bundle.model_dump(mode="json"))
        wire = self.evidence.get(digest)
        if wire is None:
            raise AttributionAdmissionError(
                "ATTRIBUTION_PURPOSE_AUTHORITY_UNAVAILABLE", "Synthetic exact-purpose evidence is absent."
            )
        packet = json.loads(wire)
        self.key.public_key().verify(base64.b64decode(packet["signature"]), packet["payload"].encode())
        claims = json.loads(packet["payload"])
        if claims["purpose"] != "COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER" or claims["bundle_digest"] != digest:
            raise AttributionAdmissionError(
                "ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT", "Signed evidence has another purpose or original."
            )
        return AttributionApproval(**claims, evidence_wire=wire, evidence_digest=authority_digest({"wire": wire}))
