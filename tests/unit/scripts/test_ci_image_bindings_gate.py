from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import ci_image_bindings_gate as gate

RUNTIME = gate.DEFAULT_RUNTIME_IMAGE
POSTGRES = gate.RECOVERY_POSTGRES_IMAGE
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def fixed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    for name in ("Dockerfile", "docker-compose.yml"):
        (tmp_path / name).write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("runtime", [RUNTIME, gate.ORIGINAL_RUNTIME_IMAGE])
def test_runtime_binding_accepts_qualified_selection_without_docker(fixed_files, mocker, runtime):
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", runtime]) == 0
    run.assert_not_called()


@pytest.mark.parametrize(
    "image",
    [
        "",
        "python:3.11",
        RUNTIME[:-1],
        RUNTIME + "\n",
        RUNTIME.replace("python@", "other@"),
        RUNTIME.replace("public.ecr.aws", "unapproved.example"),
        "$(shell touch marker)",
    ],
)
def test_runtime_binding_refuses_unqualified_output_before_docker(fixed_files, mocker, image):
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", image, "--postgres-image", POSTGRES]) == 1
    run.assert_not_called()


@pytest.mark.parametrize(
    "old,new",
    [
        ("FROM ${PYTHON_BASE_IMAGE} AS runtime", f"FROM {RUNTIME} AS runtime"),
        ('lotus.image.base.distribution="${PYTHON_BASE_IMAGE}"', f'lotus.image.base.distribution="{RUNTIME}"'),
        (
            f'org.opencontainers.image.base.digest="{gate.RUNTIME_DIGEST}"',
            'org.opencontainers.image.base.digest="sha256:wrong"',
        ),
        ("ARG APP_VERSION=", "ARG PYTHON_BASE_IMAGE=unapproved\nARG APP_VERSION="),
    ],
)
def test_runtime_binding_refuses_base_or_provenance_drift_before_docker(fixed_files, mocker, old, new):
    path = fixed_files / "Dockerfile"
    path.write_text(path.read_text().replace(old, new), encoding="utf-8")
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", gate.ORIGINAL_RUNTIME_IMAGE, "--postgres-image", POSTGRES]) == 1
    run.assert_not_called()


@pytest.mark.parametrize("keyword", ["arg", "aRg", "from", "FrOm"])
def test_case_insensitive_redefinitions_refuse_before_docker(fixed_files, mocker, keyword):
    path = fixed_files / "Dockerfile"
    instruction = (
        f"{keyword} PYTHON_BASE_IMAGE=unapproved" if keyword.lower() == "arg" else f"{keyword} {RUNTIME} AS extra"
    )
    path.write_text(path.read_text().replace("ARG APP_VERSION=", instruction + "\nARG APP_VERSION="), encoding="utf-8")
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", POSTGRES]) == 1
    assert run.call_count == 0


def test_comment_cannot_replace_actual_distribution_label(fixed_files, mocker):
    path = fixed_files / "Dockerfile"
    expected = 'lotus.image.base.distribution="${PYTHON_BASE_IMAGE}"'
    path.write_text(
        path.read_text().replace(expected, 'other.label="unrelated"') + "\n# " + expected + "\n", encoding="utf-8"
    )
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", POSTGRES]) == 1
    assert run.call_count == 0


@pytest.mark.parametrize(
    "damage",
    ["single-quoted-label", "env-assignment", "env-legacy", "env-multiple", "env-mixed-case", "multiple-arg-binding"],
)
def test_actual_provenance_rejects_literal_expansion_and_env_shadowing(fixed_files, mocker, damage):
    path = fixed_files / "Dockerfile"
    source = path.read_text()
    if damage == "single-quoted-label":
        source = source.replace(
            'lotus.image.base.distribution="${PYTHON_BASE_IMAGE}"',
            "lotus.image.base.distribution='${PYTHON_BASE_IMAGE}'",
        )
    else:
        instruction = {
            "env-assignment": "ENV PYTHON_BASE_IMAGE=unapproved",
            "env-legacy": "ENV PYTHON_BASE_IMAGE unapproved",
            "env-multiple": "ENV OTHER=valid PYTHON_BASE_IMAGE=unapproved",
            "env-mixed-case": "eNv PYTHON_BASE_IMAGE=unapproved",
            "multiple-arg-binding": "ARG OTHER=one PYTHON_BASE_IMAGE=unapproved",
        }[damage]
        source = source.replace("ARG APP_VERSION=", instruction + "\nARG APP_VERSION=")
    path.write_text(source, encoding="utf-8")
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME]) == 1
    assert run.call_count == 0


