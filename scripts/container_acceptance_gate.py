"""Decide the container vulnerability verdict from one scan, against one record.

`quality/container_supply_chain_report.md` requires every HIGH/CRITICAL finding
to be zero or explicitly accepted, with each acceptance "narrow, time-bound, and
tied to image package identity, severity, CVE/advisory identifier, affected
version, fixed version if available, and owner".

Two structural problems this replaced, both found in review:

**Three scans behind one verdict.** The evidence upload, the acceptance
validation and the blocking decision each ran their own `docker run --rm` with no
shared cache. A vulnerability-database update between invocations could make the
uploaded artifact omit the finding that failed the job, or let an id-wide
suppression cover a package the validation never saw. Three answers to one
question, reported as one. Now: one scan, retained as the evidence artifact, and
every decision below reads it.

**Two records.** `.trivyignore.yaml` and the governed JSON both described what
was accepted, in different vocabularies -- and the file Trivy actually obeyed was
the one carrying no owner, no expiry and no package identity. The governed JSON
is the only authority now, and the verdict is computed here rather than by a
Trivy `--exit-code`.

The rules, each for a way this goes wrong:

  * a finding with no acceptance blocks, which is the gate's actual job
  * nothing with an upstream fix may be accepted; it must be fixed
  * every record carries the policy's required fields
  * an acceptance must still describe the image: the base tag floats, so the
    same advisory can reappear in a different package, version or severity, and
    a record naming the old one would cover it unreviewed
  * an acceptance absent from the scan is removed, not left to cover whatever
    reappears under that id later
  * acceptance expires, so the base-image decision is revisited rather than
    inherited

A missing or malformed scan is a refusal, never a pass: this gate must not
conclude "nothing to answer for" from having nothing to read.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = REPO_ROOT / "quality" / "container_vulnerability_acceptances.v1.json"
DEFAULT_SCAN = REPO_ROOT / "output" / "container-security" / "lotus-performance-image-vulnerabilities.json"

REQUIRED_FIELDS = ("advisory_id", "severity", "packages", "owner", "expires_on", "remediation_path")


def _fail(message: str) -> None:
    print(message, file=sys.stderr)


def _findings(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Run `make container-vulnerability-report` first; this gate "
            f"must not pass by finding no scan to read."
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("Results") is None:
        raise SystemExit(
            f"{path} has no Results key. A malformed scan would make every acceptance look "
            f"justified and every unaccepted finding disappear."
        )
    return [vulnerability for result in report["Results"] for vulnerability in result.get("Vulnerabilities") or []]


def _indexed(records: list[dict], source: Path) -> dict[str, dict]:
    """Index by advisory id, refusing duplicates before they can hide each other."""

    duplicates = sorted(
        {
            record["advisory_id"]
            for index, record in enumerate(records)
            if record["advisory_id"] in {other["advisory_id"] for other in records[:index]}
        }
    )
    if duplicates:
        raise SystemExit(
            f"Duplicate advisory ids in {source}: {duplicates}. Only one record per advisory can "
            f"be validated; the others would be silently discarded while still appearing to "
            f"govern their suppression."
        )
    return {record["advisory_id"]: record for record in records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--scan", type=Path, default=DEFAULT_SCAN)
    args = parser.parse_args()

    by_id = _indexed(json.loads(args.records.read_text(encoding="utf-8"))["acceptances"], args.records)
    findings = _findings(args.scan)
    failures: list[str] = []

    present: dict[str, set[tuple[str, str]]] = {}
    severities: dict[str, set[str]] = {}
    fixable: set[str] = set()
    for finding in findings:
        advisory = finding["VulnerabilityID"]
        present.setdefault(advisory, set()).add((finding["PkgName"], finding["InstalledVersion"]))
        severities.setdefault(advisory, set()).add(finding["Severity"])
        if finding.get("FixedVersion"):
            fixable.add(advisory)

    if unaccepted := sorted(set(present) - set(by_id)):
        failures.append(
            f"unaccepted high/critical findings in the image: {unaccepted}. Fix them, or record "
            f"an acceptance carrying package identity, severity, owner, expiry and remediation."
        )

    if wrongly := sorted(set(by_id) & fixable):
        failures.append(f"these have an upstream fix and must be fixed rather than accepted: {wrongly}")

    for advisory, record in sorted(by_id.items()):
        if missing := [field for field in REQUIRED_FIELDS if not record.get(field)]:
            failures.append(f"{advisory} is missing required policy fields: {missing}")

        scanned = present.get(advisory)
        if scanned is None:
            failures.append(
                f"{advisory} is accepted but no longer present in the image. A stale acceptance "
                f"suppresses nothing today and would silently cover whatever reappears under "
                f"that id tomorrow; remove it."
            )
            continue

        if unapproved := sorted(severities[advisory] - {record["severity"]}):
            failures.append(
                f"{advisory} is now scanned as {unapproved} but was accepted as "
                f"{record['severity']!r}. Severity is part of what was approved; re-review it "
                f"rather than inheriting the old decision."
            )

        recorded = {(package["name"], package["affected_version"]) for package in record["packages"]}
        if unnamed := sorted(scanned - recorded):
            failures.append(
                f"{advisory} now affects package versions this acceptance does not name: "
                f"{unnamed}. The acceptance was reviewed against different packages, so it must "
                f"be re-reviewed rather than carried forward."
            )
        if stale := sorted(recorded - scanned):
            failures.append(
                f"{advisory} records package versions the scan no longer reports: {stale}. "
                f"Leaving them pre-approves a package that would be covered without review if "
                f"it returned; remove them from the record or re-review the acceptance."
            )

    today = dt.date.today()
    if expired := sorted(
        advisory for advisory, record in by_id.items() if dt.date.fromisoformat(record["expires_on"]) < today
    ):
        failures.append(f"these acceptances have lapsed and must be re-decided, not extended: {expired}")

    if failures:
        _fail("Container vulnerability gate failed:")
        for failure in failures:
            _fail(f"  - {failure}")
        return 1

    print(
        f"Container vulnerability gate passed: {len(findings)} high/critical finding(s), all "
        f"{len(by_id)} accepted with matching packages and severities, none fixable, none "
        f"expired. Decided from one scan snapshot."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
