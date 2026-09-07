"""Hold container vulnerability acceptances to what the promotion policy demands.

`quality/container_supply_chain_report.md` requires each accepted exception to be
"narrow, time-bound, and tied to image package identity, severity, CVE/advisory
identifier, affected version, fixed version if available, and owner". Trivy's
ignore file carries an id, a sentence and a date, and nothing else -- so it can
express the suppression but not the policy. The governed record in
`quality/container_vulnerability_acceptances.v1.json` carries the rest, and this
gate is what keeps the two honest against a live scan.

Four rules, each for a way an acceptance file goes wrong:

  * nothing with an upstream fix may be accepted -- otherwise this becomes the
    cheapest place in the repository to make a real finding disappear
  * every suppressed id must have a governed record, and every governed record
    every required field, so a bare id cannot silently suppress anything
  * an acceptance must still describe the image: the base tag floats, so the same
    CVE can reappear in a different package or version, or be reclassified to a
    higher severity, and a record naming the old one would keep suppressing a
    finding nobody approved in its current form
  * an expired acceptance fails, so the base image decision is revisited rather
    than inherited by whoever is on duty

Every check reads a scan of the current image. A missing or empty report is a
refusal rather than a pass: this gate must never conclude "nothing to answer for"
from having nothing to read.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IGNOREFILE = REPO_ROOT / ".trivyignore.yaml"
DEFAULT_RECORDS = REPO_ROOT / "quality" / "container_vulnerability_acceptances.v1.json"
SECURITY_OUTPUT = REPO_ROOT / "output" / "container-security"
DEFAULT_FIXABLE = SECURITY_OUTPUT / "lotus-performance-image-fixable.json"
DEFAULT_FULL = SECURITY_OUTPUT / "lotus-performance-image-vulnerabilities.json"

REQUIRED_FIELDS = ("advisory_id", "severity", "packages", "owner", "expires_on", "remediation_path")
_IGNORED_ID = re.compile(r"^  - id:\s*(\S+)\s*$", re.M)


def _fail(message: str) -> None:
    print(message, file=sys.stderr)


def _findings(path: Path, *, description: str) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Run `make container-vulnerability-report` first; this gate "
            f"must not pass by finding no {description} to read."
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("Results") is None:
        raise SystemExit(
            f"{path} has no Results key. A malformed {description} report would make every "
            f"acceptance look justified."
        )
    return [vulnerability for result in report["Results"] for vulnerability in result.get("Vulnerabilities") or []]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ignorefile", type=Path, default=DEFAULT_IGNOREFILE)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--fixable-report", type=Path, default=DEFAULT_FIXABLE)
    parser.add_argument("--full-report", type=Path, default=DEFAULT_FULL)
    args = parser.parse_args()

    suppressed = set(_IGNORED_ID.findall(args.ignorefile.read_text(encoding="utf-8")))
    if not suppressed:
        raise SystemExit(
            f"No suppressions parsed from {args.ignorefile}. Either it is empty, in which case "
            f"this gate has nothing to check, or its shape changed and every suppression is now "
            f"unchecked while still hiding findings."
        )

    records = json.loads(args.records.read_text(encoding="utf-8"))["acceptances"]
    by_id = {record["advisory_id"]: record for record in records}
    failures: list[str] = []

    # 1. Nothing fixable may be accepted.
    fixable = {finding["VulnerabilityID"] for finding in _findings(args.fixable_report, description="fixable")}
    if wrongly := sorted(suppressed & fixable):
        failures.append(f"these have an upstream fix and must be fixed rather than accepted: {wrongly}")

    # 2. Every suppression is governed, and every record is complete.
    if ungoverned := sorted(suppressed - set(by_id)):
        failures.append(f"suppressed with no governed acceptance record: {ungoverned}")
    if orphaned := sorted(set(by_id) - suppressed):
        failures.append(f"governed records for advisories nothing suppresses; remove them: {orphaned}")
    for advisory_id, record in sorted(by_id.items()):
        if missing := [field for field in REQUIRED_FIELDS if not record.get(field)]:
            failures.append(f"{advisory_id} is missing required policy fields: {missing}")

    # 3. Each record must still describe the image that is actually being scanned.
    present: dict[str, set[tuple[str, str]]] = {}
    live_severities: dict[str, set[str]] = {}
    for finding in _findings(args.full_report, description="unfiltered"):
        present.setdefault(finding["VulnerabilityID"], set()).add((finding["PkgName"], finding["InstalledVersion"]))
        live_severities.setdefault(finding["VulnerabilityID"], set()).add(finding["Severity"])
    for advisory_id, record in sorted(by_id.items()):
        scanned = present.get(advisory_id)
        if scanned is None:
            failures.append(
                f"{advisory_id} is accepted but no longer present in the image. The base tag "
                f"floats, so a stale acceptance suppresses nothing today and will silently cover "
                f"whatever reappears under that id tomorrow; remove it."
            )
            continue
        # Severity is part of what was approved, not a label on it. A CVE reclassified
        # from HIGH to CRITICAL keeps its id, package and version, so a match on those
        # alone would keep suppressing it under an approval nobody gave for a critical.
        if unapproved := sorted(live_severities[advisory_id] - {record["severity"]}):
            failures.append(
                f"{advisory_id} is now scanned as {unapproved} but was accepted as "
                f"{record['severity']!r}. Severity is part of what was approved; re-review it "
                f"rather than inheriting the old decision."
            )
        recorded = {(package["name"], package["affected_version"]) for package in record["packages"]}
        if drifted := sorted(scanned - recorded):
            failures.append(
                f"{advisory_id} now affects package versions this acceptance does not name: "
                f"{drifted}. The acceptance was reviewed against different packages, so it must "
                f"be re-reviewed rather than carried forward."
            )

    # 4. Acceptance is time-bound.
    today = dt.date.today()
    if expired := sorted(
        advisory_id for advisory_id, record in by_id.items() if dt.date.fromisoformat(record["expires_on"]) < today
    ):
        failures.append(f"these acceptances have lapsed and must be re-decided, not extended: {expired}")

    if failures:
        _fail("Container acceptance gate failed:")
        for failure in failures:
            _fail(f"  - {failure}")
        return 1

    print(
        f"Container acceptance gate passed: {len(suppressed)} governed acceptances, all present "
        f"in the scanned image with matching package versions, none fixable, none expired."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
