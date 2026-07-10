from __future__ import annotations

from typing import Any

CALCULATION_ENGINE_VERSION = "lotus-performance-calculation-engine.v1"
CALCULATION_ENGINE_VERSION_POLICY_VERSION = "calculation-engine-version-policy.v1"

CALCULATION_ENGINE_VERSION_FAMILIES = (
    "twr",
    "mwr",
    "contribution",
    "attribution",
    "benchmark",
    "workspace-summary",
    "twr-inspection",
    "returns-series",
)


def calculation_engine_version(settings: Any | None = None) -> str:
    """Return the governed methodology/hash identity version, not the deployable build version."""
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    return str(getattr(settings, "CALCULATION_ENGINE_VERSION", CALCULATION_ENGINE_VERSION))


def calculation_engine_version_manifest(settings: Any | None = None) -> dict[str, object]:
    version = calculation_engine_version(settings)
    return {
        "policy_version": CALCULATION_ENGINE_VERSION_POLICY_VERSION,
        "calculation_engine_version": version,
        "analytics_families": {family: version for family in CALCULATION_ENGINE_VERSION_FAMILIES},
        "build_identity_boundary": "APP_VERSION, Git SHA, image labels, and /version identify deployable build provenance; they do not change calculation hashes unless this governed calculation engine version also changes.",
    }
