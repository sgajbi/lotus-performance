from __future__ import annotations

import json
import subprocess
import sys

import pytest

import scripts.validate_lineage_volume_recovery as recovery
from scripts.validate_lineage_volume_recovery import (
    PROJECT_PREFIX,
    RECOVERY_COMPOSE_FILE,
    _captured_output,
    _wait_for_healthy_runtime,
    build_runtime_environment,
    cleanup_command,
    compose_command,
    new_project_name,
    run_validation,
    validate_project_name,
)

QUALIFY_POLICY = recovery.qualified_postgres_policy
PROVE_DATABASE = recovery.prove_owned_database


@pytest.fixture(autouse=True)
def isolated_content_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "POSTGRES_PROOF", tmp_path / "pg17-service-content.json")
    monkeypatch.setattr(recovery, "qualified_postgres_policy", lambda: tmp_path / "policy")
    monkeypatch.setattr(recovery, "prove_owned_database", lambda *_args: {"checked": True})


@pytest.mark.parametrize("exit_code", ["0", "1"])
def test_schema_owner_completion_is_required_for_recovery_proof(monkeypatch, exit_code):
    monkeypatch.setattr(recovery, "_capture", lambda *args, **kwargs: exit_code)
    if exit_code == "0":
        recovery._assert_schema_apply_succeeded("owned-schema-job", {})
    else:
        with pytest.raises(RuntimeError, match="durable schema owner exited with code 1"):
            recovery._assert_schema_apply_succeeded("owned-schema-job", {})


def test_validation_accepts_only_owned_disposable_project_names() -> None:
    project_name = f"{PROJECT_PREFIX}contract-1"

    assert validate_project_name(project_name.upper()) == project_name
    assert compose_command(project_name, "down", "-v")[-3:] == [
        project_name,
        "down",
        "-v",
    ]


def test_recovery_compose_command_removes_host_port_publication() -> None:
    command = compose_command(f"{PROJECT_PREFIX}contract-1", "config")
    compose_files = [command[index + 1] for index, value in enumerate(command) if value == "-f"]

    assert compose_files == [
        str(recovery.REPOSITORY_ROOT / "docker-compose.yml"),
        str(RECOVERY_COMPOSE_FILE),
    ]
    assert command[:4] == ["docker", "--context", "default", "compose"]
    assert "--project-directory" not in command
    assert "ports: !reset []" in RECOVERY_COMPOSE_FILE.read_text(encoding="utf-8")


def test_recovery_environment_rejects_hostile_compose_and_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery.os,
        "environ",
        {
            "PATH": "trusted-path",
            "SystemRoot": "C:\\Windows",
            "ProgramFiles": "C:\\Program Files",
            "USERPROFILE": "C:\\Users\\lotus",
            "LINEAGE_METADATA_DATABASE_URL": "postgresql://hostile/other-run",
            "PA_LINEAGE_DB_PORT": "15432",
            "PA_HOST_PORT": "18000",
            "DOCKER_HOST": "tcp://hostile:2375",
            "DOCKER_CONTEXT": "remote-shared-daemon",
            "COMPOSE_PROJECT_NAME": "hostile-project",
            "CORE_CONTROL_PLANE_BASE_URL": "https://hostile.example",
            "RUNTIME_BASE_IMAGE": "unapproved.example/python:latest",
            "RECOVERY_POSTGRES_IMAGE": "unapproved.example/postgres:latest",
            "GIT_DIR": "foreign-git-dir",
            "GIT_CONFIG_COUNT": "1",
        },
    )

    environment = build_runtime_environment(f"{PROJECT_PREFIX}contract-1")

    assert environment["LINEAGE_METADATA_DATABASE_URL"] == (
        "postgresql+psycopg://lotus:lotus@performance-lineage-db:5432/lotus_performance"
    )
    assert environment["PATH"] == "trusted-path"
    assert environment["SystemRoot"] == "C:\\Windows"
    assert environment["ProgramFiles"] == "C:\\Program Files"
    assert environment["USERPROFILE"] == "C:\\Users\\lotus"
    assert environment["RUNTIME_BASE_IMAGE"] == recovery.image_bindings.DEFAULT_RUNTIME_IMAGE
    assert environment["RECOVERY_POSTGRES_IMAGE"] == recovery.image_bindings.RECOVERY_POSTGRES_IMAGE
    assert not {
        "PA_LINEAGE_DB_PORT",
        "PA_HOST_PORT",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "COMPOSE_PROJECT_NAME",
        "CORE_CONTROL_PLANE_BASE_URL",
        "GIT_DIR",
        "GIT_CONFIG_COUNT",
    }.intersection(environment)


