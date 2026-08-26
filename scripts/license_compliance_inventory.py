from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "contracts" / "license-compliance-policy.v1.json"
OUTPUT_PATH = ROOT / "quality" / "license_compliance_inventory.md"
PYPROJECT_PATH = ROOT / "pyproject.toml"
POETRY_LOCK_PATH = ROOT / "poetry.lock"
LICENSE_PATH = ROOT / "LICENSE"
REQUIREMENT_FILES = {
    "runtime": ROOT / "requirements.txt",
    "development": ROOT / "requirements-dev.txt",
}


@dataclass(frozen=True)
class RequirementEntry:
    name: str
    normalized_name: str
    specifier: str
    source: str


@dataclass(frozen=True)
class PackageLicense:
    name: str
    normalized_name: str
    specifier: str
    sources: tuple[str, ...]
    installed_version: str
    license_text: str
    license_source: str
    review_status: str
    exception_owner: str
    exception_expires_on: str


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirement_line(line: str, source: str) -> RequirementEntry | None:
    stripped = line.split("#", 1)[0].strip()
    if not stripped or stripped.startswith(("-", "git+", "http:", "https:")):
        return None

    name_part = re.split(r"[<>=!~]", stripped, maxsplit=1)[0].strip()
    name = name_part.split("[", 1)[0]
    if not name:
        return None

    return RequirementEntry(
        name=name,
        normalized_name=_normalize_name(name),
        specifier=stripped,
        source=source,
    )


def _load_requirements() -> list[RequirementEntry]:
    entries: list[RequirementEntry] = []
    for source, path in REQUIREMENT_FILES.items():
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = _parse_requirement_line(line, source)
            if entry is not None:
                entries.append(entry)
    return entries