@pytest.mark.parametrize(
    "assignment", ['lotus.image.base.distribution="${PYTHON_BASE_IMAGE}"', 'lotus.image.base.distribution="unapproved"']
)
def test_duplicate_or_conflicting_actual_labels_refuse_before_docker(fixed_files, mocker, assignment):
    path = fixed_files / "Dockerfile"
    path.write_text(path.read_text() + "\nLABEL " + assignment + "\n", encoding="utf-8")
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", POSTGRES]) == 1
    assert run.call_count == 0


def resolved_compose(runtime=RUNTIME, postgres=None):
    return {
        "services": {
            "performance-analytics": {
                "build": {"target": "runtime", "platforms": ["linux/amd64"], "args": {"PYTHON_BASE_IMAGE": runtime}}
            },
            "performance-lineage-db": postgres
            if postgres is not None
            else {"image": POSTGRES, "platform": "linux/amd64"},
        }
    }


def test_runtime_binding_refuses_different_digest_before_docker(fixed_files, mocker):
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME[:-1] + "c", "--postgres-image", POSTGRES]) == 1
    run.assert_not_called()


def test_runtime_binding_refuses_missing_dockerfile(fixed_files):
    (fixed_files / "Dockerfile").unlink()
    assert gate.main(["--runtime-image", RUNTIME]) == 1


def test_recovery_binding_checks_resolved_fixed_compose_files(fixed_files, mocker):
    run = mocker.patch.object(
        gate.subprocess,
        "run",
        return_value=SimpleNamespace(stdout=json.dumps(resolved_compose())),
    )
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", POSTGRES]) == 0
    assert run.call_args.args[0] == [
        "docker",
        "--context",
        "default",
        "compose",
        "-f",
        str(fixed_files / "docker-compose.yml"),
        "-f",
        str(fixed_files / "docker-compose.lineage-recovery.yml"),
        "config",
        "--format",
        "json",
    ]
    assert run.call_args.kwargs["check"] is True
    assert run.call_args.kwargs["env"]["RUNTIME_BASE_IMAGE"] == RUNTIME
    assert run.call_args.kwargs["env"]["RECOVERY_POSTGRES_IMAGE"] == POSTGRES


@pytest.mark.parametrize(
    "service",
    [
        {},
        {"image": "postgres:17", "platform": "linux/amd64"},
        {"image": POSTGRES, "platform": "linux/arm64"},
        {"image": POSTGRES[:-1] + "c", "platform": "linux/amd64"},
    ],
)
def test_recovery_binding_refuses_missing_mutable_changed_or_wrong_platform(fixed_files, mocker, service):
    mocker.patch.object(
        gate.subprocess,
        "run",
        return_value=SimpleNamespace(stdout=json.dumps(resolved_compose(postgres=service))),
    )
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", POSTGRES]) == 1


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, ["docker"]), OSError("unavailable")])
def test_recovery_binding_refuses_unavailable_compose(fixed_files, mocker, error):
    mocker.patch.object(gate.subprocess, "run", side_effect=error)
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", POSTGRES]) == 1


