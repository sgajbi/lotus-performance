"""One immutable public-only annual installer shared by API and executor."""

import hashlib
import logging
import os
from dataclasses import dataclass
from threading import Lock

from app.adapters.composite_attribution_configuration import read_bounded
from app.adapters.composite_controlled_annual_configuration import CONFIG_ENV, decode_annual_configuration
from app.adapters.composite_controlled_annual_verification import ConfiguredControlledYearVerification
from app.ports.composite_controlled_annual_evidence import install_controlled_year_verifier

_lock = Lock()
_installed = None
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnnualVerificationInstallation:
    configuration_digest: str
    revision: str
    profile: str


def bootstrap_composite_controlled_annual(*, application=None):
    global _installed
    path = os.environ.get(CONFIG_ENV)
    with _lock:
        if not path:
            if _installed is not None:
                raise RuntimeError("Installed annual configuration cannot be removed in process.")
            return None
        wire = read_bounded(path)
        digest = "sha256:" + hashlib.sha256(wire.encode("utf-8")).hexdigest()
        if _installed is None:
            verifier, configuration = _configured_verifier(wire)
            install_controlled_year_verifier(verifier)
            _installed = AnnualVerificationInstallation(digest, configuration.revision, configuration.profile)
            logger.info(
                "Composite controlled annual verification installed",
                extra={"extra_fields": {**vars(_installed), "qualification": "SYNTHETIC_NON_CERTIFYING"}},
            )
        elif _installed.configuration_digest != digest:
            raise RuntimeError("Installed annual configuration cannot change in process.")
        if application is not None:
            application.state.composite_controlled_annual_installation = {
                **vars(_installed),
                "qualification": "SYNTHETIC_NON_CERTIFYING",
            }
        return _installed


def _configured_verifier(wire):
    try:
        configuration = decode_annual_configuration(wire)
        verifier = ConfiguredControlledYearVerification(configuration)
        verifier.configuration()
    except ValueError:
        # Startup tracebacks must not serialize Pydantic input (retained proofs/credentials).
        raise ValueError("Controlled annual deployment configuration is invalid or unavailable.") from None
    return verifier, configuration
