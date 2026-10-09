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

import pytest
from coverage import CoverageData

from scripts import postgres_concurrency_contracts_gate

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = "scripts/postgres_concurrency_contracts_gate.py"


def test_default_invocation_executes_fee_pooled_and_result_authority_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    selected: list[str] = []

    def run_target(
        target: str, *, scratch: Path, environment: dict[str, str], collect_coverage: bool = False
    ) -> tuple[dict[str, int], list[str]]:
        selected.append(target)
        return {"tests": 1, "skipped": 0, "failures": 0, "errors": 0}, []

    monkeypatch.setattr(sys, "argv", [GATE])
    monkeypatch.setattr(postgres_concurrency_contracts_gate, "_run_target", run_target)

    assert postgres_concurrency_contracts_gate.main() == 0
    assert {
        "tests/benchmarks/test_postgres_composite_model_fee.py",
        "tests/benchmarks/test_postgres_composite_scheduled_model_fee.py",
        "tests/benchmarks/test_postgres_composite_component_model_fee.py",
        "tests/integration/test_composite_component_model_fee_api.py",
        "tests/benchmarks/test_postgres_composite_pooled_mwr.py",
        "tests/benchmarks/test_postgres_composite_authority.py",
        "tests/benchmarks/test_postgres_composite_authority_extended.py",
    } <= set(selected)


def _run_gate(
    target: Path | tuple[Path, ...],
    environment_overrides: dict[str, str] | None = None,
    *,
    coverage_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, **(environment_overrides or {})}
    targets = target if isinstance(target, tuple) else (target,)
    target_arguments = [argument for selected in targets for argument in ("--target", str(selected))]
    if coverage_file is not None:
        target_arguments.extend(["--coverage-file", str(coverage_file)])
    return subprocess.run(
        [sys.executable, GATE, *target_arguments],
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


def test_missing_junit_report_is_refused_even_after_zero_process_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0))
    totals, failures = postgres_concurrency_contracts_gate._run_target(
        "missing-target", scratch=tmp_path, environment={}
    )
    assert totals == {} and len(failures) == 1
    assert "produced no JUnit report" in failures[0]


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
    assert "no PostgreSQL contracts were collected" in result.stdout


def test_each_selected_target_must_collect_its_own_contract(tmp_path: Path) -> None:
    empty_target = tmp_path / "test_contracts_empty.py"
    empty_target.write_text("# no tests here\n", encoding="utf-8")
    passing_target = tmp_path / "test_contracts_completed.py"
    passing_target.write_text("def test_contract():\n    assert True\n", encoding="utf-8")

    result = _run_gate((empty_target, passing_target))

    assert result.returncode == 1
    assert f"{empty_target}: no PostgreSQL contracts were collected" in result.stdout


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


def _coverage_lines(path: Path) -> dict[str, set[int]]:
    data = CoverageData(basename=str(path))
    data.read()
    return {filename: set(data.lines(filename) or []) for filename in data.measured_files()}


def test_coverage_appends_both_target_processes_and_preserves_prior_shard(tmp_path: Path) -> None:
    seed = tmp_path / "test_prior_integration.py"
    first = tmp_path / "test_business_calendar.py"
    second = tmp_path / "test_actual_calendar.py"
    seed.write_text(
        "from core.annualize import annualize_return\n"
        "def test_prior():\n"
        "    assert abs(annualize_return(.1, 365, 365, 'ACT/365') - .1) < 1e-12\n",
        encoding="utf-8",
    )
    for path, basis, divisor in ((first, "BUS/252", 252), (second, "ACT/ACT", 365.25)):
        path.write_text(
            "from core.annualize import periods_per_year_for_basis\n"
            "def test_basis():\n"
            f"    assert periods_per_year_for_basis(basis='{basis}') == {divisor}\n",
            encoding="utf-8",
        )
    combined = tmp_path / ".coverage.integration"
    first_file, second_file = tmp_path / ".coverage.first", tmp_path / ".coverage.second"
    for target, destination in ((seed, combined), (first, first_file), (second, second_file)):
        result = _run_gate(target, coverage_file=destination)
        assert result.returncode == 0, result.stdout + result.stderr
    prior, first_lines, second_lines = map(_coverage_lines, (combined, first_file, second_file))
    source = next(filename for filename in prior if filename.replace("\\", "/").endswith("/core/annualize.py"))
    assert first_lines[source] != second_lines[source]
    assert prior[source] - (first_lines[source] | second_lines[source])

    result = _run_gate((first, second), coverage_file=combined)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 contract(s) across 2 target(s)" in result.stdout
    appended = _coverage_lines(combined)
    for filename in prior.keys() | first_lines.keys() | second_lines.keys():
        expected = prior.get(filename, set()) | first_lines.get(filename, set()) | second_lines.get(filename, set())
        assert expected <= appended.get(filename, set()), filename


@pytest.mark.parametrize("case", ["skipped", "failed", "empty", "nonzero", "selector"])
def test_coverage_collection_cannot_turn_incomplete_or_failed_contracts_green(tmp_path: Path, case: str) -> None:
    sources = {
        "skipped": "import pytest\ndef test_contract():\n    pytest.skip('no database')\n",
        "failed": "def test_contract():\n    assert False\n",
        "empty": "# no contracts\n",
        "nonzero": "def test_contract():\n    assert True\n",
        "selector": TARGET_SOURCE,
    }
    expected = {
        "skipped": "skipped",
        "failed": "failure(s)",
        "empty": "no PostgreSQL contracts",
        "nonzero": "pytest exited 2",
        "selector": "failure(s)",
    }
    target = tmp_path / "test_contracts.py"
    target.write_text(sources[case], encoding="utf-8")
    if case == "nonzero":
        (tmp_path / "conftest.py").write_text(
            "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 2\n", encoding="utf-8"
        )
    environment = {"PYTEST_ADDOPTS": "-k test_contract_that_passes"} if case == "selector" else None
    result = _run_gate(target, environment, coverage_file=tmp_path / ".coverage.integration")
    assert result.returncode == 1, result.stdout + result.stderr
    assert expected[case] in result.stdout