def test_image_consumers_depend_on_their_admission_outputs():
    for workflow in ("pr-merge-gate.yml", "main-releasability.yml"):
        jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]
        recovery = jobs["lineage-volume-recovery"]
        assert {"python-admission", "postgres17-admission"} <= set(recovery["needs"])
        container = jobs["container-supply-chain-evidence"]
        assert {"coverage-gate", "python-admission", "trivy-admission"} <= set(container["needs"])
        build = next(
            step for step in container["steps"] if step.get("name") == "Build image and generate container evidence"
        )
        assert build["env"]["TRIVY_IMAGE"] == "${{ needs.trivy-admission.outputs.image }}"
        binding_index = next(
            i for i, step in enumerate(container["steps"]) if "ci_image_bindings_gate.py" in step.get("run", "")
        )
        build_index = container["steps"].index(build)
        assert binding_index < build_index
        if workflow == "main-releasability.yml":
            assert "exact-revision-assertion" in jobs["python-admission"]["needs"]
            assert "exact-revision-assertion" in jobs["postgres16-admission"]["needs"]
    for workflow, job in (
        ("pr-merge-gate.yml", "postgres-contracts"),
        ("main-releasability.yml", "postgres-contracts"),
        ("performance-characterization.yml", "characterization"),
    ):
        jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]
        assert "postgres16-admission" in jobs[job]["needs"]
        service = jobs[job]["services"]["postgres"]
        assert service["image"] == "${{ needs.postgres16-admission.outputs.image }}"
        assert "--platform linux/amd64" in service["options"]


def _assert_explicit_python_admission(job):
    assert "services" not in job
    checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v6")
    assert checkout["with"] == {
        "repository": "sgajbi/lotus-platform",
        "ref": gate.RECOVERY_POLICY_REVISION,
        "persist-credentials": False,
        "path": ".image-policy",
    }
    admission = next(step for step in job["steps"] if step.get("id") == "admission")
    assert "--verify-distribution" in admission["run"] and "--github-output" in admission["run"]
    assert "--acquisition-source original" in admission["run"]
    assert "--allow-original-source-fallback" not in admission["run"]
    assert admission["env"] == {"SOURCE_IMAGE": gate.ORIGINAL_RUNTIME_IMAGE, "DISTRIBUTION_IMAGE": RUNTIME}
    assert "--platform linux/amd64" in admission["run"]
    assert not admission.get("continue-on-error") and "if" not in admission
    assert job["outputs"]["image"] == "${{ steps.admission.outputs.image }}"


@pytest.mark.parametrize("workflow", ["pr-merge-gate.yml", "main-releasability.yml"])
def test_admission_uses_qualified_policy_before_emitting_output(workflow):
    job = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]["python-admission"]
    _assert_explicit_python_admission(job)


@pytest.mark.parametrize("damage", ["pin", "selection", "fallback", "source", "platform", "optional"])
def test_explicit_python_selection_refuses_contract_mutations(damage):
    job = yaml.safe_load((ROOT / ".github/workflows/pr-merge-gate.yml").read_text())["jobs"]["python-admission"]
    admission = next(step for step in job["steps"] if step.get("id") == "admission")
    if damage == "pin":
        job["steps"][0]["with"]["ref"] = "df4da3bda773e9d0103b3a396d58110f49489ebc"
    elif damage == "selection":
        admission["run"] = admission["run"].replace("--acquisition-source original", "")
    elif damage == "fallback":
        admission["run"] += " --allow-original-source-fallback"
    elif damage == "source":
        admission["env"]["SOURCE_IMAGE"] = RUNTIME
    elif damage == "platform":
        admission["run"] = admission["run"].replace("--platform linux/amd64", "--platform linux/arm64")
    else:
        admission["continue-on-error"] = True
    with pytest.raises(AssertionError):
        _assert_explicit_python_admission(job)


PG16_POLICY_REVISION = "f12dade6f294b8df5e236f4f49c117b81bed4cd6"
PG16_DIGEST = "sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d"
PG16_WORKFLOWS = [
    ("pr-merge-gate.yml", "postgres-contracts", "pr-pg16-service-content"),
    ("main-releasability.yml", "postgres-contracts", "main-pg16-service-content"),
    ("performance-characterization.yml", "characterization", "characterization-pg16-service-content"),
]


def _pg16_policy_checkout(steps):
    matches = [step for step in steps if step.get("with", {}).get("repository") == "sgajbi/lotus-platform"]
    assert len(matches) == 1
    checkout = matches[0]
    assert checkout["uses"] == "actions/checkout@v6"
    assert checkout["with"] == {
        "repository": "sgajbi/lotus-platform",
        "ref": PG16_POLICY_REVISION,
        "persist-credentials": False,
        "path": ".image-policy",
    }
    return steps.index(checkout)