@pytest.mark.parametrize(
    "runtime",
    [
        recovery.image_bindings.DEFAULT_RUNTIME_IMAGE,
        recovery.image_bindings.ORIGINAL_RUNTIME_IMAGE,
    ],
)
def test_recovery_carries_explicit_selection_to_every_command_and_cleanup(monkeypatch, runtime):
    monkeypatch.setenv("RUNTIME_BASE_IMAGE", "hostile")
    commands = []
    monkeypatch.setattr(recovery, "_run", lambda command, **kwargs: commands.append((command, kwargs["env"])))
    monkeypatch.setattr(recovery, "_assert_initializer_succeeded", lambda *_args: None)
    monkeypatch.setattr(recovery, "_assert_schema_apply_succeeded", lambda *_args: None)
    monkeypatch.setattr(recovery, "_wait_for_healthy_runtime", lambda *_args: None)
    monkeypatch.setattr(recovery, "_assert_non_root_volume_access", lambda *_args: None)
    monkeypatch.setattr(
        recovery, "_cleanup_owned_project", lambda project, env: commands.append((["cleanup", project], env))
    )
    summary = run_validation(runtime)
    assert summary["runtime_image"] == runtime
    assert all(env["RUNTIME_BASE_IMAGE"] == runtime for _, env in commands)
    assert commands[0][0][-4:] == ["up", "-d", "--no-deps", recovery.DATABASE_SERVICE]
    assert all(env["RECOVERY_POSTGRES_IMAGE"] == recovery.image_bindings.RECOVERY_POSTGRES_IMAGE for _, env in commands)
    assert any(command[-2:] == ["build", "performance-lineage-volume-init"] for command, _ in commands)
    assert any("--build" in command for command, _ in commands)
    assert any("restart" in command for command, _ in commands)
    assert commands[-1][0][0] == "cleanup"


@pytest.mark.parametrize(
    "runtime", ["", "python:3.11", "$(shell echo injected)", recovery.image_bindings.ORIGINAL_RUNTIME_IMAGE[:-1] + "0"]
)
def test_recovery_refuses_invalid_selection_before_all_docker_and_cleanup(monkeypatch, runtime):
    calls = []
    monkeypatch.setattr(recovery, "_run", lambda *_args, **_kwargs: calls.append("run"))
    monkeypatch.setattr(recovery, "_capture", lambda *_args, **_kwargs: calls.append("capture"))
    monkeypatch.setattr(recovery, "_cleanup_owned_project", lambda *_args: calls.append("cleanup"))
    with pytest.raises(ValueError, match="qualified exact-source"):
        run_validation(runtime)
    assert calls == []


def test_recovery_project_name_is_random_and_cleanup_keeps_shared_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery.secrets, "token_hex", lambda _: "owned123")

    assert new_project_name() == f"{PROJECT_PREFIX}owned123"
    assert cleanup_command(f"{PROJECT_PREFIX}contract-1")[-3:] == [
        "down",
        "-v",
        "--remove-orphans",
    ]
    assert "--rmi" not in cleanup_command(f"{PROJECT_PREFIX}contract-1")


def test_recovery_run_allocates_a_fresh_identity_for_each_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allocated = iter((f"{PROJECT_PREFIX}first-owned-run", f"{PROJECT_PREFIX}second-owned-run"))
    monkeypatch.setattr(recovery, "new_project_name", lambda: next(allocated))
    projects: list[str] = []

    def fake_cleanup(project_name: str, env: dict[str, str]) -> None:
        projects.append(project_name)

    monkeypatch.setattr(recovery, "_cleanup_owned_project", fake_cleanup)
    monkeypatch.setattr(recovery, "_run", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("stop")))

    with pytest.raises(RuntimeError, match="stop"):
        run_validation()
    with pytest.raises(RuntimeError, match="stop"):
        run_validation()

    assert projects == [f"{PROJECT_PREFIX}first-owned-run", f"{PROJECT_PREFIX}second-owned-run"]


