from pathlib import Path

from scripts.dependency_health_check import (
    MINIMUM_AUDIT_SETUPTOOLS_VERSION,
    _bootstrap_command,
)


def test_dependency_audit_bootstrap_upgrades_vulnerable_build_tooling() -> None:
    python = Path("audit-venv") / "bin" / "python"

    assert _bootstrap_command(python) == [
        str(python),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        f"setuptools>={MINIMUM_AUDIT_SETUPTOOLS_VERSION}",
    ]
    assert tuple(int(part) for part in MINIMUM_AUDIT_SETUPTOOLS_VERSION.split(".")) >= (83, 0, 0)
