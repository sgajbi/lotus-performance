"""Fresh operator processes with isolated storage and no inherited package path."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def operator_environment(tmp_path, request):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update(
        LINEAGE_METADATA_DATABASE_URL=f"sqlite:///{tmp_path / 'runtime.db'}",
        LINEAGE_STORAGE_PATH=str(tmp_path / "lineage"),
        RUNTIME_RETENTION_ARTIFACT_PATH=str(tmp_path / "evidence"),
        RUNTIME_RETENTION_LEGAL_HOLD_PATH=str(tmp_path / "holds.json"),
        RUNTIME_RETENTION_DAYS="30",
        RUNTIME_RETENTION_HISTORY_LIMIT="30",
        RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS="90",
        RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID="retention-contract-operator",
        RUNTIME_RETENTION_AUTOMATION_JOB_ID="retention-contract-job",
        PATH=os.pathsep.join((str(Path(sys.executable).parent), environment.get("PATH", ""))),
    )
    return request.config.rootpath, environment, tmp_path


def _run_operator(operator_environment, *arguments):
    root, environment, _ = operator_environment
    return subprocess.run(
        [sys.executable, "-m", "scripts.runtime_retention_cleanup", *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _apply_owner(operator_environment):
    root, environment, _ = operator_environment
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores; "
            "bootstrap_durable_metadata_stores()",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_retention_help_needs_no_database_or_path_setup(operator_environment):
    result = _run_operator(operator_environment, "--help")
    assert result.returncode == 0, result.stderr
    assert "Without this flag the command runs in dry-run mode" in " ".join(result.stdout.split())
    assert "--operator-id" in result.stdout
    assert list(operator_environment[2].iterdir()) == []


def test_retention_dry_run_persists_attributable_plan(operator_environment):
    _apply_owner(operator_environment)
    result = _run_operator(
        operator_environment,
        "--operator-id",
        "manual-contract-operator",
        "--job-id",
        "manual-contract-job",
        "--retention-days",
        "1",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cleanup_mode"] == "dry_run"
    assert payload["status"] == "planned"
    assert payload["retention_days"] == 1
    assert payload["operator_id"] == "manual-contract-operator"
    assert payload["trigger_mode"] == "manual"
    assert payload["job_id"] == "manual-contract-job"
    for family in ("execution", "compute_job", "async_result", "lineage_record", "lineage_artifact"):
        assert payload[f"prunable_{family}_count"] == 0
        assert payload[f"protected_{family}_count"] == 0
    assert payload["phase_results"] == []
    evidence = operator_environment[2] / "evidence"
    assert json.loads((evidence / "latest.json").read_text()) == payload
    assert json.loads((evidence / payload["evidence_file_name"]).read_text()) == payload
    assert json.loads((evidence / "manifest.json").read_text())["latest_file_name"] == payload["evidence_file_name"]


@pytest.mark.parametrize("option", ["--retention-days", "--retention-limit", "--retention-max-age-days"])
@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_retention_invalid_override_refuses_before_apply(operator_environment, option, value):
    _apply_owner(operator_environment)
    storage = operator_environment[2]
    before = hashlib.sha256((storage / "runtime.db").read_bytes()).hexdigest()
    result = _run_operator(operator_environment, "--apply", option, value)
    assert result.returncode == 2, result.stderr
    assert "positive integer" in result.stderr
    assert not (storage / "evidence").exists()
    assert hashlib.sha256((storage / "runtime.db").read_bytes()).hexdigest() == before


@pytest.mark.parametrize("option", ["--retention-limit", "--retention-max-age-days"])
def test_retention_positive_history_boundary_is_accepted(operator_environment, option):
    _apply_owner(operator_environment)
    result = _run_operator(operator_environment, option, "1")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "planned"
    manifest = json.loads((operator_environment[2] / "evidence" / "manifest.json").read_text())
    field = "retention_limit" if option == "--retention-limit" else "retention_max_age_days"
    assert manifest[field] == 1


def test_documented_make_smoke_uses_scheduled_dry_run(operator_environment):
    _apply_owner(operator_environment)
    root, environment, storage = operator_environment
    result = subprocess.run(
        ["make", "runtime-retention-smoke"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads((storage / "evidence" / "latest.json").read_text())
    assert payload["cleanup_mode"] == "dry_run"
    assert payload["status"] == "planned"
    assert payload["trigger_mode"] == "scheduled"
    assert payload["operator_id"] == "retention-contract-operator"
    assert payload["job_id"] == "retention-contract-job"
    assert payload["retention_days"] == 30
