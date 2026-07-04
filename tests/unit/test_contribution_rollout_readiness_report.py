from __future__ import annotations

import json
from pathlib import Path

from scripts.contribution_rollout_readiness_report import (
    build_contribution_rollout_readiness_report,
)


def _write_response(tmp_path: Path, file_name: str, results_by_period: dict) -> Path:
    payload = {
        "calculation_id": "00000000-0000-0000-0000-000000000001",
        "portfolio_id": "P1",
        "input_mode": "stateless",
        "results_by_period": results_by_period,
        "meta": {
            "calculation_id": "00000000-0000-0000-0000-000000000001",
            "engine_version": "test",
            "precision_mode": "FLOAT64",
            "annualization": {"enabled": False, "basis": "BUS/252", "periods_per_year": None},
            "calendar": {"type": "BUSINESS", "trading_calendar": "NYSE"},
            "periods": {"requested": ["SI"], "master_start": "2025-01-01", "master_end": "2025-01-03"},
        },
        "diagnostics": {
            "nip_days": 0,
            "reset_days": 0,
            "effective_period_start": "2025-01-01",
            "notes": [],
        },
        "audit": {"counts": {}},
    }
    path = tmp_path / file_name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_build_contribution_rollout_readiness_report_marks_ready_controlled_rollout(tmp_path: Path):
    response_path = _write_response(
        tmp_path,
        "ready.json",
        {
            "SI": {
                "average_weight_methodology_status": {
                    "status": "PROMOTION_READY",
                    "max_shadow_delta_bp": 1200,
                    "is_material_shadow": True,
                    "is_cutover_candidate": True,
                    "is_promoted": False,
                    "blocker_reason_codes": [],
                }
            }
        },
    )

    report = build_contribution_rollout_readiness_report([response_path])

    assert report.total_periods == 1
    assert report.material_periods == 1
    assert report.promotion_ready_periods == 1
    assert report.promoted_periods == 0
    assert report.blocked_periods == 0
    assert report.blocked_economic_periods == 0
    assert report.blocked_methodology_periods == 0
    assert report.promotion_ready_rate_bp == 10000
    assert report.max_shadow_delta_bp == 1200
    assert report.status_counts == {"PROMOTION_READY": 1}
    assert report.blocker_reason_counts == {}
    assert report.blocker_category_counts == {"economic_integrity": 0, "methodology_guardrail": 0}
    assert report.recommendation == "READY_FOR_CONTROLLED_ROLLOUT"


def test_build_contribution_rollout_readiness_report_marks_hold_when_flow_blockers_exist(tmp_path: Path):
    response_path = _write_response(
        tmp_path,
        "blocked.json",
        {
            "SI": {
                "average_weight_methodology_status": {
                    "status": "BLOCKED",
                    "max_shadow_delta_bp": 1500,
                    "is_material_shadow": True,
                    "is_cutover_candidate": False,
                    "is_promoted": False,
                    "blocker_reason_codes": ["flow_balance"],
                }
            }
        },
    )

    report = build_contribution_rollout_readiness_report([response_path])

    assert report.material_periods == 1
    assert report.promotion_ready_periods == 0
    assert report.blocked_periods == 1
    assert report.blocked_economic_periods == 1
    assert report.blocked_methodology_periods == 0
    assert report.promotion_ready_rate_bp == 0
    assert report.blocker_reason_counts == {"flow_balance": 1}
    assert report.blocker_category_counts == {"economic_integrity": 1, "methodology_guardrail": 0}
    assert report.recommendation == "HOLD_BLOCKERS_PRESENT"


def test_build_contribution_rollout_readiness_report_marks_mixed_readiness_for_blended_material_traffic(
    tmp_path: Path,
):
    ready_path = _write_response(
        tmp_path,
        "ready.json",
        {
            "SI": {
                "average_weight_methodology_status": {
                    "status": "PROMOTION_READY",
                    "max_shadow_delta_bp": 1100,
                    "is_material_shadow": True,
                    "is_cutover_candidate": True,
                    "is_promoted": False,
                    "blocker_reason_codes": [],
                }
            }
        },
    )
    review_path = _write_response(
        tmp_path,
        "review.json",
        {
            "SI": {
                "average_weight_methodology_status": {
                    "status": "UNDER_REVIEW",
                    "max_shadow_delta_bp": 900,
                    "is_material_shadow": True,
                    "is_cutover_candidate": False,
                    "is_promoted": False,
                    "blocker_reason_codes": [],
                }
            }
        },
    )

    report = build_contribution_rollout_readiness_report([ready_path, review_path])

    assert report.material_periods == 2
    assert report.promotion_ready_periods == 1
    assert report.blocked_periods == 0
    assert report.blocked_economic_periods == 0
    assert report.blocked_methodology_periods == 0
    assert report.promotion_ready_rate_bp == 5000
    assert report.status_counts == {"PROMOTION_READY": 1, "UNDER_REVIEW": 1}
    assert report.blocker_category_counts == {"economic_integrity": 0, "methodology_guardrail": 0}
    assert report.recommendation == "MIXED_READYNESS_KEEP_CANDIDATE_ONLY"


def test_build_contribution_rollout_readiness_report_marks_no_material_shadow_when_only_noise_exists(
    tmp_path: Path,
):
    response_path = _write_response(
        tmp_path,
        "noise.json",
        {
            "SI": {
                "average_weight_methodology_status": {
                    "status": "NO_MATERIAL_SHADOW",
                    "max_shadow_delta_bp": 120,
                    "is_material_shadow": False,
                    "is_cutover_candidate": False,
                    "is_promoted": False,
                    "blocker_reason_codes": [],
                }
            }
        },
    )

    report = build_contribution_rollout_readiness_report([response_path])

    assert report.material_periods == 0
    assert report.blocked_economic_periods == 0
    assert report.blocked_methodology_periods == 0
    assert report.promotion_ready_rate_bp == 0
    assert report.blocker_category_counts == {"economic_integrity": 0, "methodology_guardrail": 0}
    assert report.recommendation == "NO_MATERIAL_SHADOW_TRAFFIC"


def test_build_contribution_rollout_readiness_report_counts_methodology_blockers_separately(tmp_path: Path):
    response_path = _write_response(
        tmp_path,
        "blocked_reset.json",
        {
            "SI": {
                "average_weight_methodology_status": {
                    "status": "BLOCKED",
                    "max_shadow_delta_bp": 1500,
                    "is_material_shadow": True,
                    "is_cutover_candidate": False,
                    "is_promoted": False,
                    "blocker_reason_codes": ["reset_alignment"],
                }
            }
        },
    )

    report = build_contribution_rollout_readiness_report([response_path])

    assert report.blocked_periods == 1
    assert report.blocked_economic_periods == 0
    assert report.blocked_methodology_periods == 1
    assert report.blocker_reason_counts == {"reset_alignment": 1}
    assert report.blocker_category_counts == {"economic_integrity": 0, "methodology_guardrail": 1}
    assert report.recommendation == "KEEP_SHADOW_ONLY_GATHER_MORE_EVIDENCE"
