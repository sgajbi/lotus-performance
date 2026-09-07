"""Run the acceptance gate against synthetic scans, so its proofs do not expire.

Every rule in `scripts/container_acceptance_gate.py` was falsified by hand when
it was written, and nothing re-ran those falsifications afterwards. A one-time
proof binds to the version it was run against, so each later change to the gate
silently invalidated it -- and this gate changed five times under review. A guard
whose own correctness is unverified is the shape it exists to prevent.

The CLI already accepts alternate ignore, record and report paths, so every rule
can be exercised on temporary synthetic files with no container scan. That is
what makes this cheap enough to keep.

Each test states the failure it induces, because the assertion that matters is
that the gate *refuses*, not that it runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "scripts" / "container_acceptance_gate.py"

_ADVISORY = "CVE-2026-00001"
_PACKAGE = "libexample1"
_VERSION = "1.2.3-1"


def _finding(
    *,
    advisory: str = _ADVISORY,
    package: str = _PACKAGE,
    version: str = _VERSION,
    severity: str = "HIGH",
    fixed: str | None = None,
) -> dict:
    finding = {
        "VulnerabilityID": advisory,
        "PkgName": package,
        "InstalledVersion": version,
        "Severity": severity,
    }
    if fixed:
        finding["FixedVersion"] = fixed
    return finding


def _report(findings: list[dict]) -> dict:
    return {"Results": [{"Target": "synthetic", "Vulnerabilities": findings}]}


def _record(**overrides) -> dict:
    record = {
        "advisory_id": _ADVISORY,
        "severity": "HIGH",
        "packages": [{"name": _PACKAGE, "affected_version": _VERSION}],
        "fixed_version": None,
        "owner": "lotus-performance",
        "expires_on": "2099-01-01",
        "remediation_path": "No fixed version published for the base image; synthetic fixture.",
    }
    record.update(overrides)
    return record


class _Scenario:
    """One complete gate input: what is suppressed, what is recorded, what was scanned."""

    def __init__(
        self, tmp_path: Path, *, suppressed: list[str], records: list[dict], fixable: list[dict], full: list[dict]
    ) -> None:
        self.ignorefile = tmp_path / ".trivyignore.yaml"
        lines = ["vulnerabilities:"]
        for advisory in suppressed:
            lines += [f"  - id: {advisory}", '    statement: "synthetic"', "    expired_at: 2099-01-01"]
        self.ignorefile.write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.records = tmp_path / "acceptances.json"
        self.records.write_text(json.dumps({"acceptances": records}), encoding="utf-8")

        self.fixable = tmp_path / "fixable.json"
        self.fixable.write_text(json.dumps(_report(fixable)), encoding="utf-8")

        self.full = tmp_path / "full.json"
        self.full.write_text(json.dumps(_report(full)), encoding="utf-8")

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(GATE),
                "--ignorefile",
                str(self.ignorefile),
                "--records",
                str(self.records),
                "--fixable-report",
                str(self.fixable),
                "--full-report",
                str(self.full),
            ],
            capture_output=True,
            text=True,
            check=False,
        )


def test_a_governed_acceptance_matching_the_scan_passes(tmp_path: Path) -> None:
    """The control. Without it every refusal below could be a gate that always fails."""

    result = _Scenario(tmp_path, suppressed=[_ADVISORY], records=[_record()], fixable=[], full=[_finding()]).run()

    assert result.returncode == 0, result.stderr
    assert "1 governed acceptances" in result.stdout


def test_an_empty_acceptance_set_passes_for_a_clean_image(tmp_path: Path) -> None:
    """A base refresh that clears the last advisory must have a valid configuration.

    Refusing this left no passing state at all: removing the record failed, and
    keeping it failed the still-present check.
    """

    result = _Scenario(tmp_path, suppressed=[], records=[], fixable=[], full=[]).run()

    assert result.returncode == 0, result.stderr


def test_a_fixable_advisory_may_not_be_accepted(tmp_path: Path) -> None:
    """The load-bearing rule: acceptance must never substitute for fixing."""

    result = _Scenario(
        tmp_path,
        suppressed=[_ADVISORY],
        records=[_record()],
        fixable=[_finding(fixed="1.2.4-1")],
        full=[_finding(fixed="1.2.4-1")],
    ).run()

    assert result.returncode == 1
    assert "upstream fix" in result.stderr


def test_a_suppression_without_a_governed_record_is_refused(tmp_path: Path) -> None:
    result = _Scenario(tmp_path, suppressed=[_ADVISORY], records=[], fixable=[], full=[_finding()]).run()

    assert result.returncode == 1
    assert "no governed acceptance record" in result.stderr


def test_a_record_without_a_suppression_is_refused(tmp_path: Path) -> None:
    """Records outliving their entries, which is different from a clean image."""

    result = _Scenario(tmp_path, suppressed=[], records=[_record()], fixable=[], full=[_finding()]).run()

    assert result.returncode == 1


def test_duplicate_advisory_ids_are_refused_before_indexing(tmp_path: Path) -> None:
    """Indexing first would keep only the last record and validate nothing else.

    The discarded record still appears to govern its suppression, so the gate
    reports success over a suppression nobody checked.
    """

    result = _Scenario(
        tmp_path,
        suppressed=[_ADVISORY],
        records=[_record(owner="first"), _record(owner="second")],
        fixable=[],
        full=[_finding()],
    ).run()

    assert result.returncode == 1
    assert "Duplicate advisory ids" in result.stderr


@pytest.mark.parametrize("missing", ["owner", "expires_on", "remediation_path", "severity"])
def test_a_record_missing_a_required_policy_field_is_refused(tmp_path: Path, missing: str) -> None:
    result = _Scenario(
        tmp_path,
        suppressed=[_ADVISORY],
        records=[_record(**{missing: ""})],
        fixable=[],
        full=[_finding()],
    ).run()

    assert result.returncode == 1
    assert missing in result.stderr


def test_a_severity_reclassification_is_refused(tmp_path: Path) -> None:
    """HIGH accepted, CRITICAL scanned: same id, package and version, different approval."""

    result = _Scenario(
        tmp_path,
        suppressed=[_ADVISORY],
        records=[_record(severity="HIGH")],
        fixable=[],
        full=[_finding(severity="CRITICAL")],
    ).run()

    assert result.returncode == 1
    assert "scanned as ['CRITICAL']" in result.stderr


def test_a_package_the_acceptance_does_not_name_is_refused(tmp_path: Path) -> None:
    result = _Scenario(
        tmp_path,
        suppressed=[_ADVISORY],
        records=[_record()],
        fixable=[],
        full=[_finding(), _finding(package="libother2")],
    ).run()

    assert result.returncode == 1
    assert "does not name" in result.stderr


def test_a_recorded_package_absent_from_the_scan_is_refused(tmp_path: Path) -> None:
    """The other direction, which a one-sided comparison missed.

    A recorded package that has left the image stays pre-approved, and the
    suppression is id-wide -- so if it returns at the recorded version it is
    covered again with no review.
    """

    result = _Scenario(
        tmp_path,
        suppressed=[_ADVISORY],
        records=[
            _record(
                packages=[
                    {"name": _PACKAGE, "affected_version": _VERSION},
                    {"name": "libgone3", "affected_version": "9.9"},
                ]
            )
        ],
        fixable=[],
        full=[_finding()],
    ).run()

    assert result.returncode == 1
    assert "no longer reports" in result.stderr


def test_an_accepted_advisory_absent_from_the_image_is_refused(tmp_path: Path) -> None:
    result = _Scenario(tmp_path, suppressed=[_ADVISORY], records=[_record()], fixable=[], full=[]).run()

    assert result.returncode == 1
    assert "no longer present in the image" in result.stderr


def test_an_expired_acceptance_is_refused(tmp_path: Path) -> None:
    result = _Scenario(
        tmp_path,
        suppressed=[_ADVISORY],
        records=[_record(expires_on="2020-01-01")],
        fixable=[],
        full=[_finding()],
    ).run()

    assert result.returncode == 1
    assert "lapsed" in result.stderr


def test_a_missing_report_is_refused_rather_than_treated_as_nothing_to_answer_for(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, suppressed=[_ADVISORY], records=[_record()], fixable=[], full=[_finding()])
    scenario.fixable.unlink()

    assert scenario.run().returncode == 1


def test_a_malformed_report_is_refused(tmp_path: Path) -> None:
    """An empty object would make every acceptance look justified."""

    scenario = _Scenario(tmp_path, suppressed=[_ADVISORY], records=[_record()], fixable=[], full=[_finding()])
    scenario.full.write_text("{}", encoding="utf-8")

    result = scenario.run()
    assert result.returncode == 1
    assert "no Results key" in result.stderr
