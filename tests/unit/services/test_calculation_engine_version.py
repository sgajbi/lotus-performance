from types import SimpleNamespace

from app.core.config import Settings
from app.services.calculation_engine_version import (
    CALCULATION_ENGINE_VERSION,
    CALCULATION_ENGINE_VERSION_FAMILIES,
    calculation_engine_version,
    calculation_engine_version_manifest,
)
from core.repro import generate_canonical_hash_from_value


def test_calculation_engine_version_is_not_deployable_app_version() -> None:
    settings = Settings()

    assert settings.CALCULATION_ENGINE_VERSION == CALCULATION_ENGINE_VERSION
    assert calculation_engine_version(settings) == CALCULATION_ENGINE_VERSION
    assert settings.CALCULATION_ENGINE_VERSION != settings.APP_VERSION


def test_canonical_income_methodology_has_new_reproducibility_identity() -> None:
    assert CALCULATION_ENGINE_VERSION == "lotus-performance-calculation-engine.v3"
    source_input = {
        "portfolio_id": "INCOME_REPLAY",
        "cash_flows": [{"amount": "850", "cash_flow_type": "income", "timing": "eod"}],
    }

    old_fingerprint, old_hash = generate_canonical_hash_from_value(
        source_input, "lotus-performance-calculation-engine.v2"
    )
    new_fingerprint, new_hash = generate_canonical_hash_from_value(source_input, CALCULATION_ENGINE_VERSION)

    assert new_fingerprint == old_fingerprint
    assert new_hash != old_hash


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
