"""Separate source custody and purpose-specific method authority boundaries."""

from typing import Protocol

from app.models.composite_attribution import AttributionApproval, AttributionSourceBundle, CompositeAttributionRequest


class AttributionAdmissionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CompositeAttributionSource(Protocol):
    def read_population_scope(self, request: CompositeAttributionRequest, *, tenant_id: str) -> tuple[str, ...]: ...

    def read_pinned(self, request: CompositeAttributionRequest, *, tenant_id: str) -> AttributionSourceBundle: ...


class CompositeAttributionAuthority(Protocol):
    """Verify an exact BF purpose, independent canonical actors and original evidence.

    Source reader possession, technical credentials, source COMPLETE flags and
    TWR selection approvals cannot establish this financial purpose.
    """

    def verify(self, request: CompositeAttributionRequest, bundle: AttributionSourceBundle) -> AttributionApproval: ...
