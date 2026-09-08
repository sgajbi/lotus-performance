"""Prove the PostgreSQL concurrency contracts ran against a real database.

These contracts -- advisory-lock timeout behaviour and disjoint worker claims -- call
`pytest.skip` when no database answers, which is correct for a proof that needs real
locking and is exactly why running them is not the same as proving them. A skip and a
pass are the same colour to a CI lane, so #489 asks for the stronger statement: the
tests were selected, none skipped, and all passed.

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
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = "tests/benchmarks/test_postgres_concurrency_contracts.py"


def _totals(report: Path) -> dict[str, int]:
    """Aggregate counts across the suites in one JUnit report."""

    root = ElementTree.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        raise SystemExit(f"{report} contains no testsuite element; the run produced no report.")

    fields = ("tests", "skipped", "failures", "errors")
    return {field: sum(int(suite.get(field, 0)) for suite in suites) for field in fields}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "postgres-concurrency-contracts.xml"
        # A selector reaching this run from outside decides which contracts exist. A
        # deselected test is absent from the JUnit report entirely -- not recorded as
        # skipped -- so `PYTEST_ADDOPTS="-k schema_creator"` leaves a report that is
        # green, complete-looking and describes one contract, and every count this gate
        # reads agrees with it. `-o addopts=` clears any repository `addopts`, and
        # PYTEST_ADDOPTS is dropped from the child environment because `-o` does not
        # override it. Raised in review of #489.
        environment = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                args.target,
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
            raise SystemExit(
                f"pytest produced no JUnit report at {report} (exit {completed.returncode}). "
                "Treated as a refusal: a gate that cannot read its own evidence must not pass."
            )
        totals = _totals(report)

    failures: list[str] = []
    if completed.returncode != 0:
        # The XML alone is not sufficient evidence. pytest writes a report for the
        # tests it managed to finish, so an interrupt or an internal error (exit 2 or
        # 3) can leave a report that is entirely green and describes only the contracts
        # that ran before the run died. Reading counts without the exit status is the
        # same defect this gate exists to catch, one level up: a partial run reported
        # as a complete one. Raised in review of #489.
        failures.append(
            f"pytest exited {completed.returncode}. The report describes only what finished, "
            "so a green count here does not mean the contracts completed."
        )
    if totals["tests"] == 0:
        failures.append("no concurrency contracts were collected; the proof did not run at all")
    if totals["skipped"]:
        failures.append(
            f"{totals['skipped']} contract(s) skipped. These require a live PostgreSQL; a skip "
            "here is a silent loss of the advisory-lock proof, which is the gap #489 exists to "
            "close. Provide LOTUS_POSTGRES_PLAN_DATABASE_URL pointing at a real database."
        )
    if totals["failures"] or totals["errors"]:
        failures.append(
            f"{totals['failures']} failure(s) and {totals['errors']} error(s) in the concurrency " "contracts"
        )

    if failures:
        print("PostgreSQL concurrency contracts gate failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(
        f"PostgreSQL concurrency contracts gate passed: {totals['tests']} contract(s) ran "
        "against a live database, none skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
