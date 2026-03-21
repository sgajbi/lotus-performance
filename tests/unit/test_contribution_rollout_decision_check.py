from __future__ import annotations

from scripts.contribution_rollout_decision_check import evaluate_contribution_rollout_decision


def test_contribution_rollout_decision_holds_when_no_material_periods_exist():
    decision = evaluate_contribution_rollout_decision(
        {
            "recommendation": "NO_MATERIAL_SHADOW_TRAFFIC",
            "material_periods": 0,
            "promotion_ready_rate_bp": 0,
            "blocked_periods": 0,
            "blocker_reason_counts": {},
        }
    )

    assert decision.outcome == "HOLD"
    assert decision.approved is False
    assert decision.hold_category == "insufficient_evidence"
    assert decision.secondary_hold_categories == []
    assert "Gather broader non-prod contribution responses" in decision.recommended_next_action
    assert "not enough rollout evidence" in decision.reason


def test_contribution_rollout_decision_holds_when_economic_integrity_blockers_exist():
    decision = evaluate_contribution_rollout_decision(
        {
            "recommendation": "HOLD_BLOCKERS_PRESENT",
            "material_periods": 2,
            "promotion_ready_rate_bp": 5000,
            "blocked_periods": 1,
            "blocker_reason_counts": {"flow_balance": 1},
        }
    )

    assert decision.outcome == "HOLD"
    assert decision.approved is False
    assert decision.hold_category == "economic_integrity"
    assert decision.secondary_hold_categories == []
    assert "economic-integrity blockers as promotion fences" in decision.recommended_next_action
    assert "Economic-integrity blockers" in decision.reason


def test_contribution_rollout_decision_holds_when_methodology_guardrail_blockers_exist():
    decision = evaluate_contribution_rollout_decision(
        {
            "recommendation": "KEEP_SHADOW_ONLY_GATHER_MORE_EVIDENCE",
            "material_periods": 2,
            "promotion_ready_rate_bp": 5000,
            "blocked_periods": 1,
            "blocker_reason_counts": {"reset_alignment": 1},
        }
    )

    assert decision.outcome == "HOLD"
    assert decision.approved is False
    assert decision.hold_category == "methodology_guardrail"
    assert decision.secondary_hold_categories == []
    assert "reset-alignment or timeseries guardrails" in decision.recommended_next_action
    assert "Methodology guardrail blockers" in decision.reason


def test_contribution_rollout_decision_reports_secondary_hold_categories():
    decision = evaluate_contribution_rollout_decision(
        {
            "recommendation": "HOLD_BLOCKERS_PRESENT",
            "material_periods": 4,
            "promotion_ready_rate_bp": 5000,
            "blocked_periods": 2,
            "blocker_reason_counts": {"flow_balance": 1, "reset_alignment": 1},
        }
    )

    assert decision.outcome == "HOLD"
    assert decision.approved is False
    assert decision.hold_category == "economic_integrity"
    assert decision.secondary_hold_categories == ["methodology_guardrail"]
    assert "review reset-alignment guardrails separately" in decision.recommended_next_action


def test_contribution_rollout_decision_holds_when_ready_share_is_below_threshold():
    decision = evaluate_contribution_rollout_decision(
        {
            "recommendation": "MIXED_READYNESS_KEEP_CANDIDATE_ONLY",
            "material_periods": 5,
            "promotion_ready_rate_bp": 6000,
            "blocked_periods": 0,
            "blocker_reason_counts": {},
        },
        minimum_ready_rate_bp=8000,
    )

    assert decision.outcome == "HOLD"
    assert decision.approved is False
    assert decision.hold_category == "below_threshold"
    assert decision.secondary_hold_categories == []
    assert "gather more promotion-ready material periods" in decision.recommended_next_action
    assert "below the configured rollout threshold" in decision.reason


def test_contribution_rollout_decision_marks_ready_when_clean_threshold_is_met():
    decision = evaluate_contribution_rollout_decision(
        {
            "recommendation": "READY_FOR_CONTROLLED_ROLLOUT",
            "material_periods": 4,
            "promotion_ready_rate_bp": 10000,
            "blocked_periods": 0,
            "blocker_reason_counts": {},
        },
        minimum_ready_rate_bp=8000,
    )

    assert decision.outcome == "READY"
    assert decision.approved is True
    assert decision.hold_category == "none"
    assert decision.secondary_hold_categories == []
    assert "Controlled rollout can proceed" in decision.recommended_next_action
    assert "controlled rollout" in decision.reason.lower()
