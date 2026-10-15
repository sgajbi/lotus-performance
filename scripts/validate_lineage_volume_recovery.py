from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NoReturn

if __package__:
    from . import ci_image_bindings_gate as image_bindings
else:
    import ci_image_bindings_gate as image_bindings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PREFIX = "lotus-performance-lineage-recovery-"
RECOVERY_COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.lineage-recovery.yml"
POSTGRES_PROOF = REPOSITORY_ROOT / "output" / "pg17-service-content.json"
POSTGRES_CHILD = "sha256:3cec7eb015ba8adb28139fa5c83b8489cdf0e666e53dfdf20f598ae0cc8739e3"
POSTGRES_CONFIG = "sha256:327daa8fae7178d61f93142f146b098467b345e10997b9eb79f63bd58e5c8f3c"
DATABASE_SERVICE = "performance-lineage-db"
MAX_METADATA_BYTES = 2 * 1024 * 1024
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
        if returncode == 0:
            cleanup_outcome += " but owned resource absence could not be verified"
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


def build_runtime_environment(
    project_name: str,
    runtime_image: str = image_bindings.DEFAULT_RUNTIME_IMAGE,
    postgres_image: str = image_bindings.RECOVERY_POSTGRES_IMAGE,
) -> dict[str, str]:
    """Build the bounded host and container configuration for one owned recovery run.

    Docker only receives the host variables it needs to start locally. Compose interpolation is
    then limited to resource names and the in-network database URL owned by this project; caller
    configuration cannot redirect the proof to another database, daemon, project, or host port.
    Every command also selects Docker's built-in ``default`` context explicitly, so a persisted
    caller-selected context cannot redirect the validator to a remote daemon.
    """
    image_bindings.require_runtime_image(runtime_image)
    image_bindings.require_recovery_postgres_image(postgres_image)
    return {
        **_host_command_environment(),
        "RUNTIME_BASE_IMAGE": runtime_image,
        "RECOVERY_POSTGRES_IMAGE": postgres_image,
        "LINEAGE_METADATA_DATABASE_URL": _LINEAGE_DATABASE_URL,
        "PA_LINEAGE_DB_CONTAINER_NAME": f"{project_name}-db",
        "PA_LINEAGE_VOLUME_INIT_CONTAINER_NAME": f"{project_name}-volume-init",
        "PA_SCHEMA_APPLY_CONTAINER_NAME": f"{project_name}-schema-apply",
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


def run_validation(
    runtime_image: str = image_bindings.DEFAULT_RUNTIME_IMAGE,
    postgres_image: str = image_bindings.RECOVERY_POSTGRES_IMAGE,
) -> dict[str, object]:
    """Run one recovery proof in a freshly allocated, invocation-owned namespace.

    The project identity is intentionally not caller-configurable. A same-prefix value does not
    establish ownership, and cleanup includes destructive volume removal.
    """
    image_bindings.verify_runtime_build_files(runtime_image)
    image_bindings.require_recovery_postgres_image(postgres_image)
    policy_root = qualified_postgres_policy()
    if os.path.lexists(POSTGRES_PROOF):
        raise ValueError("PostgreSQL proof output must be unused")
    project_name = validate_project_name(new_project_name())
    runtime_environment = build_runtime_environment(project_name, runtime_image, postgres_image)
    container_names = {
        "initializer": runtime_environment["PA_LINEAGE_VOLUME_INIT_CONTAINER_NAME"],
        "schema_apply": runtime_environment["PA_SCHEMA_APPLY_CONTAINER_NAME"],
        "analytics": runtime_environment["PA_ANALYTICS_CONTAINER_NAME"],
        "lineage_worker": runtime_environment["PA_LINEAGE_WORKER_CONTAINER_NAME"],
        "compute_executor": runtime_environment["PA_COMPUTE_EXECUTOR_CONTAINER_NAME"],
    }
    validation_error: Exception | None = None
    try:
        _run(compose_command(project_name, "up", "-d", "--no-deps", DATABASE_SERVICE), env=runtime_environment)
        postgres_proof = prove_owned_database(project_name, runtime_environment, policy_root)
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
        _assert_schema_apply_succeeded(container_names["schema_apply"], runtime_environment)
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
            "runtime_image": runtime_image,
            "postgres_image": postgres_image,
            "postgres_content_proof": postgres_proof,
            "initializer_exit_code": 0,
            "schema_apply_exit_code": 0,
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


def qualified_postgres_policy() -> Path:
    """Authenticate the fixed excluded checkout before executing its helper."""
    if os.path.lexists(REPOSITORY_ROOT / ".image-policy"):
        raise ValueError("Runtime policy must be removed before recovery builds")
    path = image_bindings.owned_policy_directory("output/pg17-image-policy")

    def command(arguments):
        return bounded_command_metadata(arguments, _host_command_environment())

    prefix = ["git", "-C", str(path)]
    actual_root = command(prefix + ["rev-parse", "--show-toplevel"]).strip()
    actual_head = command(prefix + ["rev-parse", "HEAD"]).strip()
    if Path(actual_root).resolve() != path or actual_head != image_bindings.RECOVERY_POLICY_REVISION:
        raise ValueError("PostgreSQL policy is not the exact qualified checkout")
    if command(prefix + ["status", "--porcelain=v1", "-z", "--untracked-files=all"]):
        raise ValueError("PostgreSQL policy checkout must be clean")
    for relative in (
        "automation/verify_acquired_service_image.py",
        "automation/validate_technology_governance_policy.py",
        "platform-contracts/technology-governance/lotus-technology-governance-policy.v1.json",
        "platform-contracts/technology-governance/technology-governance-policy.schema.json",
    ):
        expected = command(prefix + ["rev-parse", "HEAD:" + relative]).strip()
        actual = command(prefix + ["hash-object", "--path=" + relative, relative]).strip()
        if actual != expected:
            raise ValueError("PostgreSQL policy/helper differs from its committed blob")
    if command(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]):
        raise ValueError("Recovery build source must be clean")
    return path