def _load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pyproject_license(path: Path | None = None) -> str:
    path = path or PYPROJECT_PATH
    pyproject = tomllib.loads(path.read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    license_value = project.get("license")
    if isinstance(license_value, str):
        return license_value
    if isinstance(license_value, dict):
        return str(license_value.get("text") or license_value.get("file") or "")
    poetry_license = pyproject.get("tool", {}).get("poetry", {}).get("license")
    if isinstance(poetry_license, str):
        return poetry_license
    return ""


def _poetry_content_hash(pyproject: dict[str, Any]) -> str:
    project = pyproject.get("project", {})
    poetry = pyproject.get("tool", {}).get("poetry", {})
    legacy_keys = ["dependencies", "source", "extras", "dev-dependencies"]
    project_content = {
        key: project[key] for key in ["requires-python", "dependencies", "optional-dependencies"] if key in project
    }
    poetry_content = {}
    for key in [*legacy_keys, "group"]:
        value = poetry.get(key)
        if value is None and (key not in legacy_keys or project_content):
            continue
        poetry_content[key] = value
    relevant_content = (
        {"project": project_content, "tool": {"poetry": poetry_content}} if project_content else poetry_content
    )
    payload = json.dumps(relevant_content, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _poetry_lock_issues() -> list[str]:
    if not POETRY_LOCK_PATH.exists():
        return ["poetry.lock is missing"]
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    lock = tomllib.loads(POETRY_LOCK_PATH.read_text(encoding="utf-8"))
    actual_hash = lock.get("metadata", {}).get("content-hash")
    expected_hash = _poetry_content_hash(pyproject)
    if actual_hash != expected_hash:
        return ["poetry.lock is stale; run poetry lock"]
    return []


def _first_party_license_issues(policy: dict) -> list[str]:
    expected_license = policy["first_party_license"]
    issues: list[str] = []

    pyproject_license = _pyproject_license()
    if pyproject_license != expected_license:
        issues.append(
            f"pyproject.toml license {pyproject_license!r} does not match policy first_party_license {expected_license!r}"
        )

    if not LICENSE_PATH.exists():
        issues.append("LICENSE file is missing")
    else:
        license_text = LICENSE_PATH.read_text(encoding="utf-8")
        if "MIT License" not in license_text:
            issues.append("LICENSE file does not contain MIT License text")

    return issues


def _metadata_for_package(package_name: str) -> Any | None:
    try:
        return metadata.distribution(package_name).metadata
    except metadata.PackageNotFoundError:
        return None


def _installed_version(package_name: str) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return "not-installed"


def _license_text(package_name: str) -> tuple[str, str]:
    package_metadata = _metadata_for_package(package_name)
    if package_metadata is None:
        return "UNKNOWN", "missing-installed-metadata"

    expression = package_metadata.get("License-Expression")
    if expression:
        return expression.replace("|", "/"), "License-Expression"

    license_classifiers = [
        classifier.removeprefix("License :: ").replace("OSI Approved :: ", "")
        for classifier in package_metadata.get_all("Classifier", [])
        if classifier.startswith("License :: ")
    ]

    license_value = package_metadata.get("License")
    if license_value:
        first_line = " ".join(license_value.split())
        if first_line.lower() not in {"dual license"}:
            return first_line[:160], "License"

    if license_classifiers:
        return "; ".join(sorted(license_classifiers)), "Classifier"

    return "UNKNOWN", "missing-license-metadata"


def _contains_token(license_text: str, tokens: list[str]) -> str | None:
    lowered = license_text.lower()
    for token in tokens:
        if token.lower() in lowered:
            return token
    return None


def _exception_for(policy: dict, package_name: str, license_token: str) -> dict | None:
    today = date.today()
    for exception in policy.get("exceptions", []):
        if _normalize_name(exception.get("package", "")) != _normalize_name(package_name):
            continue
        if not _license_token_matches_exception(str(exception.get("license_token", "")), license_token):
            continue
        try:
            expires_on = date.fromisoformat(exception.get("expires_on", ""))
        except ValueError:
            return None
        if expires_on >= today:
            return exception
    return None


def _license_token_matches_exception(exception_token: str, observed_token: str) -> bool:
    normalized_exception = exception_token.lower()
    normalized_observed = observed_token.lower()
    return (
        normalized_exception == normalized_observed
        or normalized_exception in normalized_observed
        or normalized_observed in normalized_exception
    )


def _classify_license(package_name: str, license_text: str, policy: dict) -> tuple[str, str, str]:
    review_token = _contains_token(license_text, policy["review_required_license_tokens"])
    if review_token:
        exception = _exception_for(policy, package_name, review_token)
        if exception is None:
            return "review_required_missing_exception", "", ""
        return (
            "review_required_exception",
            exception["owner"],
            exception["expires_on"],
        )

    allowed_token = _contains_token(license_text, policy["allowed_license_tokens"])
    if allowed_token:
        return "allowed", "", ""

    blocked_token = _contains_token(license_text, policy["blocked_license_tokens"])
    if blocked_token:
        return "blocked", "", ""

    return "review_required_missing_exception", "", ""


def _merged_requirements(entries: list[RequirementEntry]) -> list[tuple[str, list[RequirementEntry]]]:
    grouped: dict[str, list[RequirementEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.normalized_name, []).append(entry)
    return sorted(grouped.items())


def _exact_pin(entry: RequirementEntry) -> str | None:
    match = re.fullmatch(r"[^=]+==([^,;\s]+)", entry.specifier)
    return match.group(1) if match else None


def build_inventory(policy: dict | None = None) -> tuple[list[PackageLicense], list[str]]:
    policy = policy or _load_policy()
    packages: list[PackageLicense] = []
    issues: list[str] = [*_first_party_license_issues(policy), *_poetry_lock_issues()]

    for _normalized_name, entries in _merged_requirements(_load_requirements()):
        representative = entries[0]
        pins = {_exact_pin(entry) for entry in entries}
        if None in pins:
            issues.append(f"{representative.name}: every governed requirement must use an exact == version pin")
        exact_pins = {pin for pin in pins if pin is not None}
        if len(exact_pins) > 1:
            issues.append(f"{representative.name}: conflicting exact version pins {sorted(exact_pins)}")
        installed_version = _installed_version(representative.name)
        if len(exact_pins) == 1 and installed_version not in exact_pins:
            expected_version = next(iter(exact_pins))
            issues.append(
                f"{representative.name}: installed version {installed_version!r} does not match exact pin {expected_version!r}"
            )
        license_text, license_source = _license_text(representative.name)
        review_status, exception_owner, exception_expires_on = _classify_license(
            representative.name,
            license_text,
            policy,
        )
        if review_status in {"blocked", "review_required_missing_exception"}:
            issues.append(f"{representative.name}: {review_status} for license {license_text}")
        packages.append(
            PackageLicense(
                name=representative.name,
                normalized_name=representative.normalized_name,
                specifier="; ".join(sorted({entry.specifier for entry in entries})),
                sources=tuple(sorted({entry.source for entry in entries})),
                installed_version=installed_version,
                license_text=license_text,
                license_source=license_source,
                review_status=review_status,
                exception_owner=exception_owner,
                exception_expires_on=exception_expires_on,
            )
        )

    return packages, issues


def render_inventory(packages: list[PackageLicense], policy: dict) -> str:
    allowed_count = sum(1 for package in packages if package.review_status == "allowed")
    exception_count = sum(1 for package in packages if package.review_status == "review_required_exception")
    blocked_count = sum(1 for package in packages if package.review_status == "blocked")
    missing_exception_count = sum(
        1 for package in packages if package.review_status == "review_required_missing_exception"
    )

    lines = [
        "# License Compliance Inventory",
        "",
        "Mode: generated first-party and third-party dependency license evidence.",
        "",
        "## Policy",
        "",
        f"- First-party license: `{policy['first_party_license']}`",
        "- Policy source: `contracts/license-compliance-policy.v1.json`",
        "- Gate command: `make license-compliance-gate`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Packages inventoried | {len(packages)} |",
        f"| Allowed packages | {allowed_count} |",
        f"| Review-required packages with active exception | {exception_count} |",
        f"| Blocked packages | {blocked_count} |",
        f"| Review-required packages missing exception | {missing_exception_count} |",
        "",
        "## Packages",
        "",
        "| Package | Requirement source | Requirement spec | Installed metadata version | License | License source | Review status | Exception owner | Exception expires |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for package in packages:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{package.name}`",
                    ", ".join(package.sources),
                    f"`{package.specifier}`",
                    f"`{package.installed_version}`",
                    package.license_text.replace("|", "/"),
                    package.license_source,
                    package.review_status,
                    package.exception_owner or "-",
                    package.exception_expires_on or "-",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Review Rules",
            "",
            "- `allowed` dependencies match the approved license token set in the policy.",
            "- `review_required_exception` dependencies require a policy exception with owner, rationale, and expiry.",
            "- `blocked` or `review_required_missing_exception` dependencies fail the gate.",
            "- Regenerate with `python scripts/license_compliance_inventory.py --write` after dependency changes.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check third-party license inventory.")
    parser.add_argument("--write", action="store_true", help="write quality/license_compliance_inventory.md")
    parser.add_argument("--check", action="store_true", help="fail if generated inventory differs or policy fails")
    args = parser.parse_args()

    policy = _load_policy()
    packages, issues = build_inventory(policy)
    rendered = render_inventory(packages, policy)

    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding="utf-8")

    if args.check:
        if issues:
            for issue in issues:
                print(issue)
            return 1
        if not OUTPUT_PATH.exists():
            print(f"{OUTPUT_PATH}: inventory file is missing")
            return 1
        current = OUTPUT_PATH.read_text(encoding="utf-8")
        if current != rendered:
            print(
                f"{OUTPUT_PATH}: license inventory is stale; run python scripts/license_compliance_inventory.py --write"
            )
            return 1

    if not args.write and not args.check:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
