from __future__ import annotations

import copy

import scripts.license_compliance_inventory as license_inventory
from scripts.license_compliance_inventory import (
    _classify_license,
    _first_party_license_issues,
    _load_policy,
    build_inventory,
    render_inventory,
)


def test_license_compliance_inventory_matches_policy() -> None:
    policy = _load_policy()
    packages, issues = build_inventory(policy)
    rendered = render_inventory(packages, policy)
    packages_by_name = {package.normalized_name: package for package in packages}

    assert issues == []
    assert len(packages) == 45
    assert packages_by_name["certifi"].review_status == "review_required_exception"
    assert packages_by_name["psycopg"].review_status == "review_required_exception"
    assert packages_by_name["psycopg"].exception_owner == "platform-security"
    assert "Blocked packages | 0" in rendered
    assert "Review-required packages missing exception | 0" in rendered


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
