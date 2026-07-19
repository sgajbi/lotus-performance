from __future__ import annotations

import pytest

from scripts.validate_lineage_volume_recovery import (
    PROJECT_PREFIX,
    compose_command,
    validate_project_name,
)


def test_validation_accepts_only_owned_disposable_project_names() -> None:
    project_name = f"{PROJECT_PREFIX}contract-1"

    assert validate_project_name(project_name.upper()) == project_name
    assert compose_command(project_name, "down", "-v")[-3:] == [
        project_name,
        "down",
        "-v",
    ]


@pytest.mark.parametrize(
    "project_name",
    (
        "lotus-performance",
        "default",
        f"{PROJECT_PREFIX}unsafe_value",
        f"{PROJECT_PREFIX}../unsafe",
        "",
    ),
)
def test_validation_rejects_projects_outside_owned_prefix(project_name: str) -> None:
    with pytest.raises(ValueError, match="project name must match"):
        validate_project_name(project_name)
