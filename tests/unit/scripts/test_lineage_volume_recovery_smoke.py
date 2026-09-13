from __future__ import annotations

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
    assert not {
        "PA_LINEAGE_DB_PORT",
        "PA_HOST_PORT",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "COMPOSE_PROJECT_NAME",
        "CORE_CONTROL_PLANE_BASE_URL",
    }.intersection(environment)


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


def test_cleanup_failure_prevents_a_passed_recovery_verdict_and_reports_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_name = f"{PROJECT_PREFIX}cleanup-failure"
    monkeypatch.setattr(recovery, "new_project_name", lambda: project_name)
    monkeypatch.setattr(recovery, "_assert_initializer_succeeded", lambda *_args: None)
    monkeypatch.setattr(recovery, "_wait_for_healthy_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "_assert_non_root_volume_access", lambda *_args: None)
    monkeypatch.setattr(
        recovery,
        "_remaining_owned_resources",
        lambda *_args: {"containers": [f"{project_name}-analytics"], "networks": [], "volumes": []},
    )

    def fake_run(command: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 19 if command == cleanup_command(project_name) else 0)

    monkeypatch.setattr(recovery, "_run", fake_run)

    with pytest.raises(recovery.RecoveryCleanupError, match="exited with code 19") as exc_info:
        run_validation()

    assert exc_info.value.project_name == project_name
    assert exc_info.value.remaining_resources["containers"] == [f"{project_name}-analytics"]


def test_primary_failure_is_retained_when_owned_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_name = f"{PROJECT_PREFIX}both-failures"
    primary_command = compose_command(project_name, "build", "performance-lineage-volume-init")
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


def test_primary_failure_is_retained_when_owned_cleanup_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_name = f"{PROJECT_PREFIX}cleanup-launch-failure"
    primary_command = compose_command(project_name, "build", "performance-lineage-volume-init")
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
    primary_command = compose_command(owned_project, "build", "performance-lineage-volume-init")
    commands: list[list[str]] = []
    monkeypatch.setattr(recovery, "new_project_name", lambda: owned_project)

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
