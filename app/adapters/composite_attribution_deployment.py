"""Explicit server-owned binding; production has no invented supplier approval."""

from dataclasses import dataclass

from app.ports.composite_attribution import (
    AttributionAdmissionError,
    CompositeAttributionAuthority,
    CompositeAttributionSource,
)


class UnavailableAttributionSource:
    def read_population_scope(self, request, *, tenant_id):
        raise AttributionAdmissionError(
            "SOURCE_AUTHORITY_UNAVAILABLE", "Historical Composite attribution source is unavailable."
        )

    def read_pinned(self, request, *, tenant_id):
        raise AttributionAdmissionError(
            "SOURCE_AUTHORITY_UNAVAILABLE", "Historical Composite attribution source is unavailable."
        )


class UnavailableAttributionAuthority:
    def verify(self, request, bundle):
        raise AttributionAdmissionError(
            "ATTRIBUTION_PURPOSE_AUTHORITY_UNAVAILABLE", "Independent Composite BF method authority is unavailable."
        )


@dataclass(frozen=True)
class CompositeAttributionDeployment:
    source: CompositeAttributionSource
    authority: CompositeAttributionAuthority


_deployment = CompositeAttributionDeployment(UnavailableAttributionSource(), UnavailableAttributionAuthority())
_installed = False


def install_composite_attribution_deployment(deployment: CompositeAttributionDeployment) -> None:
    """Server bootstrap only; no public route can install source or approval authority."""
    global _deployment, _installed
    if _installed:
        raise RuntimeError("Composite attribution deployment is already installed.")
    if deployment.source is None or deployment.authority is None:
        raise ValueError("Both independently governed source and purpose verifier are required.")
    _deployment, _installed = deployment, True


def get_composite_attribution_deployment() -> CompositeAttributionDeployment:
    return _deployment