def _assert_pg16_service_proof(jobs, consumer, artifact):
    import shlex

    admission = jobs["postgres16-admission"]
    assert "services" not in admission
    _pg16_policy_checkout(admission["steps"])
    selected = next(step for step in admission["steps"] if step.get("id") == "admission")
    assert selected["env"] == {
        "SOURCE_IMAGE": "docker.io/library/postgres@" + PG16_DIGEST,
        "DISTRIBUTION_IMAGE": "public.ecr.aws/docker/library/postgres@" + PG16_DIGEST,
    }
    assert shlex.split(selected["run"]) == [
        "python",
        ".image-policy/automation/validate_technology_governance_policy.py",
        "--source-image",
        "$SOURCE_IMAGE",
        "--distribution-image",
        "$DISTRIBUTION_IMAGE",
        "--platform",
        "linux/amd64",
        "--verify-distribution",
        "--github-output",
        "$GITHUB_OUTPUT",
        "--acquisition-source",
        "original",
        "--acquisition-evidence",
        "$RUNNER_TEMP/image-acquisition-evidence",
    ]
    assert admission["outputs"]["image"] == "${{ steps.admission.outputs.image }}"
    job = jobs[consumer]
    assert "postgres16-admission" in job["needs"]
    assert not job.get("continue-on-error") and "if" not in job
    service = job["services"]["postgres"]
    assert service["image"] == "${{ needs.postgres16-admission.outputs.image }}"
    assert service["env"] == {
        "POSTGRES_DB": "lotus_performance",
        "POSTGRES_PASSWORD": "lotus",
        "POSTGRES_USER": "lotus",
    }
    assert service["ports"] == ["5432:5432"]
    assert shlex.split(service["options"]) == [
        "--platform",
        "linux/amd64",
        "--health-cmd",
        "pg_isready -U lotus -d lotus_performance",
        "--health-interval",
        "10s",
        "--health-timeout",
        "5s",
        "--health-retries",
        "10",
    ]
    steps = job["steps"]
    checkout_index = _pg16_policy_checkout(steps)
    setup_index = next(i for i, step in enumerate(steps) if step.get("uses") == "actions/setup-python@v6")
    proof = next(step for step in steps if step.get("name") == "Verify existing PG16 service content")
    proof_index = steps.index(proof)
    assert max(checkout_index, setup_index) < proof_index
    assert not proof.get("continue-on-error") and "if" not in proof
    assert proof["env"] == {
        "SERVICE_ID": "${{ job.services.postgres.id }}",
        "SELECTED_IMAGE": "${{ needs.postgres16-admission.outputs.image }}",
        "POLICY_COMMIT": PG16_POLICY_REVISION,
    }
    assert shlex.split(proof["run"]) == [
        "python",
        ".image-policy/automation/verify_acquired_service_image.py",
        "--container-id",
        "$SERVICE_ID",
        "--expected-image",
        "$SELECTED_IMAGE",
        "--expected-policy-commit",
        "$POLICY_COMMIT",
        "--output",
        "$RUNNER_TEMP/pg16-service-content.json",
    ]
    upload = next(step for step in steps if step.get("with", {}).get("name") == artifact)
    assert steps.index(upload) == proof_index + 1 and upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"]["path"] == "${{ runner.temp }}/pg16-service-content.json"
    assert upload["with"]["if-no-files-found"] == "error"
    assert not upload.get("continue-on-error") and "if" not in upload
    workloads = (
        ["make postgres-concurrency-contracts-gate"]
        if consumer == "postgres-contracts"
        else [
            "make performance-characterization",
            "python scripts/run_performance_characterization.py --mode postgres --require-non-skipped",
        ]
    )
    for command in ["make install-ci", *workloads]:
        step = next(step for step in steps if step.get("run") == command)
        assert steps.index(upload) < steps.index(step)
        assert not step.get("continue-on-error") and "if" not in step


@pytest.mark.parametrize("workflow,consumer,artifact", PG16_WORKFLOWS)
def test_pg16_original_selection_and_same_runner_proof_are_blocking(workflow, consumer, artifact):
    jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]
    _assert_pg16_service_proof(jobs, consumer, artifact)


