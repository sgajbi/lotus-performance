"""Pin complete periodic fee evidence to the existing independent method authority."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, NoReturn

from pydantic import ValidationError

from app.models.composite_authority import ManageCompositeDefinitionV2, authority_digest
from app.models.composite_eligibility_evidence import SubjectFinalizationReceipt
from app.models.composite_model_fees import CompositeModelFeePeriod, CompositePeriodicModelFeeProfile
from app.ports import composite_external_evidence as approvals
from app.ports import composite_model_fees as sources
from app.services.composite_materialization.authority_policy import _admit_lifecycle_verification, selection_for_window
from core.errors import APIError, APIUnprocessableEntityError


@dataclass(frozen=True)
class AdmittedCompositeModelFee:
    profile: CompositePeriodicModelFeeProfile
    period: CompositeModelFeePeriod
    source_wire: dict[str, Any]


def _refuse(code: str) -> NoReturn:
    raise APIUnprocessableEntityError(
        detail="Pinned composite model-fee evidence is unavailable or incompatible.", error_code=code
    )


def model_fee_resolution_request(source, command, *, tenant_id):
    definition = source.definition
    if command.model_fee_binding is None or str(command.return_view) != "NET_MODEL_FEE":
        _refuse("COMPOSITE_MODEL_FEE_BINDING_REQUIRED")
    if (
        not isinstance(definition, ManageCompositeDefinitionV2)
        or definition.source_authority.payload.mode != "INTERNAL"
    ):
        _refuse("COMPOSITE_MODEL_FEE_INTERNAL_METHOD_REQUIRED")
    if command.model_fee_binding != definition.source_authority.payload.return_method_binding:
        _refuse("COMPOSITE_MODEL_FEE_METHOD_BINDING_MISMATCH")
    if (
        definition.tenant_id,
        definition.composite_id,
        definition.content_hash,
        source.membership.content_hash,
        source.attestation.content_hash,
        source.membership.source_cut_id,
    ) != (
        tenant_id,
        command.composite_id,
        command.definition_content_hash,
        command.membership_content_hash,
        command.attestation_content_hash,
        command.source_cut_id,
    ):
        _refuse("COMPOSITE_MODEL_FEE_SOURCE_SCOPE_MISMATCH")
    _require_native_asset_selections(definition, source, command)
    return sources.CompositeModelFeeResolutionRequest(
        tenant_id,
        command.composite_id,
        command.model_fee_binding,
        command.definition_content_hash,
        command.membership_content_hash,
        command.attestation_content_hash,
        command.source_cut_id,
        str(command.period_start),
        str(command.period_end),
        command.reporting_currency,
        tuple(sorted(source.attestation.expected_portfolio_ids)),
    )


def _require_native_asset_selections(definition, source, command):
    # The first native-receipt profile retains both asset endpoints. Missing
    # authority must refuse at method admission, before a member write can
    # leave a failed job alongside misleading WAITING progress.
    try:
        for member in source.attestation.expected_portfolio_ids:
            for fact in ("MEMBER_RETURN", "BEGINNING_ASSETS", "ENDING_ASSETS"):
                selection_for_window(
                    definition,
                    member_id=member,
                    fact=fact,
                    period_start=command.period_start,
                    period_end=command.period_end,
                )
    except APIError:
        _refuse("COMPOSITE_MODEL_FEE_NATIVE_ASSET_AUTHORITY_REQUIRED")


def admit_model_fee_source(source, command, *, tenant_id, retained_wire=None, resolver=None):
    request = model_fee_resolution_request(source, command, tenant_id=tenant_id)
    raw = (
        retained_wire
        if retained_wire is not None
        else (resolver or sources.composite_model_fee_resolver()).resolve(request)
    )
    if not isinstance(raw, dict):
        _refuse("COMPOSITE_MODEL_FEE_SOURCE_UNAVAILABLE")
    raw = deepcopy(raw)
    try:
        digest = authority_digest(raw)
        profile = CompositePeriodicModelFeeProfile.model_validate(raw)
    except (ValidationError, ValueError, TypeError):
        _refuse("COMPOSITE_MODEL_FEE_SOURCE_WIRE_REFUSED")
    if digest != request.binding.digest:
        _refuse("COMPOSITE_MODEL_FEE_SOURCE_DIGEST_MISMATCH")
    period = _require_profile_scope(request, profile)
    _require_method_approval(source, command, request, raw)
    return AdmittedCompositeModelFee(profile, period, raw)


def _require_profile_scope(request, profile):
    if (
        profile.product_name,
        profile.product_version,
        profile.revision,
        profile.tenant_id,
        profile.composite_id,
        profile.reporting_currency,
    ) != (
        request.binding.product_name,
        request.binding.product_version,
        request.binding.revision,
        request.tenant_id,
        request.composite_id,
        request.reporting_currency,
    ):
        _refuse("COMPOSITE_MODEL_FEE_SOURCE_SCOPE_MISMATCH")
    periods = [
        row
        for row in profile.periods
        if (row.period_start, row.period_end) == (request.period_start, request.period_end)
    ]
    if len(periods) != 1:
        _refuse("COMPOSITE_MODEL_FEE_COMPLETE_PERIOD_REQUIRED")
    period = periods[0]
    if tuple(row.member_id for row in period.member_rates) != request.expected_members:
        _refuse("COMPOSITE_MODEL_FEE_MEMBER_COVERAGE_MISMATCH")
    return period


def _require_method_approval(source, command, request, raw):
    if source.published_eligibility is not None and isinstance(
        source.published_eligibility.receipt, SubjectFinalizationReceipt
    ):
        _require_published_method_approval(source, request)
        return
    definition = source.definition
    profile = definition.source_authority.payload
    universe_digest = next(
        row.content_hash
        for row in source.attestation.source_products
        if row.authority_scope == "AUTHORITATIVE_UNIVERSE"
    )
    approval_request = approvals.CompositeApprovalRequest(
        "RETURN_METHOD_CALENDAR",
        request.tenant_id,
        request.composite_id,
        definition.definition_version,
        request.binding,
        profile.effective_from,
        profile.effective_to,
        definition.model_copy(deep=True),
        command.model_copy(deep=True),
        universe_digest,
        request.expected_members,
        method_evidence_wire=deepcopy(raw),
        eligibility_evidence_wire=(
            source.published_eligibility.receipt.model_dump() if source.published_eligibility is not None else None
        ),
    )
    if approvals.method_approval_verifier().verify(approval_request) is not True:
        _refuse("COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE")


def _require_published_method_approval(source, request):
    receipt = source.published_eligibility.receipt
    if not isinstance(receipt, SubjectFinalizationReceipt):
        _refuse("COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE")
    finalization = receipt.finalization
    receipts = [row for row in finalization.verifications if row.request.purpose == "RETURN_METHOD_CALENDAR"]
    if len(receipts) != 1 or (receipts[0].request.binding, receipts[0].request.claims_digest) != (
        request.binding,
        request.binding.digest,
    ):
        _refuse("COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE")
    receipt = receipts[0]
    result = approvals.composite_receipt_verifier().verify(receipt.request.model_copy(deep=True))
    if not isinstance(result, approvals.VerifiedCompositeEvidence) or result.expectation is None:
        _refuse("COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE")
    _admit_lifecycle_verification(receipt, result)
