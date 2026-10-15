"""Bind central admission output to the selected runtime build and provenance."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IMMUTABLE_IMAGE = re.compile(r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}")
RUNTIME_DIGEST = "sha256:e529028263dbe6910a2d96f7d2b8f5266385e917fd45d286ef166977c094a51e"
DEFAULT_RUNTIME_IMAGE = f"public.ecr.aws/docker/library/python@{RUNTIME_DIGEST}"
ORIGINAL_RUNTIME_IMAGE = f"docker.io/library/python@{RUNTIME_DIGEST}"
RECOVERY_POSTGRES_IMAGE = (
    "docker.io/library/postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
)
RECOVERY_POLICY_REVISION = "cd7563c52008fffee8a37b1b6c3235480823a5cd"


def require_runtime_image(image: str) -> None:
    """Enforce the consumer's two qualified bindings, without selecting a registry."""
    if image not in (DEFAULT_RUNTIME_IMAGE, ORIGINAL_RUNTIME_IMAGE):
        raise ValueError("Runtime image must be one of the two qualified exact-source Python references")


def require_immutable(image: str) -> None:
    if IMMUTABLE_IMAGE.fullmatch(image) is None:
        raise ValueError("Admission output must be a nonempty immutable image reference")


def require_recovery_postgres_image(image: str) -> None:
    if image != RECOVERY_POSTGRES_IMAGE:
        raise ValueError("Recovery PostgreSQL must be the qualified exact original PG17 reference")


def owned_policy_directory(relative: str) -> Path:
    """Reject symlinks, Windows reparse points and foreign resolved checkout paths."""
    if relative not in {".image-policy", "output/pg17-image-policy"}:
        raise ValueError("Qualified policy path is not an owned checkout")
    root = ROOT.resolve()
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Qualified policy path must not contain a reparse point")
        if not path.is_dir():
            raise ValueError("Qualified policy path must be an owned directory")
    if path.resolve() != root / relative:
        raise ValueError("Qualified policy path resolves outside its exact owner")
    return path


def runtime_acquisition_module():
    if __package__:
        from . import verify_runtime_image_acquisition
    else:
        import verify_runtime_image_acquisition
    return verify_runtime_image_acquisition


def remove_owned_runtime_policy() -> None:
    if any(
        key in os.environ
        for key in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_PARAMETERS",
        )
    ):
        raise ValueError("Runtime policy cleanup refuses inherited Git overrides")
    path = owned_policy_directory(".image-policy")
    acquisition = runtime_acquisition_module()
    acquisition.qualified_policy_identity(path)
    shutil.rmtree(path)
    if acquisition.command(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]):
        raise ValueError("Build source is not clean after qualified policy removal")


def verify_runtime_build_files(runtime_image: str) -> None:
    require_runtime_image(runtime_image)
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    verify_dockerfile(dockerfile)
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    expected = "${RUNTIME_BASE_IMAGE:-" + DEFAULT_RUNTIME_IMAGE + "}"
    verify_compose_builds(compose, expected)


def docker_instructions(dockerfile: str) -> list[str]:
    instructions = []
    pending = ""
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending += stripped.removesuffix("\\").rstrip()
        if stripped.endswith("\\"):
            pending += " "
            continue
        keyword, *arguments = pending.split(maxsplit=1)
        instructions.append(keyword.upper() + (" " + arguments[0] if arguments else ""))
        pending = ""
    if pending:
        raise ValueError("Dockerfile has an unfinished continuation")
    return instructions


def verify_dockerfile(dockerfile: str) -> None:
    instructions = docker_instructions(dockerfile)
    if (
        instructions[:3]
        != [
            f"ARG PYTHON_BASE_IMAGE={DEFAULT_RUNTIME_IMAGE}",
            "FROM ${PYTHON_BASE_IMAGE} AS runtime",
            "ARG PYTHON_BASE_IMAGE",
        ]
        or sum(line.startswith("FROM ") for line in instructions) != 1
    ):
        raise ValueError("Dockerfile must consume the selected runtime build argument")
    verify_base_arguments(instructions)
    verify_no_base_environment_override(instructions)
    verify_distribution_labels(dockerfile)


