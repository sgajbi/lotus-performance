from scripts.github_action_runtime_guard import (
    _major_version,
    validate_artifact_action_versions,
    validate_workflow_job_timeouts,
)


def test_validate_artifact_action_versions_accepts_node24_artifact_actions(tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "steps:",
                "  - uses: actions/upload-artifact@v7",
                "  - uses: actions/download-artifact@v8",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_artifact_action_versions(workflow_dir) == []


def test_validate_artifact_action_versions_reports_node20_era_artifact_actions(tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "steps:",
                "  - uses: actions/upload-artifact@v4",
                "  - uses: actions/download-artifact@v5",
            ]
        ),
        encoding="utf-8",
    )

    findings = validate_artifact_action_versions(workflow_dir)

    assert [finding.format() for finding in findings] == [
        ".github/workflows/ci.yml:2: actions/upload-artifact@v4 must be v7 or newer for Node 24 runner compatibility",
        ".github/workflows/ci.yml:3: actions/download-artifact@v5 must be v8 or newer for Node 24 runner compatibility",
    ]


def test_major_version_rejects_unbounded_or_non_semver_refs():
    assert _major_version("main") == 0
    assert _major_version("v7") == 7
    assert _major_version("v8.0.1") == 8


def test_validate_workflow_job_timeouts_accepts_bounded_jobs(tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "jobs:",
                "  static-quality:",
                "    runs-on: ubuntu-latest",
                "    timeout-minutes: 20",
                "    steps:",
                "      - run: make lint",
                "  tests:",
                "    runs-on: ubuntu-latest",
                "    timeout-minutes: 45",
                "    steps:",
                "      - run: make test-unit",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_workflow_job_timeouts(workflow_dir) == []


def test_validate_workflow_job_timeouts_reports_unbounded_jobs(tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "jobs:",
                "  static-quality:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - run: make lint",
                "  tests:",
                "    runs-on: ubuntu-latest",
                "    timeout-minutes: 45",
                "    steps:",
                "      - run: make test-unit",
            ]
        ),
        encoding="utf-8",
    )

    findings = validate_workflow_job_timeouts(workflow_dir)

    assert [finding.format() for finding in findings] == [
        ".github/workflows/ci.yml:2: workflow job static-quality must declare timeout-minutes"
    ]
