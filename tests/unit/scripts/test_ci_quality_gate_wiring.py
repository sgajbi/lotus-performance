from __future__ import annotations

import os
import re
import shlex
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from scripts import ci_image_bindings_gate as image_bindings

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
    assert (
        "docker.io/library/postgres@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d" in workflow
    )
    assert "needs.postgres16-admission.outputs.image" in workflow
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

    assert "$(CONTAINER_IMAGE)" in docker_build_target
    assert "--target $(CONTAINER_BUILD_TARGET)" in docker_build_target
    assert "CONTAINER_BUILD_TARGET ?= runtime" in (ROOT / "Makefile").read_text(encoding="utf-8")
    # Each argument must be passed *and* shell-quoted. The previous form pinned the
    # raw `$(VAR)` expansion, so it would have gone on passing while a branch name
    # containing `;` or a backtick became part of the recipe syntax rather than data
    # (#511). Requiring `$(call shellquote,...)` makes the pin state the property it
    # was standing in for.
    for build_arg, variable in (
        ("PYTHON_BASE_IMAGE", "RUNTIME_BASE_IMAGE"),
        ("APP_VERSION", "CONTAINER_SERVICE_VERSION"),
        ("APP_GIT_COMMIT_SHA", "CONTAINER_GIT_SHA"),
        ("APP_GIT_BRANCH", "CONTAINER_GIT_BRANCH"),
        ("APP_BUILD_TIMESTAMP", "CONTAINER_BUILD_TIMESTAMP"),
        ("APP_REPOSITORY_URL", "CONTAINER_REPOSITORY_URL"),
        ("APP_IMAGE_DIGEST", "CONTAINER_IMAGE_DIGEST"),
        ("APP_CI_PIPELINE_RUN_ID", "CONTAINER_CI_PIPELINE_RUN_ID"),
    ):
        expected = f"--build-arg {build_arg}=$(call shellquote,$({variable}))"
        assert expected in docker_build_target, f"{build_arg} is not passed shell-quoted"


@pytest.mark.parametrize("runtime", [image_bindings.DEFAULT_RUNTIME_IMAGE, image_bindings.ORIGINAL_RUNTIME_IMAGE])
@pytest.mark.parametrize("target", ["docker-build", "docker-up", "lineage-volume-recovery-smoke"])
def test_native_build_and_recovery_commands_carry_the_selected_image(runtime, target):
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target],
        cwd=ROOT,
        env=dict(os.environ, RUNTIME_BASE_IMAGE=runtime),
        capture_output=True,
        text=True,
        check=True,
    )
    tokens = shlex.split(result.stdout.replace("\\\n", " "))
    if target == "docker-build":
        assert "PYTHON_BASE_IMAGE=" + runtime in tokens
    elif target == "docker-up":
        assert "RUNTIME_BASE_IMAGE=" + runtime in tokens
    else:
        assert tokens[tokens.index("--runtime-image") + 1] == runtime
    if target != "lineage-volume-recovery-smoke":
        assert result.stdout.index("ci_image_bindings_gate.py") < result.stdout.index("docker ")