def bounded_command_metadata(command: list[str], env: dict[str, str]) -> str:
    """Bound policy and owned-service metadata without retaining child streams."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        with subprocess.Popen(command, cwd=REPOSITORY_ROOT, env=env, stdout=stdout, stderr=stderr) as process:
            deadline = time.monotonic() + 30
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline or max(stdout.tell(), stderr.tell()) > MAX_METADATA_BYTES:
                        raise ValueError("Recovery metadata exceeded time/byte budget")
                    time.sleep(0.05)
                if process.returncode or max(stdout.tell(), stderr.tell()) > MAX_METADATA_BYTES:
                    raise ValueError("Recovery metadata command refused")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
        stdout.seek(0)
        return stdout.read().decode("utf-8")


def owned_database_id(project: str, env: dict[str, str]) -> str:
    container_id = bounded_command_metadata(
        compose_command(project, "ps", "--quiet", "--all", DATABASE_SERVICE), env
    ).strip()
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise ValueError("Recovery database must resolve exactly one full owned ID")
    metadata = json.loads(bounded_command_metadata(docker_command("container", "inspect", container_id), env))
    if not isinstance(metadata, list) or len(metadata) != 1:
        raise ValueError("Recovery database inspect must resolve exactly one container")
    container = metadata[0]
    if not isinstance(container, dict) or not isinstance(container.get("Config"), dict):
        raise ValueError("Recovery database inspect has invalid metadata shape")
    labels = container.get("Config", {}).get("Labels", {})
    if not isinstance(labels, dict) or not isinstance(container.get("State"), dict):
        raise ValueError("Recovery database inspect has invalid ownership/state shape")
    if (
        container.get("Id") != container_id
        or labels.get("com.docker.compose.project") != project
        or labels.get("com.docker.compose.service") != DATABASE_SERVICE
        or container.get("Config", {}).get("Image") != env["RECOVERY_POSTGRES_IMAGE"]
        or container.get("State", {}).get("Running") is not True
    ):
        raise ValueError("Recovery database identity/ownership differs from selected service")
    return container_id


def prove_owned_database(project: str, env: dict[str, str], policy_root: Path) -> dict:
    container_id = owned_database_id(project, env)
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(policy_root / "automation/verify_acquired_service_image.py"),
            "--container-id",
            container_id,
            "--expected-image",
            env["RECOVERY_POSTGRES_IMAGE"],
            "--expected-policy-commit",
            image_bindings.RECOVERY_POLICY_REVISION,
            "--output",
            str(POSTGRES_PROOF),
        ],
        cwd=REPOSITORY_ROOT,
        env=env,
        check=True,
        timeout=250,
    )
    if owned_database_id(project, env) != container_id:
        raise ValueError("Recovery database was replaced during content verification")
    if (
        POSTGRES_PROOF.is_symlink()
        or not POSTGRES_PROOF.is_file()
        or POSTGRES_PROOF.stat().st_size > MAX_METADATA_BYTES
    ):
        raise ValueError("PostgreSQL content proof must be a bounded regular file")
    proof = json.loads(POSTGRES_PROOF.read_text(encoding="utf-8"))
    if (
        not isinstance(proof, dict)
        or not isinstance(proof.get("policy_source"), dict)
        or type(proof.get("schema_version")) is not int
    ):
        raise ValueError("PostgreSQL content proof has invalid metadata shape")
    expected = {
        "schema_version": 1,
        "proof_type": "local-existing-service-content",
        "requested_image": env["RECOVERY_POSTGRES_IMAGE"],
        "service_container_id": container_id,
        "admitted_index_digest": image_bindings.RECOVERY_POSTGRES_IMAGE.partition("@")[2],
        "admitted_child_digest": POSTGRES_CHILD,
        "config_digest": POSTGRES_CONFIG,
        "platform": "linux/amd64",
    }
    if (
        any(proof.get(key) != value for key, value in expected.items())
        or proof.get("policy_source", {}).get("commit") != image_bindings.RECOVERY_POLICY_REVISION
        or any(
            proof.get(key) is not False
            for key in (
                "cold_acquisition_proven",
                "compressed_transfer_verified",
                "runtime_execution_verified",
                "raw_export_retained",
                "raw_inspect_retained",
            )
        )
    ):
        raise ValueError("PostgreSQL content proof differs from qualified service/policy binding")
    diff_ids = proof.get("rootfs_diff_ids")
    if (
        not isinstance(diff_ids, list)
        or not 1 <= len(diff_ids) <= 128
        or any(not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None for value in diff_ids)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(proof.get("service_image_id", ""))) is None
    ):
        raise ValueError("PostgreSQL content proof lacks checked image/RootFS identities")
    return {
        "path": "output/pg17-service-content.json",
        "service_container_id": container_id,
        "policy_commit": image_bindings.RECOVERY_POLICY_REVISION,
    }


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
    remaining_resources = _remaining_owned_resources(project_name, env)
    if completed.returncode or any(remaining_resources.values()):
        raise RecoveryCleanupError(
            project_name,
            completed.returncode,
            remaining_resources,
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


def _assert_schema_apply_succeeded(container_name: str, env: dict[str, str]) -> None:
    exit_code = _capture(docker_command("inspect", "--format", "{{.State.ExitCode}}", container_name), env=env).strip()
    if exit_code != "0":
        raise RuntimeError(f"durable schema owner exited with code {exit_code}")


def _wait_for_healthy_runtime(
    container_names: dict[str, str],
    env: dict[str, str],
    *,
    timeout_seconds: int = 180,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    pending = {name for key, name in container_names.items() if key not in {"initializer", "schema_apply"}}
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
    parser.add_argument("--runtime-image", default=image_bindings.DEFAULT_RUNTIME_IMAGE)
    parser.add_argument("--postgres-image", default=image_bindings.RECOVERY_POSTGRES_IMAGE)
    args = parser.parse_args()
    try:
        summary = run_validation(args.runtime_image, args.postgres_image)
    except (OSError, subprocess.SubprocessError, RecoveryValidationError, RuntimeError, ValueError) as exc:
        _fail(f"lineage volume recovery validation failed: {exc}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
