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
    assert "--min-api-runtime-tests 656" in target
    assert "--min-contract-governance-tests 131" in target
    assert "--max-uncategorized-tests 969" in target


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


def test_container_supply_chain_evidence_is_repo_native_and_published() -> None:
    docker_build_target = _makefile_target_definition("docker-build")
    evidence_target = _makefile_target_definition("container-supply-chain-evidence")
    sbom_target = _makefile_target_definition("container-sbom")
    vulnerability_report_target = _makefile_target_definition("container-vulnerability-report")
    vulnerability_gate_target = _makefile_target_definition("container-vulnerability-gate")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "$(CONTAINER_IMAGE)" in docker_build_target
    for build_arg in (
        "APP_VERSION=$(CONTAINER_SERVICE_VERSION)",
        "APP_GIT_COMMIT_SHA=$(CONTAINER_GIT_SHA)",
        "APP_GIT_BRANCH=$(CONTAINER_GIT_BRANCH)",
        "APP_BUILD_TIMESTAMP=$(CONTAINER_BUILD_TIMESTAMP)",
        "APP_REPOSITORY_URL=$(CONTAINER_REPOSITORY_URL)",
        "APP_IMAGE_DIGEST=$(CONTAINER_IMAGE_DIGEST)",
        "APP_CI_PIPELINE_RUN_ID=$(CONTAINER_CI_PIPELINE_RUN_ID)",
    ):
        assert f"--build-arg {build_arg}" in docker_build_target
    for label in (
        "org.opencontainers.image.source",
        "org.opencontainers.image.revision",
        "org.opencontainers.image.ref.name",
        "org.opencontainers.image.version",
        "org.opencontainers.image.created",
        "lotus.image.digest",
        "lotus.ci.pipeline_run_id",
    ):
        assert label in dockerfile
    assert "SECRET" not in dockerfile
    assert "PASSWORD" not in dockerfile
    assert "docker-build container-sbom container-vulnerability-report" in evidence_target
    assert "aquasec/trivy:0.71.2" in (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "--format cyclonedx" in sbom_target
    assert "lotus-performance-image-sbom.cdx.json" in sbom_target
    assert "--format json" in vulnerability_report_target
    assert "lotus-performance-image-vulnerabilities.json" in vulnerability_report_target
    assert "--exit-code 0" in vulnerability_report_target
    assert "--exit-code 1" in vulnerability_gate_target

    for workflow_name in ["pr-merge-gate.yml", "main-releasability.yml"]:
        workflow = _workflow_text(workflow_name)

        assert "CONTAINER_GIT_SHA: ${{ github.sha }}" in workflow
        assert "CONTAINER_GIT_BRANCH: ${{ github.ref_name }}" in workflow
        assert "CONTAINER_REPOSITORY_URL: ${{ github.server_url }}/${{ github.repository }}" in workflow
        assert "CONTAINER_CI_PIPELINE_RUN_ID: ${{ github.run_id }}" in workflow
        assert 'CONTAINER_BUILD_TIMESTAMP="$(date -u' in workflow
        assert "make container-supply-chain-evidence" in workflow
        assert "uses: actions/upload-artifact@v7" in workflow
        assert "path: output/container-security/*.json" in workflow
        assert "run: make docker-build" not in workflow

    main_releasability = _workflow_text("main-releasability.yml")
    assert "attestations: write" in main_releasability
    assert "id-token: write" in main_releasability
    assert "uses: actions/attest-build-provenance@v3" in main_releasability
    assert "subject-path: output/container-security/lotus-performance-image-sbom.cdx.json" in main_releasability


def test_auto_merge_uses_governed_merge_actor_token() -> None:
    workflow = _workflow_text("pr-auto-merge.yml")

    assert "GH_TOKEN: ${{ secrets.LOTUS_AUTOMERGE_TOKEN }}" in workflow
    assert "LOTUS_AUTOMERGE_TOKEN is not configured" in workflow
    assert "github.token" not in workflow
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "gh pr merge" in workflow