def test_recovery_cli_refuses_a_caller_selected_project_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["validate_lineage_volume_recovery.py", "--project-name", f"{PROJECT_PREFIX}other-run"]
    )

    with pytest.raises(SystemExit) as exc_info:
        recovery.main()

    assert exc_info.value.code == 2


@pytest.mark.parametrize("cleanup_exit", (0, 19))
def test_cleanup_failure_prevents_a_passed_recovery_verdict_and_reports_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
    cleanup_exit: int,
) -> None:
    project_name = f"{PROJECT_PREFIX}cleanup-failure"
    monkeypatch.setattr(recovery, "new_project_name", lambda: project_name)
    monkeypatch.setattr(recovery, "_assert_initializer_succeeded", lambda *_args: None)
    monkeypatch.setattr(recovery, "_assert_schema_apply_succeeded", lambda *_args: None)
    monkeypatch.setattr(recovery, "_wait_for_healthy_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "_assert_non_root_volume_access", lambda *_args: None)
    monkeypatch.setattr(
        recovery,
        "_remaining_owned_resources",
        lambda *_args: {"containers": [f"{project_name}-analytics"], "networks": [], "volumes": []},
    )

    def fake_run(command: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, cleanup_exit if command == cleanup_command(project_name) else 0)

    monkeypatch.setattr(recovery, "_run", fake_run)

    with pytest.raises(recovery.RecoveryCleanupError, match=f"exited with code {cleanup_exit}") as exc_info:
        run_validation()

    assert exc_info.value.project_name == project_name
    assert exc_info.value.remaining_resources["containers"] == [f"{project_name}-analytics"]


def test_primary_failure_is_retained_when_owned_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_name = f"{PROJECT_PREFIX}both-failures"
    primary_command = compose_command(project_name, "up", "-d", "--no-deps", recovery.DATABASE_SERVICE)
    monkeypatch.setattr(recovery, "new_project_name", lambda: project_name)
    monkeypatch.setattr(
        recovery, "_remaining_owned_resources", lambda *_args: {"containers": [], "networks": [], "volumes": []}
    )

    def fake_run(command: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
        if command == primary_command:
            raise subprocess.CalledProcessError(7, command)
        if command == cleanup_command(project_name):
            return subprocess.CompletedProcess(command, 23)
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(recovery, "_run", fake_run)

    with pytest.raises(recovery.RecoveryValidationError, match="cleanup also failed") as exc_info:
        run_validation()

    assert isinstance(exc_info.value.__cause__, subprocess.CalledProcessError)
    assert exc_info.value.cleanup_error.returncode == 23


@pytest.mark.parametrize("resource", ("containers", "networks", "volumes"))
def test_zero_exit_cleanup_refuses_retained_owned_resources(monkeypatch, resource):
    project = f"{PROJECT_PREFIX}zero-exit-leftover"
    remaining = {"containers": [], "networks": [], "volumes": []}
    remaining[resource] = [f"{project}-retained"]
    monkeypatch.setattr(recovery, "_run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0))
    monkeypatch.setattr(recovery, "_remaining_owned_resources", lambda *args: remaining)

    with pytest.raises(recovery.RecoveryCleanupError, match="exited with code 0 but owned resource absence") as exc:
        recovery._cleanup_owned_project(project, {})

    assert exc.value.returncode == 0
    assert exc.value.remaining_resources == remaining


@pytest.mark.parametrize("failure", ("launch", "nonzero"))
@pytest.mark.parametrize("resource", ("containers", "networks", "volumes"))
def test_zero_exit_cleanup_refuses_resource_inspection_failure(monkeypatch, resource, failure):
    project = f"{PROJECT_PREFIX}inspection-failure"
    monkeypatch.setattr(recovery, "_run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0))

    def inspect(command, **kwargs):
        kind = "containers" if "ps" in command else "networks" if "network" in command else "volumes"
        if kind == resource:
            if failure == "launch":
                raise OSError("inspection unavailable")
            return subprocess.CompletedProcess(command, 17, "", "inspection denied")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(recovery, "_capture_completed", inspect)
    with pytest.raises(recovery.RecoveryCleanupError, match="owned resource absence") as exc:
        recovery._cleanup_owned_project(project, {})
    assert exc.value.returncode == 0
    assert "inspection failed" in exc.value.remaining_resources[resource][0]


def test_zero_exit_cleanup_accepts_only_successfully_inspected_empty_inventories(monkeypatch):
    project = f"{PROJECT_PREFIX}empty-owned-project"
    commands = []
    monkeypatch.setattr(recovery, "_run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0))

    def inspect(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(recovery, "_capture_completed", inspect)
    recovery._cleanup_owned_project(project, {})
    assert len(commands) == 3
    assert all("default" in command and f"name={project}" in command for command in commands)


def test_primary_failure_is_retained_when_zero_exit_cleanup_leaves_owned_resources(monkeypatch):
    project = f"{PROJECT_PREFIX}primary-and-leftover"
    primary = compose_command(project, "up", "-d", "--no-deps", recovery.DATABASE_SERVICE)
    monkeypatch.setattr(recovery, "new_project_name", lambda: project)
    monkeypatch.setattr(
        recovery,
        "_remaining_owned_resources",
        lambda *args: {"containers": [], "networks": [], "volumes": [f"{project}_lineage-data"]},
    )

    def run(command, **kwargs):
        if command == primary:
            raise subprocess.CalledProcessError(7, command)
        assert command == cleanup_command(project)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(recovery, "_run", run)
    with pytest.raises(recovery.RecoveryValidationError, match="cleanup also failed") as exc:
        run_validation()
    assert isinstance(exc.value.__cause__, subprocess.CalledProcessError)
    assert exc.value.__cause__.returncode == 7
    assert exc.value.cleanup_error.returncode == 0
    assert exc.value.cleanup_error.remaining_resources["volumes"] == [f"{project}_lineage-data"]


def test_primary_failure_is_retained_when_owned_cleanup_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_name = f"{PROJECT_PREFIX}cleanup-launch-failure"
    primary_command = compose_command(project_name, "up", "-d", "--no-deps", recovery.DATABASE_SERVICE)
    monkeypatch.setattr(recovery, "new_project_name", lambda: project_name)
    monkeypatch.setattr(
        recovery,
        "_remaining_owned_resources",
        lambda *_args: {"containers": [], "networks": [], "volumes": [f"{project_name}_lineage-data"]},
    )

    def fake_run(command: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
        if command == primary_command:
            raise subprocess.CalledProcessError(7, command)
        if command == cleanup_command(project_name):
            raise OSError("docker executable unavailable")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(recovery, "_run", fake_run)

    with pytest.raises(recovery.RecoveryValidationError, match="could not start") as exc_info:
        run_validation()

    assert isinstance(exc_info.value.__cause__, subprocess.CalledProcessError)
    assert exc_info.value.cleanup_error.returncode is None
    assert exc_info.value.cleanup_error.remaining_resources["volumes"] == [f"{project_name}_lineage-data"]


def test_initial_failure_cannot_clean_a_preexisting_same_prefix_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preexisting_project = f"{PROJECT_PREFIX}preexisting-recovery"
    owned_project = f"{PROJECT_PREFIX}this-invocation"
    primary_command = compose_command(owned_project, "up", "-d", "--no-deps", recovery.DATABASE_SERVICE)
    commands: list[list[str]] = []
    monkeypatch.setattr(recovery, "new_project_name", lambda: owned_project)
    monkeypatch.setattr(
        recovery, "_capture_completed", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", "")
    )

    def fake_run(command: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command == primary_command:
            raise subprocess.CalledProcessError(11, command)
        if command == cleanup_command(owned_project):
            return subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(recovery, "_run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        run_validation()

    assert cleanup_command(owned_project) in commands
    assert all(preexisting_project not in part for command in commands for part in command)


@pytest.mark.parametrize(
    "project_name",
    (
        "lotus-performance",
        "default",
        f"{PROJECT_PREFIX}unsafe_value",
        f"{PROJECT_PREFIX}../unsafe",
        "",
    ),
)
def test_validation_rejects_projects_outside_owned_prefix(project_name: str) -> None:
    with pytest.raises(ValueError, match="project name must match"):
        validate_project_name(project_name)


def test_unhealthy_runtime_error_includes_container_log_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_capture(command: list[str], *, env: dict[str, str], check: bool = True) -> str:
        assert env == {"LOTUS_TEST": "lineage-volume-recovery"}
        if command[:5] == ["docker", "--context", "default", "logs", "--tail"]:
            return "Traceback: worker startup failed\n"
        if command[:6] == [
            "docker",
            "--context",
            "default",
            "inspect",
            "--format",
            "{{.State.Health.Status}}",
        ]:
            return "unhealthy\n"
        if command[:6] == [
            "docker",
            "--context",
            "default",
            "inspect",
            "--format",
            "{{json .State}}",
        ]:
            return '{"Status":"exited","ExitCode":1}\n'
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("scripts.validate_lineage_volume_recovery._capture", fake_capture)

    with pytest.raises(RuntimeError, match="Traceback: worker startup failed") as exc_info:
        _wait_for_healthy_runtime(
            {
                "analytics": "owned-analytics",
                "compute_executor": "owned-compute-executor",
                "initializer": "owned-initializer",
            },
            {"LOTUS_TEST": "lineage-volume-recovery"},
            timeout_seconds=0,
        )

    assert "container_states" in str(exc_info.value)
    assert "owned-compute-executor" in str(exc_info.value)


def test_capture_output_preserves_docker_stderr_tail() -> None:
    assert _captured_output("", "Traceback: worker startup failed\n") == "Traceback: worker startup failed\n"
    assert _captured_output("stdout line\n", "stderr line\n") == "stdout line\nstderr line\n"


def service_proof(container_id="a" * 64):
    return {
        "schema_version": 1,
        "proof_type": "local-existing-service-content",
        "policy_source": {"commit": recovery.image_bindings.RECOVERY_POLICY_REVISION},
        "requested_image": recovery.image_bindings.RECOVERY_POSTGRES_IMAGE,
        "service_container_id": container_id,
        "service_image_id": "sha256:" + "d" * 64,
        "admitted_index_digest": recovery.image_bindings.RECOVERY_POSTGRES_IMAGE.partition("@")[2],
        "admitted_child_digest": recovery.POSTGRES_CHILD,
        "config_digest": recovery.POSTGRES_CONFIG,
        "platform": "linux/amd64",
        "rootfs_diff_ids": ["sha256:" + "e" * 64],
        "cold_acquisition_proven": False,
        "compressed_transfer_verified": False,
        "runtime_execution_verified": False,
        "raw_export_retained": False,
        "raw_inspect_retained": False,
    }


def test_database_content_is_mandatory_before_build_schema_and_workloads(monkeypatch):
    events = []
    environments = []
    monkeypatch.setattr(recovery, "prove_owned_database", PROVE_DATABASE)
    monkeypatch.setattr(recovery, "owned_database_id", lambda *_args: "a" * 64)

    def helper(argv, **kwargs):
        events.append("content-proof")
        environments.append(kwargs["env"])
        assert argv[:2] == [sys.executable, "-B"]
        assert argv[argv.index("--expected-image") + 1] == recovery.image_bindings.RECOVERY_POSTGRES_IMAGE
        assert argv[argv.index("--expected-policy-commit") + 1] == recovery.image_bindings.RECOVERY_POLICY_REVISION
        assert kwargs["check"] is True and kwargs["timeout"] == 250
        recovery.POSTGRES_PROOF.write_text(json.dumps(service_proof()))

    def run(command, **kwargs):
        environments.append(kwargs["env"])
        events.append("db-only" if command[-4:] == ["up", "-d", "--no-deps", recovery.DATABASE_SERVICE] else "work")

    monkeypatch.setattr(recovery.subprocess, "run", helper)
    monkeypatch.setattr(recovery, "_run", run)
    monkeypatch.setattr(recovery, "_cleanup_owned_project", lambda *_args: events.append("cleanup"))
    for name in (
        "_assert_initializer_succeeded",
        "_assert_schema_apply_succeeded",
        "_wait_for_healthy_runtime",
        "_assert_non_root_volume_access",
    ):
        monkeypatch.setattr(recovery, name, lambda *_args: None)
    summary = run_validation(recovery.image_bindings.ORIGINAL_RUNTIME_IMAGE)
    assert events[:3] == ["db-only", "content-proof", "work"] and events[-1] == "cleanup"
    assert summary["postgres_content_proof"]["service_container_id"] == "a" * 64
    assert all(
        env["RECOVERY_POSTGRES_IMAGE"] == recovery.image_bindings.RECOVERY_POSTGRES_IMAGE for env in environments
    )
    assert all(env["RUNTIME_BASE_IMAGE"] == recovery.image_bindings.ORIGINAL_RUNTIME_IMAGE for env in environments)


@pytest.mark.parametrize(
    "damage",
    ["missing", "policy", "container", "child", "config", "rootfs", "shape", "replaced", "schema", "scope"],
)
def test_refused_or_missing_content_proof_stops_work_and_retains_owned_cleanup(monkeypatch, damage):
    commands = []
    cleanup = []
    ids = iter(["a" * 64, "b" * 64] if damage == "replaced" else ["a" * 64, "a" * 64])
    monkeypatch.setattr(recovery, "prove_owned_database", PROVE_DATABASE)
    monkeypatch.setattr(recovery, "owned_database_id", lambda *_args: next(ids))
    monkeypatch.setattr(recovery, "_run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(recovery, "_cleanup_owned_project", lambda project, env: cleanup.append(project))

    def helper(*_args, **_kwargs):
        proof = service_proof()
        if damage == "missing":
            return
        if damage == "policy":
            proof["policy_source"]["commit"] = "b" * 40
        elif damage == "container":
            proof["service_container_id"] = "b" * 64
        elif damage in {"child", "config"}:
            proof["admitted_child_digest" if damage == "child" else "config_digest"] = "sha256:" + "b" * 64
        elif damage == "rootfs":
            proof["rootfs_diff_ids"] = []
        elif damage == "schema":
            proof["schema_version"] = True
        elif damage == "scope":
            proof["cold_acquisition_proven"] = True
        elif damage == "shape":
            proof = []
        recovery.POSTGRES_PROOF.write_text(json.dumps(proof))

    monkeypatch.setattr(recovery.subprocess, "run", helper)
    with pytest.raises((ValueError, OSError)):
        run_validation()
    assert len(commands) == 1 and commands[0][-4:] == ["up", "-d", "--no-deps", recovery.DATABASE_SERVICE]
    assert len(cleanup) == 1


def test_failed_content_command_remains_primary_when_cleanup_also_fails(monkeypatch):
    primary = subprocess.CalledProcessError(7, ["qualified-service-helper"])
    cleanup = recovery.RecoveryCleanupError("owned", 23, {"containers": [], "networks": [], "volumes": []})
    monkeypatch.setattr(recovery, "prove_owned_database", PROVE_DATABASE)
    monkeypatch.setattr(recovery, "owned_database_id", lambda *_args: "a" * 64)
    monkeypatch.setattr(recovery, "_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(primary))
    monkeypatch.setattr(recovery, "_cleanup_owned_project", lambda *_args: (_ for _ in ()).throw(cleanup))
    with pytest.raises(recovery.RecoveryValidationError) as raised:
        run_validation()
    assert raised.value.validation_error is primary and raised.value.cleanup_error is cleanup


@pytest.mark.parametrize(
    "image",
    [
        "",
        "postgres:17",
        recovery.image_bindings.RECOVERY_POSTGRES_IMAGE.replace("docker.io", "public.ecr.aws/docker"),
        recovery.image_bindings.RECOVERY_POSTGRES_IMAGE[:-1] + "0",
    ],
)
def test_original_only_postgres_refusal_precedes_any_docker_or_cleanup(monkeypatch, image):
    calls = []
    monkeypatch.setattr(recovery, "_run", lambda *_args, **_kwargs: calls.append("docker"))
    monkeypatch.setattr(recovery, "_cleanup_owned_project", lambda *_args: calls.append("cleanup"))
    with pytest.raises(ValueError, match="exact original PG17"):
        run_validation(postgres_image=image)
    assert calls == []


def test_stale_content_evidence_refuses_before_resources_or_cleanup(monkeypatch):
    recovery.POSTGRES_PROOF.write_bytes(b"old proof")
    calls = []
    monkeypatch.setattr(recovery, "_run", lambda *_args, **_kwargs: calls.append("docker"))
    monkeypatch.setattr(recovery, "_cleanup_owned_project", lambda *_args: calls.append("cleanup"))
    with pytest.raises(ValueError, match="unused"):
        run_validation()
    assert calls == [] and recovery.POSTGRES_PROOF.read_bytes() == b"old proof"


@pytest.mark.parametrize(
    "damage", [None, "project", "service", "image", "id", "stopped", "multiple", "shape", "short-id"]
)
def test_database_identity_requires_full_unique_running_selected_owned_service(monkeypatch, damage):
    project = PROJECT_PREFIX + "owned-database"
    env = build_runtime_environment(project)
    container = {
        "Id": "a" * 64,
        "State": {"Running": True},
        "Config": {
            "Image": env["RECOVERY_POSTGRES_IMAGE"],
            "Labels": {"com.docker.compose.project": project, "com.docker.compose.service": recovery.DATABASE_SERVICE},
        },
    }
    if damage in {"project", "service"}:
        container["Config"]["Labels"]["com.docker.compose." + damage] = "foreign"
    elif damage == "image":
        container["Config"]["Image"] = "postgres:17"
    elif damage == "id":
        container["Id"] = "b" * 64
    elif damage == "stopped":
        container["State"]["Running"] = False
    elif damage == "shape":
        container = []

    def metadata(command, observed_env):
        assert observed_env == env
        if "ps" in command:
            assert command[-4:] == ["ps", "--quiet", "--all", recovery.DATABASE_SERVICE]
            return "short" if damage == "short-id" else "a" * 64
        return json.dumps([container, container] if damage == "multiple" else [container])

    monkeypatch.setattr(recovery, "bounded_command_metadata", metadata)
    if damage is None:
        assert recovery.owned_database_id(project, env) == "a" * 64
    else:
        with pytest.raises(ValueError):
            recovery.owned_database_id(project, env)


@pytest.fixture
def pg17_policy_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(recovery.image_bindings, "ROOT", tmp_path)
    policy = tmp_path / "output" / "pg17-image-policy"
    policy.mkdir(parents=True)
    state = {
        "root": str(policy),
        "head": recovery.image_bindings.RECOVERY_POLICY_REVISION,
        "policy_status": "",
        "source_status": "",
        "blob": "a" * 40,
    }

    def command(argv, env):
        assert not {"GIT_DIR", "DOCKER_HOST", "RECOVERY_POSTGRES_IMAGE", "COMPOSE_FILE"}.intersection(env)
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

    monkeypatch.setattr(recovery, "bounded_command_metadata", command)
    return policy, state


@pytest.mark.parametrize(
    "damage", [None, "root", "head", "policy_status", "source_status", "blob", "symlink", "runtime-policy"]
)
def test_qualified_pg17_policy_authenticates_exact_clean_excluded_checkout(pg17_policy_checkout, monkeypatch, damage):
    policy, state = pg17_policy_checkout
    monkeypatch.setenv("GIT_DIR", "foreign")
    monkeypatch.setenv("DOCKER_HOST", "foreign")
    if damage in state:
        state[damage] = str(policy.parent) if damage == "root" else "untrusted"
    elif damage == "symlink":
        policy.rmdir()
        policy.symlink_to(policy.parent, target_is_directory=True)
    elif damage == "runtime-policy":
        (policy.parents[1] / ".image-policy").mkdir()
    if damage is None:
        assert QUALIFY_POLICY() == policy
    else:
        with pytest.raises(ValueError):
            QUALIFY_POLICY()


def test_recovery_metadata_capture_is_finite_and_omits_failed_secret_streams(monkeypatch, capsys):
    assert (
        recovery.bounded_command_metadata(
            [sys.executable, "-c", "print('small')"], recovery._host_command_environment()
        ).strip()
        == "small"
    )
    monkeypatch.setattr(recovery, "MAX_METADATA_BYTES", 16)
    with pytest.raises(ValueError, match="metadata"):
        recovery.bounded_command_metadata(
            [sys.executable, "-c", "print('private-marker' * 100)"], recovery._host_command_environment()
        )
    assert capsys.readouterr() == ("", "")
