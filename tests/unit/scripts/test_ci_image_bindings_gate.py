from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import ci_image_bindings_gate as gate

RUNTIME = "public.ecr.aws/docker/library/python@sha256:" + "a" * 64
POSTGRES = "public.ecr.aws/docker/library/postgres@sha256:" + "b" * 64
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def fixed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    (tmp_path / "Dockerfile").write_text(f"FROM {RUNTIME} AS runtime\n", encoding="utf-8")
    return tmp_path


def test_runtime_binding_accepts_matching_fixed_file_without_docker(fixed_files, mocker):
    run = mocker.patch.object(gate.subprocess, "run")
    assert gate.main(["--runtime-image", RUNTIME]) == 0
    run.assert_not_called()


@pytest.mark.parametrize("image", ["", "python:3.11", RUNTIME[:-1], RUNTIME + "\n"])
def test_runtime_binding_refuses_empty_mutable_or_malformed_output(fixed_files, image):
    assert gate.main(["--runtime-image", image]) == 1


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
        return_value=SimpleNamespace(
            stdout=json.dumps({"services": {"performance-lineage-db": {"image": POSTGRES, "platform": "linux/amd64"}}})
        ),
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
        return_value=SimpleNamespace(stdout=json.dumps({"services": {"performance-lineage-db": service}})),
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
            assert "postgres16-admission" not in jobs
            assert "exact-revision-assertion" in jobs["python-admission"]["needs"]
    for workflow, job in (
        ("pr-merge-gate.yml", "postgres-contracts"),
        ("performance-characterization.yml", "characterization"),
    ):
        jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]
        assert "postgres16-admission" in jobs[job]["needs"]
        service = jobs[job]["services"]["postgres"]
        assert service["image"] == "${{ needs.postgres16-admission.outputs.image }}"
        assert "--platform linux/amd64" in service["options"]


def test_admission_uses_qualified_policy_before_emitting_output():
    workflow = yaml.safe_load((ROOT / ".github/workflows/pr-merge-gate.yml").read_text())
    job = workflow["jobs"]["python-admission"]
    assert "services" not in job
    checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v6")
    assert checkout["with"]["ref"] == "386b40e13e76e60e761c6c4068fbe7a11256ca29"
    admission = next(step for step in job["steps"] if step.get("id") == "admission")
    assert "--verify-distribution" in admission["run"] and "--github-output" in admission["run"]
    assert job["outputs"]["image"] == "${{ steps.admission.outputs.image }}"
