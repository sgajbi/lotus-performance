from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _makefile_target_definition(target: str) -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    prefix = f"{target}:"
    start = next(index for index, line in enumerate(lines) if line.startswith(prefix))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break
        block.append(line)
    return "\n".join(block)


def _workflow_text(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_quality_evaluation_gate_is_repo_native_blocking_target() -> None:
    assert "quality-evaluation-gate" in _makefile_target_definition("check")
    assert "quality-evaluation-gate" in _makefile_target_definition("ci")
    assert "$(MAKE) demo-api-certification" in _makefile_target_definition("quality-evaluation-gate")
    assert "$(MAKE) quality-test-taxonomy-gate" in _makefile_target_definition("quality-evaluation-gate")


def test_test_taxonomy_quality_gate_has_ci_thresholds() -> None:
    target = _makefile_target_definition("quality-test-taxonomy-gate")

    assert "scripts/python_test_taxonomy_inventory.py" in target
    assert "--min-api-runtime-tests 607" in target
    assert "--min-contract-governance-tests 111" in target
    assert "--max-uncategorized-tests 1148" in target


def test_contract_security_workflows_enforce_domain_and_evaluation_gates() -> None:
    for workflow_name in ["feature-lane.yml", "pr-merge-gate.yml", "main-releasability.yml"]:
        workflow = _workflow_text(workflow_name)

        assert "repository: sgajbi/lotus-platform" in workflow
        assert "path: .lotus-platform" in workflow
        assert "run: make domain-product-validate" in workflow
        assert "run: make quality-evaluation-gate" in workflow


def test_quality_baseline_snapshot_does_not_soft_fail_evaluation() -> None:
    workflow = _workflow_text("quality-baseline.yml")

    assert "run: make quality-evaluation-gate" in workflow
    assert "continue-on-error" not in workflow


def test_lint_gate_enforces_github_action_runtime_guard() -> None:
    lint_target = _makefile_target_definition("lint")

    assert "$(MAKE) github-action-runtime-guard" in lint_target


def test_test_and_coverage_workflows_use_repo_native_make_targets() -> None:
    feature_lane = _workflow_text("feature-lane.yml")
    pr_merge_gate = _workflow_text("pr-merge-gate.yml")
    main_releasability = _workflow_text("main-releasability.yml")

    assert "run: make test-unit" in feature_lane
    for workflow in (pr_merge_gate, main_releasability):
        assert "run: make test-coverage-shard SUITE=${{ matrix.suite }} TEST_PATH=${{ matrix.path }}" in workflow
        assert (
            "run: make coverage-combine-gate COVERAGE_INPUTS=coverage-data "
            "COVERAGE_FAIL_UNDER=${{ env.COVERAGE_FAIL_UNDER }}"
        ) in workflow

    governed_workflow_text = "\n".join([feature_lane, pr_merge_gate, main_releasability])
    assert "run: python -m pytest" not in governed_workflow_text
    assert "run: python -m coverage" not in governed_workflow_text
