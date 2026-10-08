"""Join exact source scope to independent verification before currency normalization."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, NoReturn

from pydantic import ValidationError

from app.models.composite_authority import ManageCompositeDefinitionV2, authority_digest
from app.models.composite_currency_normalization import CompositeFXNormalizationSource, CompositeFXVerificationReceipt
from app.ports import composite_currency_normalization as ports
from core.errors import APIUnprocessableEntityError


@dataclass(frozen=True)
class AdmittedCompositeFXSource:
    source: CompositeFXNormalizationSource
    source_wire: dict[str, Any]
    verification_receipt: CompositeFXVerificationReceipt


def _refuse(code: str) -> NoReturn:
    raise APIUnprocessableEntityError(
        detail="Pinned composite currency evidence is unavailable or incompatible.", error_code=code
    )


def verification_request_digest(request: ports.CompositeFXVerificationRequest) -> str:
    return authority_digest(
        {
            "resolution": {
                **asdict(request.resolution),
                "binding": request.resolution.binding.model_dump(mode="json"),
            },
            "source": request.source.model_dump(mode="json"),
            "source_digest": request.source_digest,
            "method_digest": request.method_digest,
        }
    )


def require_fx_normalization_route(definition) -> None:
    if isinstance(definition, ManageCompositeDefinitionV2) and definition.source_authority.payload.mode != "INTERNAL":
        _refuse("COMPOSITE_FX_AGGREGATE_METHOD_UNAVAILABLE")


def fx_resolution_for_command(command, *, tenant_id):
    if command.currency_normalization_binding is None:
        _refuse("COMPOSITE_FX_SOURCE_BINDING_REQUIRED")
    return ports.CompositeFXResolutionRequest(
        tenant_id=tenant_id,
        composite_id=command.composite_id,
        binding=command.currency_normalization_binding,
        definition_content_hash=command.definition_content_hash,
        membership_content_hash=command.membership_content_hash,
        attestation_content_hash=command.attestation_content_hash,
        source_cut_id=command.source_cut_id,
        period_start=str(command.period_start),
        period_end=str(command.period_end),
        reporting_currency=command.reporting_currency,
        return_view=str(command.return_view),
        expected_members=tuple(row.portfolio_id for row in command.member_calculations),
    )


def admit_composite_fx_source(
    request: ports.CompositeFXResolutionRequest, *, resolver=None, verifier=None, retained_wire=None
) -> AdmittedCompositeFXSource:
    raw = (
        retained_wire
        if retained_wire is not None
        else (resolver or ports.composite_fx_source_resolver()).resolve(request)
    )
    if not isinstance(raw, dict):
        _refuse("COMPOSITE_FX_SOURCE_UNAVAILABLE")
    raw = deepcopy(raw)
    source_digest = authority_digest(raw)
    if source_digest != request.binding.digest:
        _refuse("COMPOSITE_FX_SOURCE_DIGEST_MISMATCH")
    try:
        source = CompositeFXNormalizationSource.model_validate(raw)
    except ValidationError:
        _refuse("COMPOSITE_FX_SOURCE_WIRE_REFUSED")
    _require_source_scope(request, source)
    verification_request = ports.CompositeFXVerificationRequest(
        resolution=request,
        source=source,
        source_digest=source_digest,
        method_digest=authority_digest(source.method.model_dump(mode="json")),
    )
    verified = (verifier or ports.composite_fx_receipt_verifier()).verify(verification_request)
    if not isinstance(verified, ports.VerifiedCompositeFXEvidence):
        _refuse("COMPOSITE_FX_INDEPENDENT_VERIFICATION_UNAVAILABLE")
    _require_verified_receipt(verification_request, verified)
    return AdmittedCompositeFXSource(source=source, source_wire=raw, verification_receipt=verified.verification_receipt)


def require_composite_native_currency(admitted, definition):
    if admitted.source.composite_native_currency != definition.reporting_currency:
        _refuse("COMPOSITE_FX_NATIVE_CURRENCY_MISMATCH")


def _require_source_scope(request, source):
    if (
        source.product_name,
        source.product_version,
        source.revision,
        source.tenant_id,
        source.composite_id,
        source.definition_content_hash,
        source.membership_content_hash,
        source.attestation_content_hash,
        source.source_cut_id,
        source.period_start,
        source.period_end,
        source.reporting_currency,
        source.return_view,
        tuple(member.member_id for member in source.members),
    ) != (
        request.binding.product_name,
        request.binding.product_version,
        request.binding.revision,
        request.tenant_id,
        request.composite_id,
        request.definition_content_hash,
        request.membership_content_hash,
        request.attestation_content_hash,
        request.source_cut_id,
        request.period_start,
        request.period_end,
        request.reporting_currency,
        request.return_view,
        request.expected_members,
    ):
        _refuse("COMPOSITE_FX_SOURCE_SCOPE_MISMATCH")


def _require_verified_receipt(request, verified):
    expectation, receipt = verified.expectation, verified.verification_receipt
    if not isinstance(expectation, ports.CompositeFXVerificationExpectation) or expectation.request != request:
        _refuse("COMPOSITE_FX_VERIFIER_EXPECTATION_MISMATCH")
    if not isinstance(receipt, CompositeFXVerificationReceipt):
        _refuse("COMPOSITE_FX_VERIFICATION_RECEIPT_REFUSED")
    try:
        CompositeFXVerificationReceipt.model_validate(receipt.model_dump(mode="json"))
    except ValidationError:
        _refuse("COMPOSITE_FX_VERIFICATION_RECEIPT_REFUSED")
    if (
        (
            receipt.tenant_id,
            receipt.composite_id,
            receipt.verifier_id,
            receipt.issuer_id,
            receipt.artifact_revision,
            receipt.artifact_digest,
            receipt.source_digest,
            receipt.method_digest,
            receipt.request_digest,
        )
        != (
            request.resolution.tenant_id,
            request.resolution.composite_id,
            expectation.verifier_id,
            expectation.issuer_id,
            expectation.artifact_revision,
            expectation.artifact_digest,
            request.source_digest,
            request.method_digest,
            verification_request_digest(request),
        )
        or not expectation.verifier_id
        or not expectation.issuer_id
    ):
        _refuse("COMPOSITE_FX_VERIFICATION_RECEIPT_REFUSED")
