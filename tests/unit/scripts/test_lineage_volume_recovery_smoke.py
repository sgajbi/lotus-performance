from __future__ import annotations

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
