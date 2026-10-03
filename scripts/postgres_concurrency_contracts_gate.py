"""Prove the required PostgreSQL behavioral contracts ran against a real database.

These contracts -- advisory-lock behavior, disjoint worker claims, and immutable
composite-fact migration/selection -- call `pytest.skip` when no database answers,
which is correct for proof that needs real PostgreSQL semantics and is exactly why
running them is not the same as proving them. A skip and a pass are the same colour to
a CI lane, so the gate requires that every selected test ran and passed.

Counts come from the JUnit XML pytest writes, not from its human-readable summary. The
first version of this gate grepped for `^3 passed`, which coupled a required lane to a
manually synchronised test count -- adding a fourth contract would have blocked every
PR while pytest was entirely green -- and parsed prose that pytest is free to reword.
The XML carries `tests`, `skipped`, `failures` and `errors` as attributes, so the rule
becomes "everything collected ran and passed" and stays true as contracts are added.

Lives here rather than as a `run:` block because `quality/ci_quality_gates.md` states
that raw pytest commands do not belong in workflow YAML for governed test lanes, and
because a gate that cannot be run locally is one nobody can reproduce before pushing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    "tests/benchmarks/test_postgres_concurrency_contracts.py",
    "tests/benchmarks/test_postgres_composite_fact_versions.py",
    "tests/benchmarks/test_postgres_composite_materialization.py",
)


def _totals(report: Path) -> dict[str, int]:
    """Aggregate counts across the suites in one JUnit report."""

    root = ElementTree.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        raise SystemExit(f"{report} contains no testsuite element; the run produced no report.")

    fields = ("tests", "skipped", "failures", "errors")
    return {field: sum(int(suite.get(field, 0)) for suite in suites) for field in fields}


def _run_target(
    target: str,
    *,
    scratch: Path,
    environment: dict[str, str],
) -> tuple[dict[str, int], list[str]]:
    report = scratch / f"postgres-contracts-{sha256(target.encode()).hexdigest()[:12]}.xml"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            target,
            "-q",
            "--no-header",
            "-o",
            "addopts=",
            f"--junitxml={report}",
        ],
        cwd=REPO_ROOT,
        env=environment,
    )
    if not report.exists():
        return {}, [
            f"{target}: pytest produced no JUnit report at {report} (exit {completed.returncode}); "
            "a gate that cannot read its own evidence must not pass"
        ]

    totals = _totals(report)
    failures: list[str] = []
    if completed.returncode != 0:
        failures.append(
            f"{target}: pytest exited {completed.returncode}. The report describes only what finished, "
            "so a green count here does not mean the contracts completed."
        )
    if totals["tests"] == 0:
        failures.append(f"{target}: no PostgreSQL contracts were collected; this target's proof did not run")
    if totals["skipped"]:
        failures.append(
            f"{target}: {totals['skipped']} contract(s) skipped. These require a live PostgreSQL; "
            "provide LOTUS_POSTGRES_PLAN_DATABASE_URL pointing at a real database."
        )
    if totals["failures"] or totals["errors"]:
        failures.append(
            f"{target}: {totals['failures']} failure(s) and {totals['errors']} error(s) in the PostgreSQL contracts"
        )
    return totals, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", dest="targets")
    args = parser.parse_args()
    targets = args.targets or list(DEFAULT_TARGETS)

    with tempfile.TemporaryDirectory() as scratch:
        # A selector reaching this run from outside decides which contracts exist. A
        # deselected test is absent from the JUnit report entirely -- not recorded as
        # skipped -- so `PYTEST_ADDOPTS="-k schema_creator"` leaves a report that is
        # green, complete-looking and describes one contract, and every count this gate
        # reads agrees with it. `-o addopts=` clears any repository `addopts`, and
        # PYTEST_ADDOPTS is dropped from the child environment because `-o` does not
        # override it. Raised in review of #489.
        environment = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
        results = [_run_target(target, scratch=Path(scratch), environment=environment) for target in targets]

    totals = {
        field: sum(target_totals.get(field, 0) for target_totals, _ in results)
        for field in ("tests", "skipped", "failures", "errors")
    }
    failures = [failure for _, target_failures in results for failure in target_failures]

    if failures:
        print("PostgreSQL contracts gate failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(
        "PostgreSQL contracts gate passed: "
        f"{totals['tests']} contract(s) across {len(targets)} target(s) ran against a live database, none skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
