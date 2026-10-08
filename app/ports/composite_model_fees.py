"""Resolve immutable model-method evidence; the existing approval port owns trust."""

from dataclasses import dataclass
from typing import Any, Protocol

from app.models.composite_authority import EvidenceBinding
from app.models.composite_model_fee_profiles import CompositeModelFeeProfileReceipt
from app.models.composite_model_fees import CompositePeriodicModelFeeProfile
from app.ports.composite_external_evidence import UnavailableCompositeEvidence


@dataclass(frozen=True)
class CompositeModelFeeResolutionRequest:
    tenant_id: str
    composite_id: str
    binding: EvidenceBinding
    definition_content_hash: str
    membership_content_hash: str
    attestation_content_hash: str
    source_cut_id: str
    period_start: str
    period_end: str
    reporting_currency: str
    expected_members: tuple[str, ...]


class CompositeModelFeeResolutionPort(Protocol):
    def resolve(self, request: CompositeModelFeeResolutionRequest) -> dict[str, Any] | UnavailableCompositeEvidence: ...


class CompositeModelFeeProfileRepository(Protocol):
    def publish_model_fee_profile(
        self, profile: CompositePeriodicModelFeeProfile, *, tenant_id: str, actor_id: str
    ) -> CompositeModelFeeProfileReceipt: ...

    def get_model_fee_profile(
        self, *, tenant_id: str, profile_id: str, revision: str
    ) -> CompositeModelFeeProfileReceipt | None: ...

    def resolve_model_fee_profile(
        self, request: CompositeModelFeeResolutionRequest
    ) -> CompositeModelFeeProfileReceipt | None: ...


def model_fee_profile_repository() -> CompositeModelFeeProfileRepository:
    from app.services.composite_metadata_store import composite_metadata_store

    return composite_metadata_store


class UnavailableCompositeModelFeeSource:
    def resolve(self, request: CompositeModelFeeResolutionRequest) -> UnavailableCompositeEvidence:
        return UnavailableCompositeEvidence()


def composite_model_fee_resolver() -> CompositeModelFeeResolutionPort:
    from app.core.config import get_settings

    if get_settings().COMPOSITE_MODEL_FEE_SOURCE_MODE == "LOCAL_CATALOG":
        from app.adapters.composite_model_fee_profile_source import RetainedCompositeModelFeeSource

        return RetainedCompositeModelFeeSource(model_fee_profile_repository())
    return UnavailableCompositeModelFeeSource()
