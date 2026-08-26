from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import scripts.license_compliance_inventory as license_inventory
from scripts.license_compliance_inventory import (
    _classify_license,
    _exact_pin,
    _first_party_license_issues,
    _load_policy,
    _load_requirements,
    _normalize_name,
    build_inventory,
    render_inventory,
)

ROOT = Path(__file__).resolve().parents[3]


def test_license_compliance_inventory_matches_policy() -> None:
    policy = _load_policy()
    packages, issues = build_inventory(policy)
    rendered = render_inventory(packages, policy)
    packages_by_name = {package.normalized_name: package for package in packages}

    assert issues == []
    assert len(packages) == 46
    assert packages_by_name["pytest-randomly"].review_status == "allowed"
    assert packages_by_name["certifi"].review_status == "review_required_exception"
    assert packages_by_name["psycopg"].review_status == "review_required_exception"
    assert packages_by_name["psycopg"].exception_owner == "platform-security"
    assert "Blocked packages | 0" in rendered
    assert "Review-required packages missing exception | 0" in rendered


def test_non_exact_requirement_pin_fails_policy(tmp_path, monkeypatch) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    requirements.write_text("pytest>=9.0.3,<10.0.0\n", encoding="utf-8")
    monkeypatch.setattr(license_inventory, "REQUIREMENT_FILES", {"development": requirements})

    _packages, issues = build_inventory(_load_policy())

    assert "pytest: every governed requirement must use an exact == version pin" in issues


def test_installed_version_must_match_exact_pin(tmp_path, monkeypatch) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    requirements.write_text("pytest==9.0.3\n", encoding="utf-8")
    monkeypatch.setattr(license_inventory, "REQUIREMENT_FILES", {"development": requirements})
    monkeypatch.setattr(license_inventory, "_installed_version", lambda package_name: "9.0.4")

    _packages, issues = build_inventory(_load_policy())

    assert "pytest: installed version '9.0.4' does not match exact pin '9.0.3'" in issues


def test_conflicting_exact_pins_fail_policy(tmp_path, monkeypatch) -> None:
    runtime_requirements = tmp_path / "requirements.txt"
    development_requirements = tmp_path / "requirements-dev.txt"
    runtime_requirements.write_text("pytest==9.0.3\n", encoding="utf-8")
    development_requirements.write_text("pytest==9.0.4\n", encoding="utf-8")
    monkeypatch.setattr(
        license_inventory,
        "REQUIREMENT_FILES",
        {"runtime": runtime_requirements, "development": development_requirements},
    )

    _packages, issues = build_inventory(_load_policy())

    assert "pytest: conflicting exact version pins ['9.0.3', '9.0.4']" in issues


def test_poetry_manifest_and_lock_match_governed_exact_pins() -> None:
    requirement_pins = {
        entry.normalized_name: pin for entry in _load_requirements() if (pin := _exact_pin(entry)) is not None
    }
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    poetry = pyproject["tool"]["poetry"]
    declared = {
        **poetry["dependencies"],
        **poetry["group"]["dev"]["dependencies"],
    }
    declared.pop("python")

    declared_names = {_normalize_name(package_name) for package_name in declared}
    assert declared_names == set(requirement_pins)

    declared_pins = {}
    for package_name, declaration in declared.items():
        normalized_name = _normalize_name(package_name)
        version = declaration["version"] if isinstance(declaration, dict) else declaration
        assert version == requirement_pins[normalized_name], package_name
        declared_pins[normalized_name] = version

    locked_packages = {
        _normalize_name(package["name"]): package["version"]
        for package in tomllib.loads((ROOT / "poetry.lock").read_text(encoding="utf-8"))["package"]
    }
    assert {name: locked_packages[name] for name in declared_pins} == declared_pins


def test_review_required_license_without_exception_fails_policy() -> None:
    policy = copy.deepcopy(_load_policy())
    policy["exceptions"] = [exception for exception in policy["exceptions"] if exception["package"] != "psycopg"]

    status, owner, expires_on = _classify_license("psycopg", "LGPL-3.0-only", policy)

    assert status == "review_required_missing_exception"
    assert owner == ""
    assert expires_on == ""


def test_blocked_license_fails_policy() -> None:
    status, owner, expires_on = _classify_license("example", "AGPL-3.0-only", _load_policy())

    assert status == "blocked"
    assert owner == ""
    assert expires_on == ""


def test_lgpl_classifier_alias_uses_review_required_exception_before_gpl_block() -> None:
    status, owner, expires_on = _classify_license(
        "psycopg",
        "GNU Lesser General Public License v3 (LGPLv3)",
        _load_policy(),
    )

    assert status == "review_required_exception"
    assert owner == "platform-security"
    assert expires_on == "2027-01-31"


def test_first_party_license_mismatch_fails_policy(tmp_path, monkeypatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    license_file = tmp_path / "LICENSE"
    pyproject.write_text('[project]\nname = "example"\nlicense = "Apache-2.0"\n', encoding="utf-8")
    license_file.write_text("Apache License\n", encoding="utf-8")
    monkeypatch.setattr(license_inventory, "PYPROJECT_PATH", pyproject)
    monkeypatch.setattr(license_inventory, "LICENSE_PATH", license_file)

    issues = _first_party_license_issues(_load_policy())

    assert "pyproject.toml license 'Apache-2.0' does not match policy first_party_license 'MIT'" in issues
    assert "LICENSE file does not contain MIT License text" in issues
