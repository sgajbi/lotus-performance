from pathlib import Path


def test_runtime_services_share_lineage_artifact_volume() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "performance-lineage-data:" in compose
    for service in (
        "performance-analytics",
        "performance-lineage-worker",
        "performance-compute-executor",
        "performance-runtime-retention-worker",
    ):
        service_start = compose.index(f"  {service}:")
        next_service_start = compose.find("\n  performance-", service_start + 1)
        service_block = (
            compose[service_start:] if next_service_start == -1 else compose[service_start:next_service_start]
        )
        assert "- performance-lineage-data:/app/lineage_data" in service_block


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
