"""Shared typed lifecycle method guard; not a qualified model-profile supplier."""

from types import SimpleNamespace

import pytest

from app.ports import composite_external_evidence as approvals
from app.services.composite_materialization.model_fee_source_admission import _require_published_method_approval
from core.errors import APIUnprocessableEntityError
from tests.composite_eligibility_helpers import rehash_lifecycle, resolved_fixture, verification_expectation


def lifecycle_case():
    _, published = resolved_fixture()
    receipt = next(
        row for row in published.receipt.finalization.verifications if row.request.purpose == "RETURN_METHOD_CALENDAR"
    )
    source = SimpleNamespace(published_eligibility=published)
    request = SimpleNamespace(binding=receipt.request.binding)
    return source, request, receipt


def install_frozen_receipt(monkeypatch, receipt, *, altered=None):
    expectation = verification_expectation(receipt)

    class FrozenVerifier:
        def verify(self, request):
            if request != receipt.request:
                return approvals.UnavailableCompositeEvidence()
            return approvals.VerifiedCompositeEvidence(altered or receipt, expectation)

    monkeypatch.setattr(approvals, "composite_receipt_verifier", FrozenVerifier)


def test_specific_published_method_receipt_requires_and_accepts_independent_exact_verification(monkeypatch):
    source, request, receipt = lifecycle_case()
    install_frozen_receipt(monkeypatch, receipt)
    _require_published_method_approval(source, request)


@pytest.mark.parametrize("fault", ["eligibility-only", "duplicate", "different-binding", "different-claims"])
def test_published_method_cannot_be_supplied_by_wrong_purpose_or_scope(monkeypatch, fault):
    source, request, receipt = lifecycle_case()
    install_frozen_receipt(monkeypatch, receipt)
    finalization = source.published_eligibility.receipt.finalization
    if fault == "eligibility-only":
        finalization.verifications = [
            row for row in finalization.verifications if row.request.purpose != "RETURN_METHOD_CALENDAR"
        ]
    elif fault == "duplicate":
        finalization.verifications.append(receipt.model_copy(deep=True))
    elif fault == "different-binding":
        request.binding = request.binding.model_copy(update={"digest": "sha256:" + "f" * 64})
    else:
        receipt.request.claims_digest = "sha256:" + "f" * 64
    with pytest.raises(APIUnprocessableEntityError) as refused:
        _require_published_method_approval(source, request)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"


def test_published_method_with_unavailable_default_verifier_refuses():
    source, request, _ = lifecycle_case()
    with pytest.raises(APIUnprocessableEntityError) as refused:
        _require_published_method_approval(source, request)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"


def test_rehashed_receipt_identity_cannot_replace_independent_verifier_record(monkeypatch):
    source, request, receipt = lifecycle_case()
    altered_wire = receipt.model_dump(mode="json")
    altered_wire["issuer_id"] = "caller-selected-issuer"
    rehash_lifecycle(altered_wire)
    altered = type(receipt).model_validate(altered_wire)
    install_frozen_receipt(monkeypatch, receipt, altered=altered)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        _require_published_method_approval(source, request)
    assert refused.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_ARTIFACT_MISMATCH"
