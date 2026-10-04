from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.services.lineage_metadata_store import get_lineage_metadata_store
from scripts.durable_schema_apply import apply_durable_schema


@pytest.mark.parametrize("schema_shape", ["current", "stale_index"])
def test_generate_seeded_contribution_rollout_artifacts_writes_expected_bundle(
    tmp_path: Path, monkeypatch, schema_shape
):
    # The seeded harness owns a disposable database, never the checkout's
    # retained metadata or canonical lineage artifacts.
    settings = get_settings()
    monkeypatch.setattr(settings, "LINEAGE_METADATA_DATABASE_URL", f"sqlite:///{tmp_path / 'rollout.db'}")
    monkeypatch.setattr(settings, "LINEAGE_STORAGE_PATH", tmp_path / "lineage")
    command = [
        sys.executable,
        "-m",
        "scripts.generate_seeded_contribution_rollout_artifacts",
        "--output-dir",
        str(tmp_path),
    ]
    environment = {
        **os.environ,
        "LINEAGE_METADATA_DATABASE_URL": settings.LINEAGE_METADATA_DATABASE_URL,
        "LINEAGE_STORAGE_PATH": str(settings.LINEAGE_STORAGE_PATH),
    }
    if schema_shape == "stale_index":
        assert apply_durable_schema().status == "passed"
        store = get_lineage_metadata_store()
        calculation_id = uuid4()
        store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
        retained = store.get_record(calculation_id)
        with store._engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX ix_lineage_payloads_created_at")
            connection.exec_driver_sql(
                "CREATE INDEX ix_lineage_payloads_created_at ON lineage_payloads (calculation_type)"
            )
        completed = subprocess.run(
            command, cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True, text=True
        )
        assert completed.returncode != 0
        assert "successful make migration-apply before cleanup" in completed.stderr
        assert store.get_record(calculation_id) == retained
        return
    # Exercise the documented fresh-process CLI, independently of other unit
    # tests' process-local lazy-proxy patches.
    completed = subprocess.run(
        command, cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True, text=True, check=True
    )
    report = SimpleNamespace(**json.loads(completed.stdout))

    assert (tmp_path / "no_material_shadow.json").exists()
    assert (tmp_path / "ready_candidate_shadow_only.json").exists()
    assert (tmp_path / "promoted_candidate.json").exists()
    assert (tmp_path / "blocked_flow_balance.json").exists()
    assert (tmp_path / "blocked_reset_alignment.json").exists()
    latest_path = tmp_path / "latest.json"
    assert latest_path.exists()

    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))

    assert report.total_periods == 5
    assert report.material_periods == 4
    assert report.promotion_ready_periods == 2
    assert report.promoted_periods == 1
    assert report.blocked_periods == 2
    assert report.blocked_economic_periods == 1
    assert report.blocked_methodology_periods == 1
    assert report.promotion_ready_rate_bp == 5000
    assert report.recommendation == "HOLD_BLOCKERS_PRESENT"
    assert latest_payload["recommendation"] == "HOLD_BLOCKERS_PRESENT"
    assert latest_payload["status_counts"]["NO_MATERIAL_SHADOW"] == 1
    assert latest_payload["status_counts"]["PROMOTION_READY"] == 1
    assert latest_payload["status_counts"]["PROMOTED"] == 1
    assert latest_payload["status_counts"]["BLOCKED"] == 2
    assert latest_payload["blocker_reason_counts"]["flow_balance"] == 1
    assert latest_payload["blocker_reason_counts"]["reset_alignment"] == 1
    assert latest_payload["blocker_category_counts"]["economic_integrity"] == 1
    assert latest_payload["blocker_category_counts"]["methodology_guardrail"] == 1
