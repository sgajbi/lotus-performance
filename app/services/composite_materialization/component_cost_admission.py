"""Admit original financial cost payloads independently of method publication."""

from copy import deepcopy

from app.models.composite_authority import EvidenceBinding, authority_digest
from app.models.composite_component_costs import CompositeGrossCostReceipt, CompositeGrossCostSource
from app.models.composite_eligibility_evidence import VerificationRequest
from app.models.composite_model_fees import model_fee_profile_json
from app.ports import composite_external_evidence as approvals
from app.ports import composite_model_fees as sources
from app.services.composite_materialization.authority_policy import _admit_lifecycle_verification
from core.errors import APIUnprocessableEntityError


def _refuse():
    raise APIUnprocessableEntityError(
        "Whole original gross-cost financial evidence is unavailable or incompatible.",
        error_code="COMPOSITE_GROSS_COST_SOURCE_REFUSED",
    )


def financial_verification_request(wire, request, definition_version):
    digest = authority_digest(wire.model_dump(mode="json"))
    return VerificationRequest(
        purpose="PROVIDER_REGISTRATION",
        source_product=wire.product_name,
        binding=EvidenceBinding(
            product_name=wire.product_name,
            product_version=wire.product_version,
            revision=wire.revision,
            digest=digest,
        ),
        claims_digest=digest,
        tenant_id=request.tenant_id,
        composite_id=request.composite_id,
        definition_version=definition_version,
        subject_content_hash=request.definition_content_hash,
        effective_from=request.period_start,
        effective_to=request.period_end,
    )


def admit_component_cost_source(source, command, profile, *, tenant_id, retained_wire=None):
    from app.services.composite_materialization.model_fee_source_admission import model_fee_resolution_request

    request = model_fee_resolution_request(source, command, tenant_id=tenant_id)
    raw = retained_wire if retained_wire is not None else sources.composite_gross_cost_resolver().resolve(request)
    if not isinstance(raw, dict):
        _refuse()
    try:
        model_fee_profile_json(raw)
        if retained_wire is not None:
            receipt = CompositeGrossCostReceipt.model_validate(deepcopy(raw))
            wire = receipt.source
        else:
            wire = CompositeGrossCostSource.model_validate(deepcopy(raw))
        _require_source_scope(wire, request, profile)
        verification_request = financial_verification_request(wire, request, source.definition.definition_version)
        verified, admitted = _verify_financial_producer(wire, verification_request)
        if retained_wire is None:
            receipt = CompositeGrossCostReceipt(source=wire, verification=admitted)
        else:
            _admit_lifecycle_verification(receipt.verification, verified)
        return receipt
    except (ValueError, TypeError, KeyError, RecursionError):
        _refuse()


def _verify_financial_producer(wire, request):
    verified = approvals.composite_receipt_verifier().verify(request)
    if not isinstance(verified, approvals.VerifiedCompositeEvidence) or verified.expectation is None:
        _refuse()
    # The independent verifier's configured issuer must be this financial producer.
    if verified.expectation.request != request or verified.expectation.issuer_id != wire.producer_id:
        _refuse()
    admitted = approvals.admit_verified_receipt(verified.expectation, verified, allow_synthetic=True)
    return verified, admitted


def _require_source_scope(wire, request, profile):
    if (
        wire.definition_content_hash,
        wire.membership_content_hash,
        wire.attestation_content_hash,
        wire.source_cut_id,
        wire.model_fee_binding,
    ) != (
        request.definition_content_hash,
        request.membership_content_hash,
        request.attestation_content_hash,
        request.source_cut_id,
        request.binding,
    ):
        _refuse()
    if tuple(item.evidence.scope.member_id for item in wire.members) != request.expected_members:
        _refuse()
    period = next(
        row
        for row in profile.periods
        if (row.period_start, row.period_end) == (request.period_start, request.period_end)
    )
    for member, entry in zip(wire.members, period.member_rates, strict=True):
        evidence, scope = member.evidence, member.evidence.scope
        if (
            scope.tenant_id,
            scope.composite_id,
            scope.member_id,
            scope.period_start,
            scope.period_end,
            scope.reporting_currency,
            scope.method_binding,
            scope.calendar_binding,
            scope.gross_receipt_digest,
            scope.reference_base,
            evidence.evidence_binding,
        ) != (
            request.tenant_id,
            request.composite_id,
            entry.member_id,
            request.period_start,
            request.period_end,
            request.reporting_currency,
            profile.method_binding,
            profile.calendar_binding,
            entry.gross_receipt_digest,
            entry.reference_base,
            entry.gross_component_evidence_binding,
        ):
            _refuse()


def require_component_costs_before_facts(admitted):
    if admitted.gross_cost_source is None:
        _refuse()