def verify_base_arguments(instructions: list[str]) -> None:
    declarations = []
    for instruction in instructions:
        if instruction.startswith("ARG "):
            arguments = shlex.split(instruction.partition(" ")[2])
            if len(arguments) != 1:
                raise ValueError("Supported Dockerfile contract requires one binding per ARG instruction")
            declarations.append(arguments[0].partition("=")[0])
    if declarations.count("PYTHON_BASE_IMAGE") != 2:
        raise ValueError("Dockerfile must not redefine the selected runtime build argument")


def verify_no_base_environment_override(instructions: list[str]) -> None:
    for instruction in instructions:
        if instruction.startswith("ENV "):
            names = [token.partition("=")[0] for token in shlex.split(instruction.partition(" ")[2])]
            if "PYTHON_BASE_IMAGE" in names:
                raise ValueError("ENV must not override the selected runtime build argument")


def label_assignments(dockerfile: str) -> list[tuple[str, str, str]]:
    assignments = []
    for instruction in docker_instructions(dockerfile):
        if instruction.startswith("LABEL "):
            arguments = instruction.partition(" ")[2]
            lexer = shlex.shlex(arguments, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = ""
            while True:
                start = lexer.instream.tell()
                token = lexer.get_token()
                if token is None:
                    break
                raw = arguments[start : lexer.instream.tell()].strip()
                key, _, value = token.partition("=")
                assignments.append((key, value, raw))
    return assignments


def verify_distribution_labels(dockerfile: str) -> None:
    assignments = label_assignments(dockerfile)
    for label, expected in (
        ("lotus.image.base.distribution", "${PYTHON_BASE_IMAGE}"),
        ("org.opencontainers.image.base.name", "docker.io/library/python"),
        ("org.opencontainers.image.base.digest", RUNTIME_DIGEST),
    ):
        if [(value, raw) for key, value, raw in assignments if key == label] != [(expected, f'{label}="{expected}"')]:
            raise ValueError(f"Dockerfile provenance does not bind {label}")


def verify_compose_builds(compose: dict, runtime_image: str) -> None:
    builds = [service["build"] for service in compose["services"].values() if "build" in service]
    if not builds:
        raise ValueError("Compose must retain its runtime builds")
    for build in builds:
        if (
            build.get("args", {}).get("PYTHON_BASE_IMAGE") != runtime_image
            or build.get("target") != "runtime"
            or build.get("platforms") != ["linux/amd64"]
        ):
            raise ValueError("Compose runtime builds must consume the selected image and linux/amd64 platform")


def verify_resolved_recovery(compose: dict, runtime_image: str, postgres_image: str) -> None:
    verify_compose_builds(compose, runtime_image)
    service = compose["services"]["performance-lineage-db"]
    if service.get("image") != postgres_image or service.get("platform") != "linux/amd64":
        raise ValueError("Recovery Compose does not consume the admitted PostgreSQL image/platform")


def verify_bindings(runtime_image: str, postgres_image: str | None = None) -> dict[str, str]:
    verify_runtime_build_files(runtime_image)
    bindings = {"runtime_image": runtime_image, "platform": "linux/amd64"}
    if postgres_image is not None:
        require_recovery_postgres_image(postgres_image)
        environment = dict(os.environ, RUNTIME_BASE_IMAGE=runtime_image, RECOVERY_POSTGRES_IMAGE=postgres_image)
        for key in (
            "COMPOSE_FILE",
            "COMPOSE_PROFILES",
            "COMPOSE_ENV_FILES",
            "COMPOSE_PROJECT_NAME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
        ):
            environment.pop(key, None)
        result = subprocess.run(
            [
                "docker",
                "--context",
                "default",
                "compose",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "-f",
                str(ROOT / "docker-compose.lineage-recovery.yml"),
                "config",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=environment,
        )
        verify_resolved_recovery(json.loads(result.stdout), runtime_image, postgres_image)
        bindings["postgres_image"] = postgres_image
    return bindings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--postgres-image")
    parser.add_argument("--remove-runtime-policy", action="store_true")
    args = parser.parse_args(argv)
    try:
        bindings = verify_bindings(args.runtime_image, args.postgres_image)
        if args.remove_runtime_policy:
            remove_owned_runtime_policy()
    except (
        ValueError,
        OSError,
        subprocess.CalledProcessError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        yaml.YAMLError,
    ) as error:
        print(f"Image binding refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(bindings, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