@pytest.mark.parametrize("origin", ["environment", "command-line"])
def test_native_binding_refuses_raw_hostile_values_before_build(tmp_path, origin):
    marker = tmp_path / "must-not-exist"
    hostile = f"$(shell echo expanded > {marker.as_posix()}); `echo injected`; '"
    arguments = ["make", "--no-print-directory", "runtime-image-bindings"]
    environment = dict(os.environ)
    environment.pop("RUNTIME_BASE_IMAGE", None)
    if origin == "environment":
        environment["RUNTIME_BASE_IMAGE"] = hostile
    else:
        arguments.append("RUNTIME_BASE_IMAGE=" + hostile)
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "qualified exact-source" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize("origin", ["environment", "command-line"])
def test_make_info_macro_is_not_expanded_before_guard_refusal(origin):
    marker = "ROOT664_RAW_EXPANSION_MARKER"
    hostile = f"$(info {marker})unapproved"
    arguments = ["make", "--no-print-directory", "runtime-image-bindings"]
    environment = dict(os.environ)
    environment.pop("RUNTIME_BASE_IMAGE", None)
    if origin == "environment":
        environment["RUNTIME_BASE_IMAGE"] = hostile
    else:
        arguments.append("RUNTIME_BASE_IMAGE=" + hostile)
    result = subprocess.run(arguments, cwd=ROOT, env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert "qualified exact-source" in result.stderr
    assert marker not in result.stdout.splitlines()
    assert hostile in result.stdout


@pytest.mark.parametrize("origin", ["default", "environment", "command-line"])
@pytest.mark.parametrize("runtime", [image_bindings.DEFAULT_RUNTIME_IMAGE, image_bindings.ORIGINAL_RUNTIME_IMAGE])
def test_native_binding_valid_controls_for_each_input_origin(origin, runtime):
    arguments = ["make", "--no-print-directory", "runtime-image-bindings"]
    environment = dict(os.environ)
    environment.pop("RUNTIME_BASE_IMAGE", None)
    expected = runtime
    if origin == "environment":
        environment["RUNTIME_BASE_IMAGE"] = runtime
    elif origin == "command-line":
        arguments.append("RUNTIME_BASE_IMAGE=" + runtime)
    else:
        expected = image_bindings.DEFAULT_RUNTIME_IMAGE
    result = subprocess.run(arguments, cwd=ROOT, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f'"runtime_image": "{expected}"' in result.stdout


def test_hosted_build_and_recovery_pass_trusted_admission_to_native_commands():
    for name in ("pr-merge-gate.yml", "main-releasability.yml"):
        jobs = yaml.safe_load(_workflow_text(name))["jobs"]
        for job, step_name in (
            ("container-supply-chain-evidence", "Build image and generate container evidence"),
            ("lineage-volume-recovery", "Prove non-root restart recovery"),
        ):
            step = next(step for step in jobs[job]["steps"] if step.get("name") == step_name)
            assert step["env"]["RUNTIME_BASE_IMAGE"] == "${{ needs.python-admission.outputs.image }}"
            steps = jobs[job]["steps"]
            parser = next(step for step in steps if step.get("name") == "Install binding parser")
            packages = tomllib.loads((ROOT / "poetry.lock").read_text())["package"]
            pinned = next(package["version"] for package in packages if package["name"] == "pyyaml")
            assert f"PyYAML=={pinned}" in parser["run"] and "--no-deps" in parser["run"]
            assert steps.index(parser) < next(
                i for i, candidate in enumerate(steps) if "ci_image_bindings_gate.py" in candidate.get("run", "")
            )
            acquisition = next(
                step for step in steps if step.get("name") == "Acquire selected runtime config and layers"
            )
            checkout = next(step for step in steps if step.get("name") == "Checkout qualified acquisition policy")
            assert checkout["with"]["ref"] == "df4da3bda773e9d0103b3a396d58110f49489ebc"
            assert checkout["with"]["persist-credentials"] is False
            assert acquisition["env"]["RUNTIME_IMAGE"] == "${{ needs.python-admission.outputs.image }}"
            assert acquisition["env"]["EXPECTED_SOURCE"] == "${{ github.sha }}"
            assert steps.index(checkout) < steps.index(acquisition) < steps.index(step)
            assert "--policy-root .image-policy" in acquisition["run"]
            artifact = next(step for step in steps if step.get("name") == "Preserve runtime acquisition evidence")
            assert artifact["if"] == "always()"
            assert artifact["with"]["path"] == "output/image-acquisition"


def _assert_original_pg17_recovery(jobs, artifact_name):
    admission = jobs["postgres17-admission"]
    assert admission["steps"][0]["with"]["ref"] == image_bindings.RECOVERY_POLICY_REVISION
    selected = next(step for step in admission["steps"] if step.get("id") == "admission")
    assert (
        "--acquisition-source original" in selected["run"] and "--allow-original-source-fallback" not in selected["run"]
    )
    assert selected["env"]["SOURCE_IMAGE"] == image_bindings.RECOVERY_POSTGRES_IMAGE
    assert selected["env"]["DISTRIBUTION_IMAGE"] == image_bindings.RECOVERY_POSTGRES_IMAGE.replace(
        "docker.io", "public.ecr.aws/docker"
    )
    job = jobs["lineage-volume-recovery"]
    assert {"python-admission", "postgres17-admission"} <= set(job["needs"])
    assert not job.get("continue-on-error")
    steps = job["steps"]
    runtime_checkout = next(step for step in steps if step.get("name") == "Checkout qualified acquisition policy")
    assert runtime_checkout["with"]["ref"] == "df4da3bda773e9d0103b3a396d58110f49489ebc"
    assert runtime_checkout["with"]["path"] == ".image-policy"
    acquire = next(step for step in steps if step.get("name") == "Acquire selected runtime config and layers")
    runtime_upload = next(step for step in steps if step.get("name") == "Preserve runtime acquisition evidence")
    cleanup = next(step for step in steps if step.get("name") == "Remove verified runtime policy before build")
    policy = next(step for step in steps if step.get("name") == "Checkout qualified PG17 content policy")
    workload = next(step for step in steps if step.get("run") == "make lineage-volume-recovery-smoke")
    proof_upload = next(step for step in steps if step.get("with", {}).get("name") == artifact_name)
    assert [steps.index(step) for step in (acquire, runtime_upload, cleanup, policy, workload, proof_upload)] == sorted(
        steps.index(step) for step in (acquire, runtime_upload, cleanup, policy, workload, proof_upload)
    )
    assert (
        cleanup["run"]
        == 'python scripts/ci_image_bindings_gate.py --runtime-image "$RUNTIME_IMAGE" --remove-runtime-policy'
    )
    assert not cleanup.get("continue-on-error") and "if" not in cleanup
    assert policy["with"] == {
        "repository": "sgajbi/lotus-platform",
        "ref": image_bindings.RECOVERY_POLICY_REVISION,
        "persist-credentials": False,
        "path": "output/pg17-image-policy",
    }
    assert workload["env"] == {
        "RUNTIME_BASE_IMAGE": "${{ needs.python-admission.outputs.image }}",
        "RECOVERY_POSTGRES_IMAGE": "${{ needs.postgres17-admission.outputs.image }}",
    }
    assert not workload.get("continue-on-error") and "if" not in workload
    assert proof_upload["if"] == "always()" and proof_upload["with"]["path"] == "output/pg17-service-content.json"
    assert proof_upload["with"]["if-no-files-found"] == "error" and not proof_upload.get("continue-on-error")


@pytest.mark.parametrize(
    "workflow,artifact",
    [("pr-merge-gate.yml", "pr-pg17-service-content"), ("main-releasability.yml", "main-pg17-service-content")],
)
def test_original_pg17_recovery_wiring_preserves_policy_order_selection_and_mandatory_artifact(workflow, artifact):
    _assert_original_pg17_recovery(yaml.safe_load(_workflow_text(workflow))["jobs"], artifact)


@pytest.mark.parametrize(
    "damage",
    [
        "pin",
        "selection",
        "dependency",
        "df4",
        "early-checkout",
        "late-checkout",
        "cleanup",
        "soft-cleanup",
        "policy-path",
        "dropped-selection",
        "optional-artifact",
        "missing-artifact",
    ],
)
def test_original_pg17_wiring_control_refuses_effective_contract_mutations(damage):
    jobs = yaml.safe_load(_workflow_text("pr-merge-gate.yml"))["jobs"]
    admission = jobs["postgres17-admission"]
    job = jobs["lineage-volume-recovery"]
    steps = job["steps"]
    policy = next(step for step in steps if step.get("name") == "Checkout qualified PG17 content policy")
    cleanup = next(step for step in steps if step.get("name") == "Remove verified runtime policy before build")
    upload = next(step for step in steps if step.get("with", {}).get("name") == "pr-pg17-service-content")
    if damage == "pin":
        admission["steps"][0]["with"]["ref"] = "main"
    elif damage == "selection":
        selected = next(step for step in admission["steps"] if step.get("id") == "admission")
        selected["run"] = selected["run"].replace("--acquisition-source original", "")
    elif damage == "dependency":
        job["needs"].remove("postgres17-admission")
    elif damage == "df4":
        next(step for step in steps if step.get("name") == "Checkout qualified acquisition policy")["with"]["ref"] = (
            image_bindings.RECOVERY_POLICY_REVISION
        )
    elif damage in {"early-checkout", "late-checkout"}:
        steps.remove(policy)
        steps.insert(0, policy) if damage == "early-checkout" else steps.append(policy)
    elif damage == "cleanup":
        steps.remove(cleanup)
    elif damage == "soft-cleanup":
        cleanup["continue-on-error"] = True
    elif damage == "policy-path":
        policy["with"]["path"] = ".pg17-image-policy"
    elif damage == "dropped-selection":
        next(step for step in steps if step.get("run") == "make lineage-volume-recovery-smoke")["env"].pop(
            "RECOVERY_POSTGRES_IMAGE"
        )
    elif damage == "optional-artifact":
        upload["with"]["if-no-files-found"] = "ignore"
    else:
        steps.remove(upload)
    with pytest.raises((AssertionError, StopIteration)):
        _assert_original_pg17_recovery(jobs, "pr-pg17-service-content")


def test_late_policy_checkout_is_excluded_from_git_and_docker_build_custody():
    assert "output/" in (ROOT / ".gitignore").read_text().splitlines()
    assert "output" in (ROOT / ".dockerignore").read_text().splitlines()
    for workflow in ("pr-merge-gate.yml", "main-releasability.yml"):
        jobs = yaml.safe_load(_workflow_text(workflow))["jobs"]
        for name in ("lineage-volume-recovery", "container-supply-chain-evidence"):
            steps = jobs[name]["steps"]
            upload = next(step for step in steps if step.get("name") == "Preserve runtime acquisition evidence")
            cleanup = next(step for step in steps if step.get("name") == "Remove verified runtime policy before build")
            build = next(
                step
                for step in steps
                if step.get("name")
                in {"Prove non-root restart recovery", "Build image and generate container evidence"}
            )
            assert steps.index(upload) < steps.index(cleanup) < steps.index(build)


@pytest.mark.parametrize("origin", ["environment", "command-line"])
def test_recovery_make_preserves_raw_postgres_values_until_pre_docker_refusal(origin):
    marker = "RECOVERY_RAW_EXPANSION_MUST_NOT_RUN"
    hostile = f"$(info {marker})unapproved"
    env = dict(os.environ)
    argv = ["make", "--no-print-directory", "lineage-volume-recovery-smoke"]
    if origin == "environment":
        env["RECOVERY_POSTGRES_IMAGE"] = hostile
    else:
        argv.append("RECOVERY_POSTGRES_IMAGE=" + hostile)
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "exact original PG17" in result.stderr
    assert marker not in result.stdout.splitlines() and hostile in result.stdout


@pytest.mark.parametrize("origin", ["default", "environment", "command-line"])
def test_recovery_make_passes_exact_original_postgres_argument_without_docker(origin):
    env = dict(os.environ)
    env.pop("RECOVERY_POSTGRES_IMAGE", None)
    argv = ["make", "--no-print-directory", "-n", "lineage-volume-recovery-smoke"]
    if origin == "environment":
        env["RECOVERY_POSTGRES_IMAGE"] = image_bindings.RECOVERY_POSTGRES_IMAGE
    elif origin == "command-line":
        argv.append("RECOVERY_POSTGRES_IMAGE=" + image_bindings.RECOVERY_POSTGRES_IMAGE)
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    tokens = shlex.split(result.stdout)
    assert tokens[tokens.index("--postgres-image") + 1] == image_bindings.RECOVERY_POSTGRES_IMAGE


def test_container_supply_chain_preserves_provenance_and_scan_artifacts():
    docker_build_target = _makefile_target_definition("docker-build")
    evidence_target = _makefile_target_definition("container-supply-chain-evidence")
    sbom_target = _makefile_target_definition("container-sbom")
    vulnerability_report_target = _makefile_target_definition("container-vulnerability-report")
    vulnerability_gate_target = _makefile_target_definition("container-vulnerability-gate")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
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
    # The evidence target reaches the build through both scanning targets rather than
    # naming it beside them: siblings can run concurrently under `make -j`, so a sibling
    # `docker-build` is not an ordering and a scan could hit a stale image of the same
    # tag. Reachability and the ordering itself are asserted in
    # `test_container_scan_composition.py`; what belongs here is that evidence still
    # produces both artifacts.
    assert "container-sbom" in evidence_target
    assert "container-vulnerability-report" in evidence_target
    assert "ghcr.io/aquasecurity/trivy@sha256:f5d0e600ecda7449e2a9b272805aef698631d3bb3f3a739a750de2c6819acdc9" in (
        ROOT / "Makefile"
    ).read_text(encoding="utf-8")
    assert "--platform linux/amd64" in docker_build_target
    assert "--format cyclonedx" in sbom_target
    assert "lotus-performance-image-sbom.cdx.json" in sbom_target
    assert "--format json" in vulnerability_report_target
    assert "lotus-performance-image-vulnerabilities.json" in vulnerability_report_target
    assert "--exit-code 0" in vulnerability_report_target
    # The verdict is no longer a Trivy exit code. Three separate scans previously stood
    # behind one answer -- the uploaded evidence, the acceptance validation and the
    # blocking decision -- so a database update between them could make the artifact omit
    # the finding that failed the job. The gate now reads the one scan the report target
    # produced and decides from it, which is why it depends on that target rather than
    # scanning again.
    assert "container-vulnerability-report" in vulnerability_gate_target
    assert "scripts/container_acceptance_gate.py" in vulnerability_gate_target
    assert "--ignore-unfixed" not in vulnerability_report_target, (
        "the retained artifact must contain the findings the gate acts on, including "
        "unfixable ones, or the evidence cannot answer why the job failed"
    )

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
    assert "BASE_SHA: ${{ github.event.pull_request.base.sha }}" in dispatcher
    assert 'git rev-list --reverse "$BASE_SHA..$MERGE_COMMIT_SHA"' in dispatcher
    assert 'dispatch_ref="main-releasability-${revision}"' in dispatcher
    assert '-f expected_sha="$revision"' in dispatcher
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

    Releasability evidence is immutable, so even a duplicate or backfill for the same revision must
    not cancel a run before it reaches a verdict.
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
    assert "cancel-in-progress: false" in "\n".join(
        concurrency_lines
    ), "A duplicate or backfill must not cancel the only verdict-bearing evaluation for a revision."
