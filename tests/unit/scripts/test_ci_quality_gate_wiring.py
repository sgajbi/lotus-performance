from __future__ import annotations

import re
from pathlib import Path

import yaml

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
    assert "--min-contract-governance-tests 136" in target
    # This asserts only that a ceiling is *declared*. Its value is owned by
    # tests/unit/scripts/test_test_taxonomy_classification.py, which compares it against the
    # measured tree. Repeating the literal here made every legitimate re-bank fail a test about
    # wiring, which is how a threshold ends up copied rather than measured. See issue #475.
    assert re.search(r"--max-uncategorized-tests \d+", target) is not None


def test_license_compliance_gate_is_repo_native_blocking_target() -> None:
    assert "license-compliance-gate" in _makefile_target_definition("check")
    assert "license-compliance-gate" in _makefile_target_definition("ci")
    assert "scripts/license_compliance_inventory.py --check" in _makefile_target_definition("license-compliance-gate")


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


def test_performance_characterization_evidence_workflow_is_repo_native() -> None:
    workflow = _workflow_text("performance-characterization.yml")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "scripts/run_performance_characterization.py --mode full" in _makefile_target_definition(
        "performance-characterization"
    )
    assert "scripts/run_performance_characterization.py --mode postgres --require-non-skipped" in (
        _makefile_target_definition("performance-characterization-postgres")
    )
    assert "LOTUS_POSTGRES_PLAN_DATABASE_URL" in workflow
    assert "services:" in workflow
    assert "postgres:16" in workflow
    assert "run: make performance-characterization" in workflow
    assert "run: python scripts/run_performance_characterization.py --mode postgres --require-non-skipped" in workflow
    assert "uses: actions/upload-artifact@v7" in workflow
    assert "output/performance-characterization/*" in workflow
    assert "continue-on-error" not in workflow
    assert "performance-characterization" in makefile


def test_lint_gate_enforces_github_action_runtime_guard() -> None:
    lint_target = _makefile_target_definition("lint")

    assert "$(MAKE) github-action-runtime-guard" in lint_target


def test_lint_gate_enforces_calculation_engine_version_guard() -> None:
    lint_target = _makefile_target_definition("lint")

    assert "$(MAKE) calculation-engine-version-gate" in lint_target
    assert "scripts/calculation_engine_version_gate.py" in _makefile_target_definition(
        "calculation-engine-version-gate"
    )


def test_migration_apply_uses_executable_schema_apply_not_prose_only() -> None:
    migration_apply_target = _makefile_target_definition("migration-apply")

    assert "scripts/durable_schema_apply.py" in migration_apply_target
    assert "scripts/migration_contract_check.py" not in migration_apply_target


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
    assert "--target $(CONTAINER_BUILD_TARGET)" in docker_build_target
    assert "CONTAINER_BUILD_TARGET ?= runtime" in (ROOT / "Makefile").read_text(encoding="utf-8")
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
    assert "requirements-dev.txt" not in dockerfile
    assert "USER lotus" in dockerfile
    assert "/health/live" in dockerfile
    assert "docker-build container-sbom container-vulnerability-report" in evidence_target
    assert "aquasec/trivy:0.71.2" in (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "--format cyclonedx" in sbom_target
    assert "lotus-performance-image-sbom.cdx.json" in sbom_target
    assert "--format json" in vulnerability_report_target
    assert "lotus-performance-image-vulnerabilities.json" in vulnerability_report_target
    assert "--exit-code 0" in vulnerability_report_target
    assert "--exit-code 1" in vulnerability_gate_target

    branch_identity_by_workflow = {
        "pr-merge-gate.yml": "${{ github.ref_name }}",
        "main-releasability.yml": "${{ inputs.expected_sha && 'main' || github.ref_name }}",
    }
    for workflow_name, branch_identity in branch_identity_by_workflow.items():
        workflow = _workflow_text(workflow_name)

        assert "CONTAINER_GIT_SHA: ${{ github.sha }}" in workflow
        assert f"CONTAINER_GIT_BRANCH: {branch_identity}" in workflow
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


def test_merged_pr_dispatch_binds_main_releasability_to_exact_sha() -> None:
    dispatcher = _workflow_text("merged-pr-main-releasability.yml")
    main_gate = _workflow_text("main-releasability.yml")

    assert "MERGE_COMMIT_SHA: ${{ github.event.pull_request.merge_commit_sha }}" in dispatcher
    assert 'dispatch_ref="main-releasability-${MERGE_COMMIT_SHA}"' in dispatcher
    assert '-f expected_sha="$MERGE_COMMIT_SHA"' in dispatcher
    assert "expected_sha:" in main_gate
    assert 'actual_sha="$(git rev-parse HEAD)"' in main_gate
    assert "inputs.expected_sha || github.sha" in main_gate
    assert "push:" not in main_gate.split("concurrency:", maxsplit=1)[0]
    parsed = yaml.safe_load(main_gate)
    roots = {name for name, job in parsed["jobs"].items() if name != "exact-revision-assertion" and "needs" not in job}
    assert roots == set()
    assert "CONTAINER_GIT_BRANCH: ${{ inputs.expected_sha && 'main' || github.ref_name }}" in main_gate


def test_main_releasability_concurrency_is_keyed_per_commit_not_per_branch() -> None:
    """A gate run must not be cancelled by a later commit.

    The group was keyed on `github.ref`. On `main` that ref is constant, so every run shared one
    group and `cancel-in-progress: true` cancelled runs validating *different* commits. The
    cancellation is silent - a cancelled run is not a failure - so a commit could lose its
    releasability evidence with nothing reporting it. Merge commit `5402692` lost two runs that way
    before this was found. See issue #481.

    `cancel-in-progress` stays `true` and is asserted here too: superseding an earlier attempt at the
    *same* revision is correct, and this fix must not be mistaken for disabling cancellation.
    """

    workflow = _workflow_text("main-releasability.yml")

    lines = workflow.splitlines()
    start = lines.index("concurrency:")
    concurrency_lines = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line.startswith((" ", "\t")):
            break
        concurrency_lines.append(line)

    # Read the `group:` value alone rather than the whole block. The workflow carries a comment
    # explaining why `github.ref` is wrong, and a substring search over the block matches that
    # explanation and fails for the wrong reason. A guard that cannot tell configuration from prose
    # about the configuration is not checking configuration.
    group_lines = [line for line in concurrency_lines if line.strip().startswith("group:")]
    assert len(group_lines) == 1, f"Expected exactly one `group:` line, got {group_lines}"
    group = group_lines[0].strip()

    assert "github.ref" not in group, (
        "The concurrency group is keyed on `github.ref`, which is constant on `main`, so a later "
        f"commit cancels the run validating an earlier one: {group}"
    )
    assert "github.sha" in group, f"The concurrency group must be keyed on the commit under validation: {group}"
    assert "cancel-in-progress: true" in "\n".join(concurrency_lines), (
        "Cancellation within a single revision is correct and must stay enabled; the defect was the "
        "grouping, not the cancellation."
    )
