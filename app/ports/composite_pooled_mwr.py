"""Owner-authorized source acquisition and immutable pooled input custody ports."""

from typing import Protocol

from app.models.composite_pooled_mwr import CompositePooledMWRRequest, PooledSourceBundle


class PooledSourceAdmissionError(Exception):
    def __init__(self, code: str, message: str, *, availability: str = "UNAVAILABLE"):
        super().__init__(message)
        self.code = code
        self.availability = availability


class PooledMonetarySourceReader(Protocol):
    """Implementations verify owner authority before returning original evidence.

    A public request reference, self-declared COMPLETE flag or digest is not
    authorization. Production readers require configured source-owner bindings;
    controlled readers must explicitly preserve synthetic qualification.
    """

    def read_pinned(self, request: CompositePooledMWRRequest, *, tenant_id: str) -> PooledSourceBundle: ...
