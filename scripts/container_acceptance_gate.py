"""Refuse to accept a container finding that has an upstream fix.

`.trivyignore.yaml` exists so the vulnerability gate can pass on base-image
advisories with no published fix. It is also the easiest place in the repository
to make a real, fixable finding disappear, so the rule that keeps it honest is
that nothing fixable may be accepted.

That check needs the fixable scan report, which only exists in the lane that
scans the image. It started life as a unit test with a `skipif` on the report's
absence -- which would have skipped in every lane that runs unit tests, and run
in none of them. A check that is always skipped is reported as green and
enforces nothing, so it lives here instead, in the lane that has the evidence.

Reads the report produced by `make container-vulnerability-report`, which scans
with --ignore-unfixed: everything it lists therefore has a fix available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACCEPTANCES = REPO_ROOT / ".trivyignore.yaml"
DEFAULT_REPORT = REPO_ROOT / "output" / "container-security" / "lotus-performance-image-vulnerabilities.json"

_ACCEPTED_ID = re.compile(r"^  - id:\s*(\S+)\s*$", re.M)


def accepted_ids(path: Path) -> set[str]:
    ids = set(_ACCEPTED_ID.findall(path.read_text(encoding="utf-8")))
    if not ids:
        raise SystemExit(
            f"No acceptances parsed from {path}. Either the file is empty, in which case this "
            f"gate has nothing to check and should not be running, or its shape changed and "
            f"every acceptance is now unchecked while still suppressing findings."
        )
    return ids


def fixable_ids(path: Path) -> set[str]:
    report = json.loads(path.read_text(encoding="utf-8"))
    results = report.get("Results")
    if results is None:
        raise SystemExit(
            f"{path} has no Results key. An empty or malformed report would make every " f"acceptance look justified."
        )
    return {
        vulnerability["VulnerabilityID"] for result in results for vulnerability in result.get("Vulnerabilities") or []
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptances", type=Path, default=DEFAULT_ACCEPTANCES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    if not args.report.exists():
        raise SystemExit(
            f"{args.report} does not exist. Run `make container-vulnerability-report` first; "
            f"this gate must not pass by finding nothing to read."
        )

    accepted = accepted_ids(args.acceptances)
    fixable = fixable_ids(args.report)
    wrongly_accepted = sorted(accepted & fixable)

    if wrongly_accepted:
        print(
            "These container findings have an upstream fix and must be fixed rather than "
            f"accepted: {', '.join(wrongly_accepted)}",
            file=sys.stderr,
        )
        return 1

    print(
        f"Container acceptance gate passed: {len(accepted)} accepted advisories, "
        f"{len(fixable)} fixable findings, no overlap."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
