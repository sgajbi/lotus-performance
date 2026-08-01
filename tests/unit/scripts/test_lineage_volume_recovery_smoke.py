from __future__ import annotations

import pytest

from scripts.validate_lineage_volume_recovery import (
    PROJECT_PREFIX,
    _wait_for_healthy_runtime,
    compose_command,
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
        if command[:3] == ["docker", "logs", "--tail"]:
            return "Traceback: worker startup failed\n"
        if command[:4] == ["docker", "inspect", "--format", "{{.State.Health.Status}}"]:
            return "unhealthy\n"
        if command[:4] == ["docker", "inspect", "--format", "{{json .State}}"]:
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
