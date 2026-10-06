from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from scripts.ci_local_compose_project import compose_project_name

RUNTIME_SERVICES = (
    "performance-analytics",
    "performance-lineage-worker",
    "performance-compute-executor",
    "performance-runtime-retention-worker",
)


def _assert_runtime_privilege_boundary(service: dict, name: str) -> None:
    assert service.get("cap_drop") == ["ALL"], f"{name}: all capabilities must be dropped"
    assert not service.get("cap_add"), f"{name}: capabilities cannot be re-added"
    assert service.get("security_opt") == ["no-new-privileges:true"], f"{name}: privilege elevation must be denied"
    assert service.get("user", "lotus") in ("lotus", "10001", "10001:10001"), f"{name}: runtime user cannot be root"


def test_all_runtime_services_deny_privilege_elevation() -> None:
    services = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))["services"]
    for name in RUNTIME_SERVICES:
        _assert_runtime_privilege_boundary(services[name], name)


@pytest.mark.parametrize("name", RUNTIME_SERVICES)
@pytest.mark.parametrize(
    ("key", "value", "reason"),
    (
        ("cap_drop", [], "all capabilities"),
        ("cap_add", ["SYS_ADMIN"], "cannot be re-added"),
        ("security_opt", [], "privilege elevation"),
        ("user", "0:0", "cannot be root"),
    ),
)
def test_runtime_privilege_guard_refuses_regressed_configuration(name, key, value, reason) -> None:
    services = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))["services"]
    mutant = deepcopy(services[name])
    mutant[key] = value
    with pytest.raises(AssertionError, match=reason):
        _assert_runtime_privilege_boundary(mutant, name)


def _service_block(compose: str, service: str) -> str:
    service_start = compose.index(f"  {service}:")
    next_service_start = compose.find("\n  performance-", service_start + 1)
    return compose[service_start:] if next_service_start == -1 else compose[service_start:next_service_start]


def test_runtime_services_share_lineage_artifact_volume() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "performance-lineage-data:" in compose
    for service in RUNTIME_SERVICES:
        assert "- performance-lineage-data:/app/lineage_data" in _service_block(compose, service)


def test_runtime_container_names_are_overrideable_for_isolated_recovery_proof() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for variable in (
        "PA_LINEAGE_DB_CONTAINER_NAME",
        "PA_LINEAGE_VOLUME_INIT_CONTAINER_NAME",
        "PA_SCHEMA_APPLY_CONTAINER_NAME",
        "PA_ANALYTICS_CONTAINER_NAME",
        "PA_LINEAGE_WORKER_CONTAINER_NAME",
        "PA_COMPUTE_EXECUTOR_CONTAINER_NAME",
        "PA_RUNTIME_RETENTION_CONTAINER_NAME",
    ):
        assert f"${{{variable}:-" in compose


def test_runtime_services_wait_for_bounded_lineage_volume_initialization() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    initializer = _service_block(compose, "performance-lineage-volume-init")

    assert 'user: "0:0"' in initializer
    assert "chown -R 10001:10001 /app/lineage_data" in initializer
    assert "chmod 0770 /app/lineage_data" in initializer
    assert "10001:10001:770" in initializer
    assert "read_only: true" in initializer
    assert "- ALL" in initializer
    assert "- CHOWN" in initializer
    assert "- DAC_OVERRIDE" in initializer
    assert "- FOWNER" in initializer
    assert "- no-new-privileges:true" in initializer
    assert "- performance-lineage-data:/app/lineage_data" in initializer

    for service in RUNTIME_SERVICES:
        service_block = _service_block(compose, service)
        assert "performance-lineage-volume-init:" in service_block
        assert "condition: service_completed_successfully" in service_block