@pytest.mark.parametrize("workflow,consumer,artifact", PG16_WORKFLOWS)
@pytest.mark.parametrize(
    "damage",
    [
        "policy",
        "selection",
        "dependency",
        "service-image",
        "service-id",
        "helper-commit",
        "late-proof",
        "soft-proof",
        "optional-artifact",
        "health",
        "workload",
        "fallback",
    ],
)
def test_pg16_wiring_guard_refuses_mutated_effective_contract(workflow, consumer, artifact, damage):
    jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]
    admission = jobs["postgres16-admission"]
    job = jobs[consumer]
    steps = job["steps"]
    proof = next(step for step in steps if step.get("name") == "Verify existing PG16 service content")
    upload = next(step for step in steps if step.get("with", {}).get("name") == artifact)
    if damage == "policy":
        admission["steps"][0]["with"]["ref"] = "df4da3bda773e9d0103b3a396d58110f49489ebc"
    elif damage == "selection":
        selected = next(step for step in admission["steps"] if step.get("id") == "admission")
        selected["run"] = selected["run"].replace("--acquisition-source original", "")
    elif damage == "dependency":
        job["needs"].remove("postgres16-admission")
    elif damage == "service-image":
        job["services"]["postgres"]["image"] = "postgres:16"
    elif damage == "service-id":
        proof["env"]["SERVICE_ID"] = "${{ job.services.unrelated.id }}"
    elif damage == "helper-commit":
        proof["env"]["POLICY_COMMIT"] = "main"
    elif damage == "late-proof":
        steps.remove(proof)
        steps.append(proof)
    elif damage == "soft-proof":
        proof["continue-on-error"] = True
    elif damage == "optional-artifact":
        upload["with"]["if-no-files-found"] = "ignore"
    elif damage == "health":
        job["services"]["postgres"]["options"] = "--platform linux/amd64"
    elif damage == "workload":
        command = (
            "make postgres-concurrency-contracts-gate"
            if consumer == "postgres-contracts"
            else ("python scripts/run_performance_characterization.py --mode postgres --require-non-skipped")
        )
        next(step for step in steps if step.get("run") == command)["continue-on-error"] = True
    else:
        selected = next(step for step in admission["steps"] if step.get("id") == "admission")
        selected["run"] += " --allow-original-source-fallback"
    with pytest.raises((AssertionError, StopIteration)):
        _assert_pg16_service_proof(jobs, consumer, artifact)


@pytest.mark.parametrize("runtime", [RUNTIME, gate.ORIGINAL_RUNTIME_IMAGE])
def test_resolved_recovery_binds_same_selection_and_discards_hostile_overrides(
    fixed_files, mocker, monkeypatch, runtime
):
    monkeypatch.setenv("RUNTIME_BASE_IMAGE", "hostile")
    monkeypatch.setenv("COMPOSE_FILE", "hostile.yml")
    monkeypatch.setenv("DOCKER_HOST", "tcp://hostile:2375")
    run = mocker.patch.object(
        gate.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(resolved_compose(runtime)))
    )
    assert gate.main(["--runtime-image", runtime, "--postgres-image", POSTGRES]) == 0
    env = run.call_args.kwargs["env"]
    assert env["RUNTIME_BASE_IMAGE"] == runtime
    assert "COMPOSE_FILE" not in env and "DOCKER_HOST" not in env


def test_resolved_recovery_refuses_dropped_runtime_selection(fixed_files, mocker):
    mocker.patch.object(gate.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(resolved_compose())))
    assert gate.main(["--runtime-image", gate.ORIGINAL_RUNTIME_IMAGE, "--postgres-image", POSTGRES]) == 1


@pytest.mark.parametrize("change", ["missing", "platform", "fixed-image"])
def test_source_compose_refuses_selection_or_platform_drift_before_docker(fixed_files, mocker, change):
    path = fixed_files / "docker-compose.yml"
    compose = yaml.safe_load(path.read_text())
    build = compose["x-provenance-build"]
    if change == "missing":
        build["args"].pop("PYTHON_BASE_IMAGE")
    elif change == "platform":
        build["platforms"] = ["linux/arm64"]
    else:
        build["args"]["PYTHON_BASE_IMAGE"] = RUNTIME
    path.write_text(yaml.safe_dump(compose), encoding="utf-8")
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", POSTGRES]) == 1
    run.assert_not_called()


