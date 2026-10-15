"""One server-owned composition shared by API, executor and retained reader."""

import hashlib
import os
from dataclasses import dataclass
from threading import Lock

from app.adapters.composite_attribution_artifact_source import ConfiguredAttributionSource
from app.adapters.composite_attribution_configuration import (
    CONFIG_ENV,
    ConfiguredPrincipalAuthority,
    decode_configuration,
    read_bounded,
)
from app.adapters.composite_attribution_deployment import (
    CompositeAttributionDeployment,
    install_composite_attribution_deployment,
)
from app.adapters.composite_attribution_purpose_verifier import ConfiguredAttributionPurposeVerifier
from app.adapters.composite_source_authority_deployment import (
    ConfiguredSourceAuthorities,
    configured_source_authorities,
    install_source_authorities,
)
from app.composite_principal_admission import CompositePrincipalDeployment

_lock = Lock()
_installed = None


@dataclass(frozen=True)
class AttributionInstallation:
    configuration_digest: str
    revision: str
    profile: str
    principal_deployment: CompositePrincipalDeployment


def bootstrap_composite_attribution(*, application=None):
    """Missing configuration leaves all existing unavailable ports untouched."""
    global _installed
    path = os.environ.get(CONFIG_ENV)
    with _lock:
        if not path:
            if _installed is not None:
                raise RuntimeError("Installed attribution configuration cannot be removed in process.")
            return None
        wire = read_bounded(path)
        digest = "sha256:" + hashlib.sha256(wire.encode("utf-8")).hexdigest()
        if _installed is None:
            _installed = _compose(wire, digest)
        elif _installed.configuration_digest != digest:
            raise RuntimeError("Installed attribution configuration cannot change in process.")
        if application is not None:
            application.state.composite_principal_deployment = _installed.principal_deployment
            application.state.composite_attribution_installation = {
                "configuration_digest": digest,
                "revision": _installed.revision,
                "profile": _installed.profile,
                "qualification": "SYNTHETIC_NON_CERTIFYING",
            }
        return _installed


def _compose(wire, digest):
    configuration = decode_configuration(wire)
    authority = ConfiguredPrincipalAuthority(configuration)
    authority.configuration()  # Expired enabled configuration refuses startup.
    source = ConfiguredAttributionSource(configuration, authority)
    verifier = ConfiguredAttributionPurposeVerifier(source)
    # Only the worker consumes financial source/approval. Retained-reader startup
    # must not reread that source or request a new BF approval.
    original = ConfiguredSourceAuthorities(authority)
    if configured_source_authorities() is not None:
        raise RuntimeError("Original source authority was installed outside shared bootstrap.")
    install_composite_attribution_deployment(CompositeAttributionDeployment(source, verifier))
    install_source_authorities(original)
    return AttributionInstallation(
        digest,
        configuration.revision,
        configuration.profile,
        CompositePrincipalDeployment(configuration.principal_trust.trust(), authority),
    )
