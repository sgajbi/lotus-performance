from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import NoReturn

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PREFIX = "lotus-performance-lineage-recovery-"
RUNTIME_SERVICES = (
    "performance-analytics",
    "performance-lineage-worker",
    "performance-compute-executor",
)
_PROJECT_PATTERN = re.compile(rf"^{PROJECT_PREFIX}[a-z0-9][a-z0-9-]{{0,40}}$")


def validate_project_name(project_name: str) -> str:
    normalized = project_name.strip().lower()
    if not _PROJECT_PATTERN.fullmatch(normalized):
        raise ValueError(f"project name must match {PROJECT_PREFIX}<lowercase-safe-identifier>")
    return normalized


def build_runtime_environment(project_name: str) -> dict[str, str]:
    return {
        **os.environ,
        "PA_LINEAGE_DB_PORT": str(_available_port()),
        "PA_HOST_PORT": str(_available_port()),
        "PA_LINEAGE_DB_CONTAINER_NAME": f"{project_name}-db",
        "PA_LINEAGE_VOLUME_INIT_CONTAINER_NAME": f"{project_name}-volume-init",
        "PA_ANALYTICS_CONTAINER_NAME": f"{project_name}-analytics",
        "PA_LINEAGE_WORKER_CONTAINER_NAME": f"{project_name}-lineage-worker",
        "PA_COMPUTE_EXECUTOR_CONTAINER_NAME": f"{project_name}-compute-executor",
        "PA_RUNTIME_RETENTION_CONTAINER_NAME": f"{project_name}-retention",
    }


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def compose_command(project_name: str, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(REPOSITORY_ROOT),
        "-f",
        str(REPOSITORY_ROOT / "docker-compose.yml"),
        "-p",
        project_name,
        *arguments,
    ]


def run_validation(project_name: str) -> dict[str, object]:
    project_name = validate_project_name(project_name)
    runtime_environment = build_runtime_environment(project_name)
    container_names = {
        "initializer": runtime_environment["PA_LINEAGE_VOLUME_INIT_CONTAINER_NAME"],
        "analytics": runtime_environment["PA_ANALYTICS_CONTAINER_NAME"],
        "lineage_worker": runtime_environment["PA_LINEAGE_WORKER_CONTAINER_NAME"],
        "compute_executor": runtime_environment["PA_COMPUTE_EXECUTOR_CONTAINER_NAME"],
    }
    try:
        _run(
            compose_command(project_name, "build", "performance-lineage-volume-init"),
            env=runtime_environment,
        )
        _run(
            compose_command(
                project_name,
                "run",
                "--rm",
                "--no-deps",
                "--user",
                "0:0",
                "--entrypoint",
                "/bin/sh",
                "performance-lineage-volume-init",
                "-c",
                (
                    "set -eu; "
                    "printf 'retained-lineage-evidence\\n' > /app/lineage_data/recovery-marker.txt; "
                    "chown -R 0:0 /app/lineage_data; chmod 0755 /app/lineage_data; "
                    "test \"$(stat -c '%u:%g:%a' /app/lineage_data)\" = '0:0:755'"
                ),
            ),
            env=runtime_environment,
        )
        _run(
            compose_command(project_name, "up", "-d", "--build", *RUNTIME_SERVICES),
            env=runtime_environment,
        )
        _assert_initializer_succeeded(container_names["initializer"], runtime_environment)
        _wait_for_healthy_runtime(container_names, runtime_environment)
        _assert_non_root_volume_access(project_name, runtime_environment)

        _run(
            compose_command(project_name, "restart", *RUNTIME_SERVICES),
            env=runtime_environment,
        )
        _wait_for_healthy_runtime(container_names, runtime_environment)
        _assert_non_root_volume_access(project_name, runtime_environment)
        return {
            "status": "passed",
            "project_name": project_name,
            "initializer_exit_code": 0,
            "root_owned_volume_repaired": True,
            "lineage_evidence_retained": True,
            "healthy_after_restart": list(RUNTIME_SERVICES),
        }
    finally:
        _run(
            compose_command(
                project_name,
                "down",
                "-v",
                "--remove-orphans",
                "--rmi",
                "local",
            ),
            env=runtime_environment,
            check=False,
        )


def _assert_initializer_succeeded(container_name: str, env: dict[str, str]) -> None:
    exit_code = _capture(
        ["docker", "inspect", "--format", "{{.State.ExitCode}}", container_name],
        env=env,
    ).strip()
    if exit_code != "0":
        raise RuntimeError(f"lineage volume initializer exited with code {exit_code}")


def _wait_for_healthy_runtime(
    container_names: dict[str, str],
    env: dict[str, str],
    *,
    timeout_seconds: int = 180,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    pending = {name for key, name in container_names.items() if key != "initializer"}
    while pending and time.monotonic() < deadline:
        pending = {
            name
            for name in pending
            if _capture(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
                env=env,
                check=False,
            ).strip()
            != "healthy"
        }
        if pending:
            time.sleep(2)
    if pending:
        statuses = {
            name: _capture(
                ["docker", "inspect", "--format", "{{json .State}}", name],
                env=env,
                check=False,
            ).strip()
            for name in sorted(pending)
        }
        logs = _container_log_tails(pending, env=env)
        raise RuntimeError(
            "runtime services did not become healthy: "
            f"{json.dumps({'container_states': statuses, 'container_logs': logs}, sort_keys=True)}"
        )


def _container_log_tails(
    container_names: set[str],
    *,
    env: dict[str, str],
    tail_lines: int = 120,
) -> dict[str, str]:
    return {
        name: _capture(
            ["docker", "logs", "--tail", str(tail_lines), name],
            env=env,
            check=False,
        ).strip()
        for name in sorted(container_names)
    }


def _assert_non_root_volume_access(project_name: str, env: dict[str, str]) -> None:
    _run(
        compose_command(
            project_name,
            "run",
            "--rm",
            "--no-deps",
            "--user",
            "10001:10001",
            "--entrypoint",
            "/bin/sh",
            "performance-lineage-volume-init",
            "-c",
            (
                "set -eu; test -r /app/lineage_data/recovery-marker.txt; "
                "grep -qx 'retained-lineage-evidence' /app/lineage_data/recovery-marker.txt; "
                "printf 'write-probe\\n' > /app/lineage_data/non-root-write-probe.txt; "
                "rm /app/lineage_data/non-root-write-probe.txt"
            ),
        ),
        env=env,
    )


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=env,
        check=check,
        text=True,
    )


def _capture(
    command: list[str],
    *,
    env: dict[str, str],
    check: bool = True,
) -> str:
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove non-root lineage volume recovery and restart health.")
    parser.add_argument(
        "--project-name",
        default=f"{PROJECT_PREFIX}{os.getpid()}",
        help=f"Owned disposable Compose project; must start with {PROJECT_PREFIX}",
    )
    args = parser.parse_args()
    try:
        summary = run_validation(args.project_name)
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        _fail(f"lineage volume recovery validation failed: {exc}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
