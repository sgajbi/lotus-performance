from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_seeded_contribution_rollout_artifacts import (
    generate_seeded_contribution_rollout_artifacts,
)


def test_generate_seeded_contribution_rollout_artifacts_writes_expected_bundle(tmp_path: Path):
    report = generate_seeded_contribution_rollout_artifacts(tmp_path)

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
