from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.workers import healthcheck as worker_healthcheck

ROOT = Path(__file__).resolve().parents[3]


def _makefile_target_definition(target: str) -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    prefix = f"{target}:"
    start = next(index for index, line in enumerate(lines) if line.startswith(prefix))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break
        block.append(line)
    return "\n".join(block)


def test_dockerfile_uses_minimized_non_root_runtime_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "COPY requirements.txt ./" in dockerfile
    assert "requirements-dev.txt" not in dockerfile
    assert "useradd --system --uid 10001" in dockerfile
    assert "USER lotus" in dockerfile
    assert "COPY --chown=lotus:lotus . ." in dockerfile
    assert "mkdir -p /app/lineage_data /app/artifacts /app/output" in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "PYTHONUNBUFFERED=1" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/health/live" in dockerfile
    assert "SECRET" not in dockerfile
    assert "PASSWORD" not in dockerfile


def test_runtime_requirements_exclude_test_and_development_tooling() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    forbidden_runtime_packages = (
        "coverage",
        "iniconfig",
        "pluggy",
        "py-cpuinfo",
        "pygments",
        "pytest",
        "pytest-asyncio",
        "pytest-benchmark",
        "pytest-cov",
        "pytest-mock",
    )

    for package in forbidden_runtime_packages:
        assert f"{package}==" not in requirements.lower()


def test_container_build_targets_production_runtime_stage() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    docker_build = _makefile_target_definition("docker-build")

    assert "CONTAINER_BUILD_TARGET ?= runtime" in makefile
    assert "--target $(CONTAINER_BUILD_TARGET)" in docker_build
    assert "requirements-dev.txt" not in docker_build


def test_compose_services_build_runtime_target_and_expose_healthchecks() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service_name in (
        "performance-analytics",
        "performance-lineage-worker",
        "performance-compute-executor",
        "performance-runtime-retention-worker",
    ):
        assert f"  {service_name}:" in compose
    assert compose.count("target: runtime") == 4
    assert "/health/ready" in compose
    assert '["CMD", "python", "-m", "app.workers.healthcheck", "lineage"]' in compose
    assert '["CMD", "python", "-m", "app.workers.healthcheck", "compute-executor"]' in compose
    assert '["CMD", "python", "-m", "app.workers.healthcheck", "runtime-retention"]' in compose


def test_worker_healthcheck_reports_ready_when_shared_runtime_dependencies_are_ready(mocker) -> None:
    mocker.patch(
        "app.workers.healthcheck.check_durable_metadata_store_ready",
        return_value=SimpleNamespace(is_ready=True, status="ready", reason=None),
    )

    assert worker_healthcheck.check_worker_ready("lineage") == (True, "ready")
    assert worker_healthcheck.main(["compute-executor"]) == 0


def test_worker_healthcheck_fails_closed_for_unready_or_unknown_worker(mocker) -> None:
    mocker.patch(
        "app.workers.healthcheck.check_durable_metadata_store_ready",
        return_value=SimpleNamespace(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_schema_incomplete",
        ),
    )

    assert worker_healthcheck.check_worker_ready("runtime-retention") == (
        False,
        "durable_metadata_schema_incomplete",
    )
    assert worker_healthcheck.main(["runtime-retention"]) == 1
    assert worker_healthcheck.check_worker_ready("unknown") == (False, "unsupported_worker:unknown")
