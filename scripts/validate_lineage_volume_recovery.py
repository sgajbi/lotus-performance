from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import NoReturn

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PREFIX = "lotus-performance-lineage-recovery-"
RECOVERY_COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.lineage-recovery.yml"
RUNTIME_SERVICES = (
    "performance-analytics",
    "performance-lineage-worker",
    "performance-compute-executor",
)
_PROJECT_PATTERN = re.compile(rf"^{PROJECT_PREFIX}[a-z0-9][a-z0-9-]{{0,40}}$")
_HOST_ENVIRONMENT_KEYS = (
    "PATH",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "ProgramFiles",
    "ProgramW6432",
    "ProgramFiles(x86)",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
)
_LINEAGE_DATABASE_URL = "postgresql+psycopg://lotus:lotus@performance-lineage-db:5432/lotus_performance"
_LOCAL_DOCKER_CONTEXT = "default"


def validate_project_name(project_name: str) -> str:
    normalized = project_name.strip().lower()
    if not _PROJECT_PATTERN.fullmatch(normalized):
        raise ValueError(f"project name must match {PROJECT_PREFIX}<lowercase-safe-identifier>")
    return normalized


def new_project_name() -> str:
    """Return a collision-resistant name inside the validator's owned Compose namespace."""
    return f"{PROJECT_PREFIX}{secrets.token_hex(12)}"


def build_runtime_environment(project_name: str) -> dict[str, str]:
    """Build the bounded host and container configuration for one owned recovery run.

    Docker only receives the host variables it needs to start locally. Compose interpolation is
    then limited to resource names and the in-network database URL owned by this project; caller
    configuration cannot redirect the proof to another database, daemon, project, or host port.
    Every command also selects Docker's built-in ``default`` context explicitly, so a persisted
    caller-selected context cannot redirect the validator to a remote daemon.
    """
    return {
        **_host_command_environment(),
        "LINEAGE_METADATA_DATABASE_URL": _LINEAGE_DATABASE_URL,
        "PA_LINEAGE_DB_CONTAINER_NAME": f"{project_name}-db",
        "PA_LINEAGE_VOLUME_INIT_CONTAINER_NAME": f"{project_name}-volume-init",
        "PA_ANALYTICS_CONTAINER_NAME": f"{project_name}-analytics",
        "PA_LINEAGE_WORKER_CONTAINER_NAME": f"{project_name}-lineage-worker",
        "PA_COMPUTE_EXECUTOR_CONTAINER_NAME": f"{project_name}-compute-executor",
        "PA_RUNTIME_RETENTION_CONTAINER_NAME": f"{project_name}-retention",
    }


def _host_command_environment() -> dict[str, str]:
    return {key: value for key in _HOST_ENVIRONMENT_KEYS if (value := os.environ.get(key)) is not None}


def compose_command(project_name: str, *arguments: str) -> list[str]:
    return docker_command(
        "compose",
        "-f",
        str(REPOSITORY_ROOT / "docker-compose.yml"),
        "-f",
        str(RECOVERY_COMPOSE_FILE),
        "-p",
        project_name,
        *arguments,
    )


def docker_command(*arguments: str) -> list[str]:
    """Run every Docker CLI operation against the built-in local context."""
    return ["docker", "--context", _LOCAL_DOCKER_CONTEXT, *arguments]


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
            cleanup_command(project_name),
            env=runtime_environment,
            check=False,
        )


def cleanup_command(project_name: str) -> list[str]:
    """Remove only project-scoped containers, volumes, networks, and orphaned services.

    Deliberately retain images: Compose's local-image label is not a safe ownership boundary for a
    shared developer or CI daemon.
    """
    return compose_command(project_name, "down", "-v", "--remove-orphans")


def _assert_initializer_succeeded(container_name: str, env: dict[str, str]) -> None:
    exit_code = _capture(
        docker_command("inspect", "--format", "{{.State.ExitCode}}", container_name),
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
                docker_command("inspect", "--format", "{{.State.Health.Status}}", name),
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
                docker_command("inspect", "--format", "{{json .State}}", name),
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
            docker_command("logs", "--tail", str(tail_lines), name),
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
    return _captured_output(completed.stdout, completed.stderr)


def _captured_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout.rstrip()}\n{stderr}"
    return stdout or stderr


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove non-root lineage volume recovery and restart health.")
    parser.add_argument(
        "--project-name",
        default=new_project_name(),
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