@pytest.mark.parametrize(
    "image", ["", "postgres:17", POSTGRES.replace("docker.io", "public.ecr.aws/docker"), POSTGRES[:-1] + "0", RUNTIME]
)
def test_recovery_postgres_selection_refuses_unapproved_sources_before_docker(fixed_files, mocker, image):
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME, "--postgres-image", image]) == 1
    run.assert_not_called()


@pytest.fixture
def runtime_policy_checkout(fixed_files, monkeypatch):
    acquisition = gate.runtime_acquisition_module()
    monkeypatch.setattr(acquisition, "ROOT", fixed_files)
    policy = fixed_files / ".image-policy"
    policy.mkdir()
    (policy / "owned-marker").write_text("owned")
    state = {
        "root": str(policy),
        "head": acquisition.POLICY_REVISION,
        "policy_status": "",
        "source_status": "",
        "blob": "a" * 40,
    }

    def command(argv, **_kwargs):
        if "-C" not in argv:
            return state["source_status"]
        if "--show-toplevel" in argv:
            return state["root"]
        if "status" in argv:
            return state["policy_status"]
        if "hash-object" in argv:
            return state["blob"]
        if any(argument.startswith("HEAD:") for argument in argv):
            return "a" * 40
        return state["head"]

    monkeypatch.setattr(acquisition, "command", command)
    return policy, state


def test_verified_policy_cleanup_removes_only_owned_checkout_and_preserves_foreign_files(runtime_policy_checkout):
    policy, _ = runtime_policy_checkout
    foreign = policy.parent / "foreign-policy"
    foreign.mkdir()
    (foreign / "marker").write_bytes(b"foreign bytes")
    gate.remove_owned_runtime_policy()
    assert not policy.exists()
    assert (foreign / "marker").read_bytes() == b"foreign bytes"


@pytest.mark.parametrize("damage", ["root", "head", "policy_status", "blob"])
def test_policy_cleanup_refuses_foreign_wrong_dirty_or_modified_identity(runtime_policy_checkout, damage):
    policy, state = runtime_policy_checkout
    state[damage] = str(policy.parent) if damage == "root" else "untrusted"
    with pytest.raises(ValueError):
        gate.remove_owned_runtime_policy()
    assert (policy / "owned-marker").read_text() == "owned"


@pytest.mark.parametrize("kind", ["symlink", "reparse"])
def test_policy_cleanup_refuses_reparse_targets_before_recursive_action(runtime_policy_checkout, monkeypatch, kind):
    policy, _ = runtime_policy_checkout
    foreign = policy.parent / "foreign"
    foreign.mkdir()
    (foreign / "marker").write_bytes(b"foreign")
    if kind == "symlink":
        (policy / "owned-marker").unlink()
        policy.rmdir()
        policy.symlink_to(foreign, target_is_directory=True)
    else:
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            observed = original(path, *args, **kwargs)
            return SimpleNamespace(st_mode=observed.st_mode, st_file_attributes=0x400) if path == policy else observed

        monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError, match="reparse"):
        gate.remove_owned_runtime_policy()
    assert (foreign / "marker").read_bytes() == b"foreign"
    assert policy.exists()


@pytest.mark.parametrize("key", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT"])
def test_policy_cleanup_refuses_inherited_git_redirection(runtime_policy_checkout, monkeypatch, key):
    policy, _ = runtime_policy_checkout
    monkeypatch.setenv(key, "untrusted")
    with pytest.raises(ValueError, match="Git overrides"):
        gate.remove_owned_runtime_policy()
    assert (policy / "owned-marker").read_text() == "owned"


def test_policy_cleanup_fails_build_custody_when_other_source_is_dirty(runtime_policy_checkout):
    policy, state = runtime_policy_checkout
    state["source_status"] = " M app/foreign.py\x00"
    with pytest.raises(ValueError, match="Build source is not clean"):
        gate.remove_owned_runtime_policy()
    assert not policy.exists()


def test_policy_owner_path_refuses_arbitrary_relative_or_absolute_roots(fixed_files):
    for relative in ("../foreign", str(fixed_files), "foreign-policy"):
        with pytest.raises(ValueError, match="not an owned checkout"):
            gate.owned_policy_directory(relative)
