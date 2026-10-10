"""Exercise PR/main proof parity, required aggregation and real coverage artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import yaml
from coverage import CoverageData

from scripts import ci_coverage_evidence as gate
from scripts.postgres_concurrency_contracts_gate import DEFAULT_TARGETS

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI_EVIDENCE_SHA", "a" * 40)
    monkeypatch.setenv("CI_EVIDENCE_RUN", "100-1")


def artifacts(root: Path) -> None:
    for index, shard in enumerate(gate.REQUIRED_SHARDS):
        directory = root / f"coverage-data-{shard}"
        directory.mkdir(parents=True)
        data = CoverageData(basename=str(directory / f".coverage.{shard}"))
        data.add_lines({str(ROOT / "core/annualize.py"): {index + 1}})
        data.write()
        gate.stamp(shard, directory)


def test_four_separate_shards_merge_without_losing_any_measurement(tmp_path: Path, identity: None) -> None:
    artifacts(tmp_path)
    gate.verify(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "coverage", "combine", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            **{key: value for key, value in os.environ.items() if not key.startswith("COV_CORE_")},
            "COVERAGE_FILE": str(tmp_path / ".coverage"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined = CoverageData(basename=str(tmp_path / ".coverage"))
    combined.read()
    assert combined.lines(str(ROOT / "core/annualize.py")) == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "bad", ["missing", "empty", "corrupt", "stale", "revision", "suite", "changed", "misnamed", "duplicate", "no-lines"]
)
def test_incomplete_or_stale_coverage_cannot_enter_combiner(tmp_path: Path, identity: None, bad: str) -> None:
    artifacts(tmp_path)
    path = tmp_path / "coverage-data-postgres/.coverage.postgres"
    if bad == "missing":
        path.unlink()
    elif bad in {"empty", "corrupt"}:
        path.write_bytes(b"" if bad == "empty" else b"not SQLite")
    elif bad in {"stale", "revision", "suite", "changed"}:
        manifest = path.with_name(path.name + ".json")
        data = json.loads(manifest.read_text())
        field = {"stale": "CI_EVIDENCE_RUN", "revision": "CI_EVIDENCE_SHA", "suite": "shard", "changed": "sha256"}
        data[field[bad]] = "99-1"
        manifest.write_text(json.dumps(data))
    elif bad == "misnamed":
        path.rename(path.with_name(".coverage.wrong"))
    elif bad == "duplicate":
        (tmp_path / ".coverage.postgres").write_bytes(path.read_bytes())
    else:
        path.unlink()
        data = CoverageData(basename=str(path))
        data.add_lines({"empty.py": set()})
        data.write()
    with pytest.raises((ValueError, gate.CoverageException)):
        gate.verify(tmp_path)
    assert not (tmp_path / ".coverage.unit").exists(), "No partial accepted inventory may be staged"


@pytest.mark.parametrize("dependency", ["test-suites", "postgres-contracts"])
@pytest.mark.parametrize("state", ["failure", "skipped", "cancelled", "timed_out", "missing", "success"])
@pytest.mark.parametrize("workflow_name", ["pr-merge-gate.yml", "main-releasability.yml"])
def test_shipped_required_aggregate_command_fails_closed(state: str, dependency: str, workflow_name: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows" / workflow_name).read_text())
    aggregate = workflow["jobs"]["coverage-gate"]
    assert aggregate["needs"] == ["test-suites", "postgres-contracts"]
    assert aggregate["if"] == "${{ always() }}"
    step = next(step for step in aggregate["steps"] if step.get("run") == "make ci-proof-results-gate")
    assert step["env"]["CI_PROOF_RESULTS"] == "${{ toJSON(needs) }}"
    results = {"test-suites": {"result": "success"}, "postgres-contracts": {"result": "success"}}
    results[dependency]["result"] = state
    if state == "missing":
        del results[dependency]
    environment = {**os.environ, "CI_PROOF_RESULTS": json.dumps(results)}
    # Execute the native recipe actually selected by the workflow, with the same
    # Python runtime as this test rather than another interpreter found on PATH.
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment["PATH"]
    result = subprocess.run(step["run"].split(), cwd=ROOT, env=environment, capture_output=True, text=True)
    assert (result.returncode == 0) is (state == "success"), result.stdout + result.stderr
    release = workflow["jobs"]["container-supply-chain-evidence"]
    assert release["needs"] == ["coverage-gate", "python-admission", "trivy-admission"] and "if" not in release


@pytest.mark.parametrize("workflow_name", ["pr-merge-gate.yml", "main-releasability.yml"])
def test_pg_and_matrix_are_independent_jobs_preserving_baseline_and_authority_proof(workflow_name: str) -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow_name).read_text())["jobs"]
    assert set(jobs["postgres-contracts"]["needs"]) == set(jobs["test-suites"]["needs"]) | {"postgres16-admission"}
    assert "services" not in jobs["test-suites"]
    assert (
        jobs["postgres-contracts"]["services"]["postgres"]["image"] == "${{ needs.postgres16-admission.outputs.image }}"
    )
    assert {item["suite"] for item in jobs["test-suites"]["strategy"]["matrix"]["include"]} == {
        "unit",
        "integration",
        "e2e",
    }
    assert len(DEFAULT_TARGETS) == 12 and len(set(DEFAULT_TARGETS)) == 12
    # Immutable baseline target-manifest digest from main e67ef6db. Works in the
    # shallow CI checkout, without creating a second editable selection list.
    assert sha256(json.dumps(DEFAULT_TARGETS[:9]).encode()).hexdigest() == (
        "395731955c4c369b5ad644c6d6567a8715be9d647f23c3c9ea66e66381ad76e9"
    )
    assert DEFAULT_TARGETS[9:] == (
        "tests/benchmarks/test_postgres_composite_authority.py",
        "tests/benchmarks/test_postgres_composite_authority_extended.py",
        "tests/benchmarks/test_postgres_composite_attribution.py",
    )


def _execution_contract(job: dict) -> dict:
    """Display labels differ by lane; every executable field must stay equivalent."""
    contract = deepcopy(job)
    contract.pop("name", None)
    for step in contract.get("steps", []):
        step.pop("name", None)
    return contract


def _assert_coverage_parity(pr: dict, main: dict) -> None:
    for key in ("COVERAGE_FAIL_UNDER", "CI_EVIDENCE_SHA", "CI_EVIDENCE_RUN"):
        assert main["env"][key] == pr["env"][key]
    for name in ("test-suites", "postgres-contracts"):
        assert name in main["jobs"]
        assert _execution_contract(main["jobs"][name]) == _execution_contract(pr["jobs"][name])
    admission = deepcopy(main["jobs"]["postgres16-admission"])
    assert admission.pop("needs") == ["exact-revision-assertion"]
    assert admission == pr["jobs"]["postgres16-admission"]
    expected = pr["jobs"]["coverage-gate"]
    aggregate = main["jobs"]["coverage-gate"]
    assert aggregate["needs"] == expected["needs"] and aggregate["if"] == expected["if"]
    # Main additionally retains the verified combined artifact. All proof/merge
    # steps must execute in exactly PR order, before that evidence publication.
    assert _execution_contract(aggregate)["steps"][:-1] == _execution_contract(expected)["steps"]
    assert aggregate["steps"][-1]["uses"] == "actions/upload-artifact@v7"
    assert aggregate["steps"][-1]["with"]["if-no-files-found"] == "error"


def test_main_and_pr_execute_identical_coverage_cohorts_and_provenance() -> None:
    pr = yaml.safe_load((ROOT / ".github/workflows/pr-merge-gate.yml").read_text())
    main = yaml.safe_load((ROOT / ".github/workflows/main-releasability.yml").read_text())
    _assert_coverage_parity(pr, main)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-pg",
        "missing-manifest",
        "wrong-revision",
        "no-admission",
        "no-result-gate",
        "no-provenance",
        "merge-first",
        "flatten-first",
    ],
)
def test_coverage_parity_refuses_main_cohort_or_provenance_regressions(fault: str) -> None:
    pr = yaml.safe_load((ROOT / ".github/workflows/pr-merge-gate.yml").read_text())
    main = yaml.safe_load((ROOT / ".github/workflows/main-releasability.yml").read_text())
    aggregate = main["jobs"]["coverage-gate"]
    if fault == "missing-pg":
        del main["jobs"]["postgres-contracts"]
    elif fault == "missing-manifest":
        main["jobs"]["test-suites"]["steps"][-1]["with"]["path"] = ".coverage.${{ matrix.suite }}"
    elif fault == "wrong-revision":
        main["env"]["CI_EVIDENCE_SHA"] = "${{ github.event.pull_request.head.sha }}"
    elif fault == "no-admission":
        main["jobs"]["postgres-contracts"]["services"]["postgres"]["image"] = "postgres:16"
    elif fault in {"no-result-gate", "no-provenance"}:
        command = (
            "make ci-proof-results-gate"
            if fault == "no-result-gate"
            else "make coverage-evidence-gate COVERAGE_INPUTS=coverage-data"
        )
        aggregate["steps"] = [step for step in aggregate["steps"] if step.get("run") != command]
    elif fault == "merge-first":
        aggregate["steps"][-2], aggregate["steps"][-3] = aggregate["steps"][-3], aggregate["steps"][-2]
    else:
        download = next(step for step in aggregate["steps"] if step.get("name") == "Download coverage artifacts")
        download["run"] += "\nfind coverage-data -type f -exec cp {} coverage-data/ \\;"
    with pytest.raises(AssertionError):
        _assert_coverage_parity(pr, main)
