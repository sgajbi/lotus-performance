"""Annual enrollment applicability, distinct from monthly financial custody."""

from app.models.composite_controlled_annual_authority import ControlledAnnualDefinitionV4
from app.models.composite_controlled_annual_basis import year_rules_for_window
from app.models.composite_controlled_annual_evidence import ControlledAnnualFinalizationReceipt
from app.models.composite_eligibility_evidence import _month_window
from app.ports import composite_controlled_annual_evidence as year_ports
from app.services.composite_materialization.authority_policy import (
    ProviderTrustRequest,
    authority_refusal,
    provider_trust_resolver,
)


def admit_annual_authority(definition, command, expected_members, published_eligibility) -> None:
    payload = definition.source_authority.payload
    proof = definition.authority_approval.verification
    if published_eligibility is None or not isinstance(
        published_eligibility.receipt, ControlledAnnualFinalizationReceipt
    ):
        raise authority_refusal("COMPOSITE_YEAR_EVALUATED_PUBLICATION_REQUIRED")
    members = publication_member_identities(definition, command)
    if [item.member_id for item in members] != expected_members:
        raise authority_refusal("COMPOSITE_AUTHORITY_UNIVERSE_MISMATCH")
    _admit_publication_window(published_eligibility.receipt.finalization.subject, command, members)
    try:
        result = year_ports.controlled_year_verifier().verify(proof.request.model_copy(deep=True))
        year_ports.admit_controlled_year_verification(proof, result)
    except ValueError as exc:
        raise authority_refusal(str(exc)) from exc
    _annual_registrations(payload)
    from app.services.composite_materialization.authority_policy import _verify_lifecycle_approvals

    _verify_lifecycle_approvals(published_eligibility)


def _annual_registrations(payload) -> None:
    providers = {item.provider_id: item for item in payload.providers}
    resolver = provider_trust_resolver()
    for rule in payload.authority_rules:
        provider = providers[rule.provider_id]
        request = ProviderTrustRequest(
            payload.tenant_id,
            provider.provider_id,
            provider.registry_revision,
            provider.registry_digest,
            rule.source_product,
            rule.effective_from,
            rule.effective_to,
        )
        result = resolver.resolve(request)
        if result.posture != "SYNTHETIC_TEST_ONLY" or result.registration_digest != provider.registry_digest:
            raise authority_refusal("COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")


def require_annual_internal_bindings(definition: ControlledAnnualDefinitionV4, command, reference, evidence, facts):
    """Require actual native receipt products; yearly enrollment supplies no values."""
    basis = definition.source_authority.payload.basis_mapping.basis
    for fact in facts:
        try:
            rules = year_rules_for_window(
                basis, reference.portfolio_id, fact, str(command.period_start), str(command.period_end)
            )
        except ValueError as exc:
            raise authority_refusal(str(exc)) from exc
        actual = (
            ("CompositeMemberSourceEvidence", evidence.contract_version)
            if fact == "MEMBER_RETURN"
            else (evidence.source_assets.source_product, evidence.source_assets.contract_version)
        )
        if any((rule.source_product, rule.source_contract_version) != actual for rule in rules):
            raise authority_refusal("COMPOSITE_YEAR_NATIVE_ENROLLMENT_MISMATCH")


def publication_member_identities(definition, command):
    """Project a stable period population; this supplies no eligibility publication authority."""
    if not isinstance(definition, ControlledAnnualDefinitionV4):
        return definition.source_authority.payload.member_identities
    candidates = _annual_period_candidates(definition, command)
    members = candidates[0].members
    if any(candidate.members != members for candidate in candidates[1:]):
        raise authority_refusal("COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH")
    return members


def _annual_period_candidates(definition, command):
    start, end = str(command.period_start), str(command.period_end)
    _require_annual_profile_window(definition.source_authority.payload, command)
    months = [
        f"{command.period_start.year}-{month:02d}"
        for month in range(command.period_start.month, command.period_end.month + 1)
    ]
    candidates = [
        item
        for item in definition.authority_approval.verification.candidate_evidence
        if months[0] <= item.month <= months[-1]
    ]
    if [item.month for item in candidates] != months:
        raise authority_refusal("COMPOSITE_YEAR_MONTH_VECTOR_MISMATCH")
    for candidate in candidates:
        _require_candidate_window(candidate, start, end)
    return candidates


def _require_annual_profile_window(payload, command):
    if command.period_start.year != command.period_end.year:
        raise authority_refusal("COMPOSITE_PROFILE_WINDOW_MISMATCH")
    if not (payload.effective_from <= str(command.period_start) <= str(command.period_end) <= payload.effective_to):
        raise authority_refusal("COMPOSITE_PROFILE_WINDOW_MISMATCH")


def _require_candidate_window(candidate, start, end):
    first, last = _month_window(candidate.month)
    if candidate.coverage_from > max(start, first) or candidate.coverage_to < min(end, last):
        raise authority_refusal("COMPOSITE_UNIVERSE_COVERAGE_MISMATCH")


def _admit_publication_window(subject, command, members):
    start, end = str(command.period_start), str(command.period_end)
    if start[:7] != subject.month or end[:7] != subject.month:
        raise authority_refusal("COMPOSITE_ELIGIBILITY_RESOLUTION_WINDOW_MISMATCH")
    if not (subject.universe.coverage_from <= start <= end <= subject.universe.coverage_to):
        raise authority_refusal("COMPOSITE_ELIGIBILITY_RESOLUTION_WINDOW_MISMATCH")
    if subject.universe.members != members:
        raise authority_refusal("COMPOSITE_ELIGIBILITY_PUBLICATION_MEMBER_MISMATCH")
