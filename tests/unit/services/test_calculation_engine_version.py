from types import SimpleNamespace

from app.core.config import Settings
from app.services.calculation_engine_version import (
    CALCULATION_ENGINE_VERSION,
    CALCULATION_ENGINE_VERSION_FAMILIES,
    calculation_engine_version,
    calculation_engine_version_manifest,
)


def test_calculation_engine_version_is_not_deployable_app_version() -> None:
    settings = Settings()

    assert settings.CALCULATION_ENGINE_VERSION == CALCULATION_ENGINE_VERSION
    assert calculation_engine_version(settings) == CALCULATION_ENGINE_VERSION
    assert settings.CALCULATION_ENGINE_VERSION != settings.APP_VERSION


def test_calculation_engine_version_manifest_governs_all_hash_families() -> None:
    settings = SimpleNamespace(APP_VERSION="build-2026.07.10", CALCULATION_ENGINE_VERSION="methodology-v2")

    manifest = calculation_engine_version_manifest(settings)

    assert manifest["policy_version"] == "calculation-engine-version-policy.v1"
    assert manifest["calculation_engine_version"] == "methodology-v2"
    assert manifest["analytics_families"] == {
        family: "methodology-v2" for family in CALCULATION_ENGINE_VERSION_FAMILIES
    }
    assert "APP_VERSION" in str(manifest["build_identity_boundary"])
    assert "do not change calculation hashes" in str(manifest["build_identity_boundary"])
