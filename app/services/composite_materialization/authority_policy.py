"""Independent v2 payload, interval and approval-binding admission.

This checks content; provider/key qualification is a separate injected port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from app.models.composite_authority import AuthoritySelection, ManageCompositeDefinitionV2, authority_digest
from app.models.composite_materialization import CompositeMaterializationCommand
from app.ports import composite_external_evidence as approval_ports
from core.errors import APIUnprocessableEntityError


def authority_refusal(code: str) -> APIUnprocessableEntityError:
    return APIUnprocessableEntityError(detail="Pinned composite authority failed admission.", error_code=code)


@dataclass(frozen=True)
class ProviderTrustRequest:
    tenant_id: str
    provider_id: str
    registry_revision: str
    registry_digest: str
    source_product: str
    effective_from: str
    effective_to: str


@dataclass(frozen=True)
class ProviderTrustResolution:
    posture: Literal["UNAVAILABLE", "SYNTHETIC_TEST_ONLY"]
    reason_code: str
    registration_digest: str | None = None


class CompositeProviderTrustPort(Protocol):
    def resolve(self, request: ProviderTrustRequest) -> ProviderTrustResolution: ...


class UnavailableProviderTrustResolver:
    def resolve(self, request: ProviderTrustRequest) -> ProviderTrustResolution:
        return ProviderTrustResolution("UNAVAILABLE", "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")


def provider_trust_resolver() -> CompositeProviderTrustPort:
    """Production has no qualified resolver. Owning tests inject a dependency."""
    return UnavailableProviderTrustResolver()


def verify_definition_digests(definition: ManageCompositeDefinitionV2) -> None:
    wire = definition.model_dump(mode="json")
    profile = definition.source_authority
    if authority_digest(profile.payload.model_dump(mode="json")) != profile.profile_digest:
        raise authority_refusal("COMPOSITE_PROFILE_DIGEST_MISMATCH")
    business = {
        key: value
        for key, value in wire.items()
        if key not in {"authority_approval", "definition_payload_digest", "content_hash"}
    }
    if authority_digest(business) != definition.definition_payload_digest:
        raise authority_refusal("COMPOSITE_DEFINITION_PAYLOAD_DIGEST_MISMATCH")
    final_payload = {key: value for key, value in wire.items() if key != "content_hash"}
    if authority_digest(final_payload) != definition.content_hash:
        raise authority_refusal("COMPOSITE_SOURCE_HASH_MISMATCH")
    _verify_approval_binding(definition)


def _verify_approval_binding(definition: ManageCompositeDefinitionV2) -> None:
    payload = definition.source_authority.payload
    claims = definition.authority_approval.claims
    if claims.approving_identity == definition.created_by:
        raise authority_refusal("COMPOSITE_AUTHORITY_SELF_APPROVAL_FORBIDDEN")
    if definition.inception_date > payload.effective_from or (
        definition.termination_date is not None and definition.termination_date < payload.effective_to
    ):
        raise authority_refusal("COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH")
    actual = (
        claims.tenant_id,
        claims.composite_id,
        claims.definition_version,
        claims.profile_id,
        claims.profile_revision,
        claims.profile_digest,
        claims.definition_payload_digest,
        claims.effective_from,
        claims.effective_to,
        claims.eligibility_evidence_digest,
        claims.method_evidence_digest,
    )
    expected = (
        definition.tenant_id,
        definition.composite_id,
        definition.definition_version,
        payload.profile_id,
        payload.profile_revision,
        definition.source_authority.profile_digest,
        definition.definition_payload_digest,
        payload.effective_from,
        payload.effective_to,
        payload.eligibility_evaluation_binding.digest,
        payload.return_method_binding.digest,
    )
    if actual != expected or (payload.tenant_id, payload.composite_id) != (
        definition.tenant_id,
        definition.composite_id,
    ):
        raise authority_refusal("COMPOSITE_APPROVAL_BINDING_MISMATCH")


def selection_for_window(
    definition: ManageCompositeDefinitionV2,
    *,
    member_id: str,
    fact: str,
    period_start: date,
    period_end: date,
) -> AuthoritySelection:
    selections = [
        s
        for s in definition.source_authority.payload.selections
        if _selection_intersects(s, member_id, fact, period_start, period_end)
    ]
    selections.sort(key=lambda item: item.effective_from)
    _verify_adjacent_windows(selections)
    if (
        not selections
        or date.fromisoformat(selections[0].effective_from) > period_start
        or (date.fromisoformat(selections[-1].effective_to) < period_end)
    ):
        raise authority_refusal("COMPOSITE_ECONOMIC_AUTHORITY_GAP")
    if len(selections) > 1:
        raise authority_refusal("COMPOSITE_AUTHORITY_TRANSITION_REQUIRES_SPLIT_PERIOD")
    return selections[0]


def _selection_intersects(selection, member_id, fact, period_start, period_end):
    return (
        member_id in selection.member_ids
        and selection.fact == fact
        and date.fromisoformat(selection.effective_from) <= period_end
        and date.fromisoformat(selection.effective_to) >= period_start
    )


def admit_authority_profile(
    definition: ManageCompositeDefinitionV2,
    *,
    command: CompositeMaterializationCommand,
    tenant_id: str,
    expected_members: list[str],
    universe_digest: str,
    published_eligibility: approval_ports.PublishedEligibilityEvidence | None = None,
) -> None:
    verify_definition_digests(definition)
    payload = definition.source_authority.payload
    if (payload.tenant_id, payload.composite_id) != (tenant_id, command.composite_id):
        raise authority_refusal("COMPOSITE_SOURCE_SCOPE_MISMATCH")
    if date.fromisoformat(payload.effective_from) > command.period_start or (
        date.fromisoformat(payload.effective_to) < command.period_end
    ):
        raise authority_refusal("COMPOSITE_PROFILE_WINDOW_MISMATCH")
    members = {member.member_id: member for member in payload.member_identities}
    providers = {provider.provider_id: provider for provider in payload.providers}
    if set(members) != set(expected_members):
        raise authority_refusal("COMPOSITE_AUTHORITY_UNIVERSE_MISMATCH")
    _verify_selections(definition, command, members, providers)
    if definition.authority_approval.evidence_kind == "INSTITUTIONAL_ATTESTATION_REFERENCE":
        raise authority_refusal("COMPOSITE_INSTITUTIONAL_AUTHORITY_UNAVAILABLE")
    _verify_registrations(payload, providers, tenant_id)
    _verify_independent_approvals(definition, command, universe_digest, expected_members, published_eligibility)


def _verify_registrations(payload, providers, tenant_id):
    resolver = provider_trust_resolver()
    for selection in payload.selections:
        provider = providers[selection.provider_id]
        resolution = resolver.resolve(
            ProviderTrustRequest(
                tenant_id,
                provider.provider_id,
                provider.registry_revision,
                provider.registry_digest,
                selection.source_product,
                selection.effective_from,
                selection.effective_to,
            )
        )
        if resolution.posture != "SYNTHETIC_TEST_ONLY" or resolution.registration_digest != provider.registry_digest:
            raise authority_refusal("COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")


def _verify_independent_approvals(
    definition, command, universe_digest, expected_members, published_eligibility=None
) -> None:
    payload = definition.source_authority.payload
    if payload.eligibility_evaluation_binding.product_name == "CompositeSubjectEvaluationApproval":
        _verify_lifecycle_approvals(published_eligibility)
        return
    checks = (
        (
            "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE",
            payload.return_method_binding,
            approval_ports.authority_approval_verifier,
            "COMPOSITE_AUTHORITY_APPROVAL_UNAVAILABLE",
        ),
        (
            "ELIGIBILITY_POLICY_EVALUATION",
            payload.eligibility_evaluation_binding,
            approval_ports.eligibility_approval_verifier,
            "COMPOSITE_ELIGIBILITY_APPROVAL_UNAVAILABLE",
        ),
        (
            "RETURN_METHOD_CALENDAR",
            payload.return_method_binding,
            approval_ports.method_approval_verifier,
            "COMPOSITE_METHOD_APPROVAL_UNAVAILABLE",
        ),
    )
    for purpose, binding, factory, code in checks:
        request = approval_ports.CompositeApprovalRequest(
            purpose,
            definition.tenant_id,
            definition.composite_id,
            definition.definition_version,
            binding,
            payload.effective_from,
            payload.effective_to,
            definition,
            command,
            universe_digest,
            tuple(sorted(expected_members)),
        )
        if not factory().verify(request):
            raise authority_refusal(code)


def _verify_lifecycle_approvals(published_eligibility) -> None:
    if not isinstance(published_eligibility, approval_ports.PublishedEligibilityEvidence):
        raise authority_refusal("COMPOSITE_ELIGIBILITY_PUBLISHED_CUSTODY_UNAVAILABLE")
    finalization = published_eligibility.receipt.finalization
    proposal = finalization.evaluation_approval.proposal
    receipts = [
        proposal.policy_approval.verification,
        finalization.evaluation_approval.verification,
        *finalization.verifications,
    ]
    verifier = approval_ports.composite_receipt_verifier()
    for receipt in receipts:
        result = verifier.verify(receipt.request.model_copy(deep=True))
        if not isinstance(result, approval_ports.VerifiedCompositeEvidence) or result.expectation is None:
            raise authority_refusal("COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE")
        _admit_lifecycle_verification(receipt, result)


def _admit_lifecycle_verification(receipt, result) -> None:
    if result.expectation.request != receipt.request:
        raise authority_refusal("COMPOSITE_RECEIPT_VERIFICATION_REQUEST_MISMATCH")
    try:
        verified = approval_ports.admit_verified_receipt(result.expectation, result, allow_synthetic=True)
    except ValueError as exc:
        raise authority_refusal(str(exc)) from exc
    if verified != receipt:
        raise authority_refusal("COMPOSITE_RECEIPT_VERIFICATION_ARTIFACT_MISMATCH")


def _verify_selections(definition, command, members, providers) -> None:
    payload = definition.source_authority.payload
    _verify_provider_owners(providers)
    _verify_member_kinds(members, providers)
    for selection in payload.selections:
        _verify_selection_scope(selection, payload, command, members, providers)
    _verify_authority_mode(payload, providers)
    required = {"MEMBER_RETURN", "BEGINNING_ASSETS"}
    required.update(s.fact for s in payload.selections if s.fact in {"ENDING_ASSETS", "BENCHMARK_RETURN"})
    for member in members:
        for fact in sorted(required):
            _verify_full_coverage(definition, command, member, fact)


def _verify_authority_mode(payload, providers):
    external_kinds = {
        providers[s.provider_id].source_kind == "EXTERNAL_PROVIDER"
        for s in payload.selections
        if s.fact != "BENCHMARK_RETURN"
    }
    expected_kinds = {"INTERNAL": {False}, "EXTERNAL": {True}, "HYBRID": {False, True}}
    if external_kinds != expected_kinds[payload.mode]:
        raise authority_refusal("COMPOSITE_AUTHORITY_MODE_MISMATCH")


def _verify_provider_owners(providers):
    for provider in providers.values():
        owner = {"LOTUS_CORE": "lotus-core", "LOTUS_PERFORMANCE": "lotus-performance"}.get(provider.source_kind)
        if owner is not None and provider.provider_id != owner:
            raise authority_refusal("COMPOSITE_AUTHORITY_INTERNAL_OWNER_MISMATCH")


def _verify_member_kinds(members, providers):
    for identity in members.values():
        if identity.provider_id not in providers:
            raise authority_refusal("COMPOSITE_AUTHORITY_PROVIDER_MISMATCH")
        external = providers[identity.provider_id].source_kind == "EXTERNAL_PROVIDER"
        if (identity.identity_kind == "EXTERNAL_MEMBER") != external:
            raise authority_refusal("COMPOSITE_AUTHORITY_MEMBER_KIND_MISMATCH")


def _verify_selection_scope(selection, payload, command, members, providers):
    if selection.provider_id not in providers or not set(selection.member_ids) <= set(members):
        raise authority_refusal("COMPOSITE_AUTHORITY_PROVIDER_MISMATCH")
    provider = providers[selection.provider_id]
    _verify_selection_kind(selection, provider, command)
    if selection.economic_authority != provider.provider_id:
        raise authority_refusal("COMPOSITE_ECONOMIC_AUTHORITY_MISMATCH")
    if selection.effective_from < payload.effective_from or selection.effective_to > payload.effective_to:
        raise authority_refusal("COMPOSITE_PROFILE_WINDOW_MISMATCH")
    _verify_selection_method(selection, payload)


def _verify_selection_method(selection, payload):
    if selection.fact == "MEMBER_RETURN":
        if selection.method_profile_binding != payload.return_method_binding:
            raise authority_refusal("COMPOSITE_METHOD_BINDING_MISMATCH")
    elif selection.method_profile_binding is not None:
        raise authority_refusal("COMPOSITE_AUTHORITY_METHOD_BINDING_UNEXPECTED")


def _verify_selection_kind(selection, provider, command):
    if provider.source_kind == "EXTERNAL_PROVIDER":
        return
    required_kind = "LOTUS_PERFORMANCE" if selection.fact == "MEMBER_RETURN" else "LOTUS_CORE"
    if provider.source_kind != required_kind:
        raise authority_refusal("COMPOSITE_AUTHORITY_FACT_KIND_MISMATCH")
    if selection.source_cut_id != command.source_cut_id:
        raise authority_refusal("COMPOSITE_SOURCE_REVISION_MISMATCH")


def _verify_full_coverage(definition, command, member, fact):
    payload = definition.source_authority.payload
    windows = sorted(
        (s for s in payload.selections if s.fact == fact and member in s.member_ids),
        key=lambda item: item.effective_from,
    )
    if not windows:
        raise authority_refusal("COMPOSITE_ECONOMIC_AUTHORITY_GAP")
    if (windows[0].effective_from, windows[-1].effective_to) != (payload.effective_from, payload.effective_to):
        raise authority_refusal("COMPOSITE_ECONOMIC_AUTHORITY_GAP")
    _verify_adjacent_windows(windows)
    selection_for_window(
        definition, member_id=member, fact=fact, period_start=command.period_start, period_end=command.period_end
    )


def _verify_adjacent_windows(windows):
    for previous, current in zip(windows, windows[1:]):
        delta = (date.fromisoformat(current.effective_from) - date.fromisoformat(previous.effective_to)).days
        if delta <= 0:
            raise authority_refusal("COMPOSITE_ECONOMIC_AUTHORITY_OVERLAP")
        if delta != 1:
            raise authority_refusal("COMPOSITE_ECONOMIC_AUTHORITY_GAP")
