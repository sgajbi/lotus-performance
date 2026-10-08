"""Append-only canonical profile records through the existing composite store session."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm.exc import MultipleResultsFound

from app.adapters.composite_model_fee_profile_records import CompositeModelFeeProfileModel
from app.models.composite_authority import EvidenceBinding, authority_digest
from app.models.composite_model_fee_profiles import CompositeModelFeeProfileReceipt
from app.models.composite_model_fees import CompositePeriodicModelFeeProfile, model_fee_profile_json
from core.errors import APIConflictError, APIError


def _refuse_retained():
    raise APIError(
        status_code=503,
        detail="Retained model-fee profile custody conflicts with its immutable identity.",
        error_code="COMPOSITE_MODEL_FEE_PROFILE_RETAINED_EVIDENCE_REFUSED",
        retryable=False,
    )


def profile_record_receipt(row):
    try:
        profile = CompositePeriodicModelFeeProfile.model_validate_json(row.profile_json)
        digest = authority_digest(json.loads(row.profile_json))
        actual = (
            row.tenant_id,
            row.composite_id,
            row.profile_id,
            row.revision,
            row.product_name,
            row.product_version,
            row.content_digest,
        )
        expected = (
            profile.tenant_id,
            profile.composite_id,
            profile.profile_id,
            profile.revision,
            profile.product_name,
            profile.product_version,
            digest,
        )
        if actual != expected or row.profile_json != model_fee_profile_json(profile.model_dump(mode="json")):
            _refuse_retained()
        return CompositeModelFeeProfileReceipt(
            binding=EvidenceBinding(
                product_name=profile.product_name,
                product_version=profile.product_version,
                revision=profile.revision,
                digest=digest,
            ),
            profile=profile,
            published_by=row.published_by,
            published_at_utc=datetime.fromisoformat(row.published_at_utc),
        )
    except (ValueError, TypeError):
        _refuse_retained()


def publish_profile(session, profile, *, tenant_id, actor_id):
    if not actor_id or actor_id != actor_id.strip() or len(actor_id) > 128:
        raise APIError(
            status_code=400,
            detail="Profile publication requires an admitted nonblank original actor.",
            error_code="COMPOSITE_MODEL_FEE_PROFILE_ACTOR_REQUIRED",
        )
    profile = CompositePeriodicModelFeeProfile.model_validate(profile.model_dump(mode="json"))
    if profile.tenant_id != tenant_id:
        raise APIConflictError(
            "Method-profile tenant contradicts admitted authority.",
            error_code="COMPOSITE_MODEL_FEE_PROFILE_TENANT_MISMATCH",
        )
    canonical = model_fee_profile_json(profile.model_dump(mode="json"))
    digest = authority_digest(json.loads(canonical))
    identity = (tenant_id, profile.profile_id, profile.revision)
    existing = session.get(CompositeModelFeeProfileModel, identity)
    if existing is not None:
        return _same_content_receipt(existing, canonical, digest)
    row = CompositeModelFeeProfileModel(
        tenant_id=tenant_id,
        profile_id=profile.profile_id,
        revision=profile.revision,
        composite_id=profile.composite_id,
        product_name=profile.product_name,
        product_version=profile.product_version,
        content_digest=digest,
        profile_json=canonical,
        published_by=actor_id,
        published_at_utc=datetime.now(UTC).isoformat(),
    )
    # The identity/unique binding constraints serialize simultaneous inserts.
    # A savepoint permits inspecting the committed winner without rolling back
    # the surrounding existing store session's transaction.
    from sqlalchemy.exc import IntegrityError

    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        winner = session.get(CompositeModelFeeProfileModel, identity, populate_existing=True)
        if winner is None:
            _refuse_retained()
        return _same_content_receipt(winner, canonical, digest)
    return profile_record_receipt(row)


def _same_content_receipt(row, canonical, digest):
    receipt = profile_record_receipt(row)
    if row.profile_json != canonical or row.content_digest != digest:
        raise APIConflictError(
            "Published method-profile identity already has different immutable content.",
            error_code="COMPOSITE_MODEL_FEE_PROFILE_CONTENT_CONFLICT",
        )
    return receipt


def read_profile(session, *, tenant_id, profile_id, revision):
    row = session.get(CompositeModelFeeProfileModel, (tenant_id, profile_id, revision))
    return profile_record_receipt(row) if row is not None else None


def resolve_profile(session, request):
    query = select(CompositeModelFeeProfileModel).where(
        CompositeModelFeeProfileModel.tenant_id == request.tenant_id,
        CompositeModelFeeProfileModel.composite_id == request.composite_id,
        CompositeModelFeeProfileModel.product_name == request.binding.product_name,
        CompositeModelFeeProfileModel.product_version == request.binding.product_version,
        CompositeModelFeeProfileModel.revision == request.binding.revision,
        CompositeModelFeeProfileModel.content_digest == request.binding.digest,
    )
    try:
        row = session.scalars(query).one_or_none()
    except MultipleResultsFound:
        _refuse_retained()
    return profile_record_receipt(row) if row is not None else None
