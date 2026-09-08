"""The concurrency-contracts gate refuses everything that is not a completed proof.

The contracts it guards call `pytest.skip` when no database answers, so a green lane
is not evidence on its own -- that is the gap #489 exists to close, and this gate is
what closes it. These tests drive the gate itself on the shapes that must not pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = "scripts/postgres_concurrency_contracts_gate.py"


def _run_gate(target: Path, environment_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, **(environment_overrides or {})}
    return subprocess.run(
        [sys.executable, GATE, "--target", str(target)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_a_completed_run_with_no_skips_passes(tmp_path: Path) -> None:
    """The accepted case, so the refusals below mean something.

    Without an accepted baseline a suite of refusals is indistinguishable from a gate
    that refuses everything.
    """

    target = tmp_path / "test_contracts_completed.py"
    target.write_text("def test_contract():\n    assert True\n", encoding="utf-8")

    result = _run_gate(target)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "none skipped" in result.stdout


def test_a_skipped_contract_is_refused(tmp_path: Path) -> None:
    """A skip and a pass are the same colour to a CI lane.

    This is the whole reason the gate exists: the real contracts skip when no database
    answers, which is correct behaviour and silent loss of the advisory-lock proof.
    """

    target = tmp_path / "test_contracts_skipped.py"
    target.write_text(
        "import pytest\n\n\ndef test_contract():\n    pytest.skip('no database')\n",
        encoding="utf-8",
    )

    result = _run_gate(target)

    assert result.returncode == 1
    assert "skipped" in result.stdout


def test_a_nonzero_pytest_exit_is_refused_even_with_a_green_report(tmp_path: Path) -> None:
    """A green report describes what finished, not that the run finished.

    pytest writes the report for the tests it completed, so an interrupt or an internal
    error can leave counts that are entirely green while the remaining contracts never
    ran. Reading counts without the exit status reproduces, one level up, exactly the
    defect this gate was built to catch -- a partial run reported as a complete one.

    `pytest_sessionfinish` forces the combination deterministically; the real causes
    (an interrupt, an internal error, a crashed worker) produce the same pair. Written
    after a first attempt that raised `KeyboardInterrupt` inside a test, which the gate
    rejected through its empty-collection branch instead and therefore proved nothing
    about this one.

    Raised in review of #489.
    """

    (tmp_path / "conftest.py").write_text(
        "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 2\n",
        encoding="utf-8",
    )
    target = tmp_path / "test_contracts_interrupted.py"
    target.write_text("def test_contract():\n    assert True\n", encoding="utf-8")

    result = _run_gate(target)

    assert result.returncode == 1, "a nonzero pytest exit was accepted on a green report"
    assert "pytest exited 2" in result.stdout


def test_collecting_nothing_is_refused(tmp_path: Path) -> None:
    """Zero contracts is zero evidence, and pytest reports it cheerfully."""

    target = tmp_path / "test_contracts_empty.py"
    target.write_text("# no tests here\n", encoding="utf-8")

    result = _run_gate(target)

    assert result.returncode == 1
    assert "no concurrency contracts were collected" in result.stdout


TARGET_SOURCE = """
def test_contract_that_passes():
    assert True


def test_contract_that_fails():
    raise AssertionError("this contract must not be deselected")
"""


def test_an_inherited_selector_cannot_shrink_what_the_gate_proves(tmp_path: Path) -> None:
    """A deselected contract is absent from the report, not recorded as skipped.

    Every other refusal here reads a count the report states. This one is about a
    contract the report never mentions: `-k` deselection leaves JUnit XML that is green,
    internally consistent and describes a smaller suite, so `skipped`, `failures` and
    `errors` are all zero and agree with each other. The gate cannot detect from counts
    alone that it was handed a different question.

    The target holds a passing contract and a failing one, and the inherited selector
    names only the passing one. If the selector reaches pytest, the gate sees a single
    green test and reports the run complete; if it does not, the failing contract runs
    and the gate refuses. The two outcomes are opposite rather than merely different, so
    a regression here cannot present as a pass. Raised in review of #489.
    """

    target = tmp_path / "test_contracts_selected.py"
    target.write_text(TARGET_SOURCE, encoding="utf-8")

    result = _run_gate(target, {"PYTEST_ADDOPTS": "-k test_contract_that_passes"})

    assert result.returncode != 0, (
        "an inherited -k selected one contract and the gate called the run complete: " + result.stdout + result.stderr
    )
    assert "failure(s)" in result.stdout
