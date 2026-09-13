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


class RecoveryCleanupError(RuntimeError):
    """Raised when the invocation-owned Compose project could not be removed."""

    def __init__(
        self,
        project_name: str,
        returncode: int | None,
        remaining_resources: dict[str, list[str]],
        *,
        launch_error: OSError | None = None,
    ) -> None:
        self.project_name = project_name
        self.returncode = returncode
        self.remaining_resources = remaining_resources
        self.launch_error = launch_error
        cleanup_outcome = (
            f"could not start: {launch_error}" if launch_error is not None else f"exited with code {returncode}"
        )
        super().__init__(
            "lineage recovery cleanup failed "
            f"for owned project {project_name}: {cleanup_outcome}; "
            f"remaining owned resources: {json.dumps(remaining_resources, sort_keys=True)}"
        )


class RecoveryValidationError(RuntimeError):
    """Retain the original recovery failure when its cleanup also fails."""

    def __init__(self, validation_error: Exception, cleanup_error: RecoveryCleanupError) -> None:
        self.validation_error = validation_error
        self.cleanup_error = cleanup_error
        super().__init__(f"recovery validation failed: {validation_error}; cleanup also failed: {cleanup_error}")


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


def run_validation() -> dict[str, object]:
    """Run one recovery proof in a freshly allocated, invocation-owned namespace.

    The project identity is intentionally not caller-configurable. A same-prefix value does not
    establish ownership, and cleanup includes destructive volume removal.
    """
    project_name = validate_project_name(new_project_name())
    runtime_environment = build_runtime_environment(project_name)
    container_names = {
        "initializer": runtime_environment["PA_LINEAGE_VOLUME_INIT_CONTAINER_NAME"],
        "analytics": runtime_environment["PA_ANALYTICS_CONTAINER_NAME"],
        "lineage_worker": runtime_environment["PA_LINEAGE_WORKER_CONTAINER_NAME"],
        "compute_executor": runtime_environment["PA_COMPUTE_EXECUTOR_CONTAINER_NAME"],
    }
    validation_error: Exception | None = None
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
    except Exception as exc:
        validation_error = exc
        raise
    finally:
        try:
            _cleanup_owned_project(project_name, runtime_environment)
        except RecoveryCleanupError as cleanup_error:
            if validation_error is not None:
                raise RecoveryValidationError(validation_error, cleanup_error) from validation_error
            raise


def cleanup_command(project_name: str) -> list[str]:
    """Remove only project-scoped containers, volumes, networks, and orphaned services.

    Deliberately retain images: Compose's local-image label is not a safe ownership boundary for a
    shared developer or CI daemon.
    """
    return compose_command(project_name, "down", "-v", "--remove-orphans")


def _cleanup_owned_project(project_name: str, env: dict[str, str]) -> None:
    try:
        completed = _run(cleanup_command(project_name), env=env, check=False)
    except OSError as exc:
        raise RecoveryCleanupError(
            project_name,
            None,
            _remaining_owned_resources(project_name, env),
            launch_error=exc,
        ) from exc
    if completed.returncode:
        raise RecoveryCleanupError(
            project_name,
            completed.returncode,
            _remaining_owned_resources(project_name, env),
        )


def _remaining_owned_resources(project_name: str, env: dict[str, str]) -> dict[str, list[str]]:
    """Report only names that can belong to this generated Compose project."""
    return {
        "containers": _owned_resource_names(
            docker_command("ps", "-a", "--filter", f"name={project_name}", "--format", "{{.Names}}"),
            f"{project_name}-",
            env,
        ),
        "networks": _owned_resource_names(
            docker_command("network", "ls", "--filter", f"name={project_name}", "--format", "{{.Name}}"),
            f"{project_name}_",
            env,
        ),
        "volumes": _owned_resource_names(
            docker_command("volume", "ls", "--filter", f"name={project_name}", "--format", "{{.Name}}"),
            f"{project_name}_",
            env,
        ),
    }


def _owned_resource_names(command: list[str], prefix: str, env: dict[str, str]) -> list[str]:
    try:
        completed = _capture_completed(command, env=env, check=False)
    except OSError as exc:
        return [f"<inspection failed: {exc}>"]
    output = _captured_output(completed.stdout, completed.stderr)
    if completed.returncode:
        return [f"<inspection failed: exit {completed.returncode}: {output.strip()}>"]
    return sorted({line.strip() for line in output.splitlines() if line.strip().startswith(prefix)})


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
    completed = _capture_completed(command, env=env, check=check)
    return _captured_output(completed.stdout, completed.stderr)


def _capture_completed(
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
        capture_output=True,
        text=True,
    )


def _captured_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout.rstrip()}\n{stderr}"
    return stdout or stderr


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove non-root lineage volume recovery and restart health.")
    parser.parse_args()
    try:
        summary = run_validation()
    except (OSError, subprocess.CalledProcessError, RecoveryValidationError, RuntimeError, ValueError) as exc:
        _fail(f"lineage volume recovery validation failed: {exc}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
