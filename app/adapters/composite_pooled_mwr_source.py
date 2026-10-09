"""Deployment-owned source port. No default supplier qualification is invented."""

from dataclasses import dataclass

from app.models.composite_pooled_mwr import CompositePooledMWRRequest, PooledSourceBundle
from app.ports.composite_pooled_mwr import PooledMonetarySourceReader, PooledSourceAdmissionError


class UnavailablePooledMonetarySource:
    def read_population_scope(self, request: CompositePooledMWRRequest, *, tenant_id: str) -> tuple[str, ...]:
        raise PooledSourceAdmissionError(
            "SOURCE_AUTHORITY_UNAVAILABLE", "No qualified pooled monetary source reader is installed."
        )

    def read_pinned(self, request: CompositePooledMWRRequest, *, tenant_id: str) -> PooledSourceBundle:
        raise PooledSourceAdmissionError(
            "SOURCE_AUTHORITY_UNAVAILABLE", "No qualified pooled monetary source reader is installed."
        )


@dataclass(frozen=True)
class PooledMonetarySourceDeployment:
    reader: PooledMonetarySourceReader | None = None


_deployment = PooledMonetarySourceDeployment()


def install_pooled_monetary_source_deployment(deployment: PooledMonetarySourceDeployment) -> None:
    """Explicit server bootstrap only; this function has no HTTP configuration surface."""
    global _deployment
    if _deployment.reader is not None:
        raise RuntimeError("Pooled monetary source deployment is already installed.")
    if deployment.reader is None:
        raise ValueError("A deployment must supply its qualified source reader.")
    _deployment = deployment


def get_pooled_monetary_source_reader() -> PooledMonetarySourceReader:
    return _deployment.reader or UnavailablePooledMonetarySource()