def test_runtime_roles_wait_for_source_matched_read_only_schema_owner() -> None:
    services = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))["services"]
    owner = services["performance-schema-apply"]
    assert owner["command"] == [
        "python",
        "-m",
        "scripts.durable_schema_apply",
        "--output-dir",
        "/tmp/durable-schema-apply",
    ]
    assert owner["read_only"] is True and owner["restart"] == "no"
    assert owner["healthcheck"] == {"disable": True}
    assert owner["cap_drop"] == ["ALL"]
    assert owner["security_opt"] == ["no-new-privileges:true"]
    assert owner["depends_on"]["performance-lineage-db"]["condition"] == "service_healthy"
    assert owner["depends_on"]["performance-lineage-volume-init"]["condition"] == "service_completed_successfully"
    assert owner["volumes"] == ["performance-lineage-data:/app/lineage_data"]
    for name in RUNTIME_SERVICES:
        runtime = services[name]
        assert runtime["depends_on"]["performance-schema-apply"]["condition"] == "service_completed_successfully"
        assert runtime["build"] == owner["build"]
        assert (
            runtime["environment"]["LINEAGE_METADATA_DATABASE_URL"]
            == owner["environment"]["LINEAGE_METADATA_DATABASE_URL"]
        )


def test_docker_build_context_excludes_generated_runtime_state() -> None:
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()

    for generated_path in (
        "output",
        "lineage_data",
        "*.db",
        "*.db-shm",
        "*.db-wal",
        "*.sqlite",
        "*.sqlite3",
    ):
        assert generated_path in dockerignore


def test_ci_local_compose_lifecycle_uses_one_checkout_specific_project() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    compose = Path("docker-compose.ci-local.yml").read_text(encoding="utf-8")
    project_option = '--project-name "$(CI_LOCAL_COMPOSE_PROJECT)" -f docker-compose.ci-local.yml'

    assert "CI_LOCAL_COMPOSE_PROJECT ?= $(shell python scripts/ci_local_compose_project.py)" in makefile
    assert "CI_LOCAL_GIT_DIR ?= $(shell git rev-parse --git-common-dir)" in makefile
    assert "CI_LOCAL_GIT_WORKTREE_DIR ?= $(shell git rev-parse --absolute-git-dir)" in makefile
    assert makefile.count(project_option) == 2
    assert (
        makefile.count(
            "CI_LOCAL_GIT_DIR=$(call shellquote,$(CI_LOCAL_GIT_DIR)) "
            "CI_LOCAL_GIT_WORKTREE_DIR=$(call shellquote,$(CI_LOCAL_GIT_WORKTREE_DIR)) docker compose"
        )
        == 2
    )
    assert "docker compose -f docker-compose.ci-local.yml down" not in makefile
    assert "apt-get install -y --no-install-recommends git make" in compose
    assert "git config --global --add safe.directory /workspace" in compose
    assert "source: ." in compose
    assert "target: /source" in compose
    assert "read_only: true" in compose
    assert "- /workspace" in compose
    assert "source: ${CI_LOCAL_GIT_DIR:?CI_LOCAL_GIT_DIR must name the checkout Git common directory}" in compose
    assert "target: /git-common" in compose
    assert (
        "source: ${CI_LOCAL_GIT_WORKTREE_DIR:?CI_LOCAL_GIT_WORKTREE_DIR must name the active Git directory}" in compose
    )
    assert "target: /git-worktree-source" in compose
    assert "tar -C /source" in compose
    for excluded_path in (".git", ".venv", "artifacts", "output", "lineage_data", "*.db", ".coverage*"):
        assert f"--exclude={excluded_path}" in compose or f"--exclude='{excluded_path}'" in compose
    assert "cp -a /source/. /workspace/" not in compose
    assert "cp -a /git-worktree-source/. /workspace/.git/" in compose
    assert "printf '/git-common\\n' > /workspace/.git/commondir" in compose
    assert "    environment:" not in compose
    assert "--requirement requirements.txt --requirement requirements-dev.txt" in compose
    assert "--requirements" not in compose
    assert "coverage report --fail-under=99" in compose


def test_ci_local_compose_project_name_is_stable_and_checkout_specific(tmp_path: Path) -> None:
    first = tmp_path / "checkout"
    second = tmp_path / "other" / "checkout"
    first.mkdir()
    second.mkdir(parents=True)

    assert compose_project_name(first) == compose_project_name(first)
    assert compose_project_name(first) != compose_project_name(second)
    assert compose_project_name(first).startswith("lotus-performance-ci-local-checkout-")
