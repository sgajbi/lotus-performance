from pathlib import Path

RUNTIME_SERVICES = (
    "performance-analytics",
    "performance-lineage-worker",
    "performance-compute-executor",
    "performance-runtime-retention-worker",
)


def _service_block(compose: str, service: str) -> str:
    service_start = compose.index(f"  {service}:")
    next_service_start = compose.find("\n  performance-", service_start + 1)
    return compose[service_start:] if next_service_start == -1 else compose[service_start:next_service_start]


def test_runtime_services_share_lineage_artifact_volume() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "performance-lineage-data:" in compose
    for service in RUNTIME_SERVICES:
        assert "- performance-lineage-data:/app/lineage_data" in _service_block(compose, service)


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
