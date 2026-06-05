from app.services.contribution_audit import (
    AverageWeightShadowAuditState,
    _contribution_methodology_notes,
    _position_flow_balance_notes,
)


def test_average_weight_shadow_notes_distinguish_material_and_characterization_delta():
    material_state = AverageWeightShadowAuditState(delta_positions=3, delta_max_bp=600)
    characterization_state = AverageWeightShadowAuditState(delta_positions=2, delta_max_bp=100)

    material_notes = material_state._average_weight_shadow_notes()
    characterization_notes = characterization_state._average_weight_shadow_notes()

    assert len(material_notes) == 2
    assert any("differs materially" in note for note in material_notes)
    assert characterization_notes == [
        "Reset-aware average-weight shadow differs from the active mean-weight output for "
        "2 position-period rows. The maximum delta was 100 basis points, which is still under characterization."
    ]


def test_rollout_posture_notes_report_guardrail_blockers_and_promotion():
    audit_state = AverageWeightShadowAuditState(material_periods=2, cutover_candidate_periods=1)
    audit_state.record_cutover_assessment(
        is_cutover_candidate=False,
        blocker_reason_codes={"flow_balance", "reset_alignment"},
    )
    audit_state.record_cutover_assessment(
        is_cutover_candidate=True,
        blocker_reason_codes=set(),
        is_promoted=True,
    )

    notes = audit_state._rollout_posture_notes()

    assert any("strong candidates for a future denominator cutover study" in note for note in notes)
    assert any("promotion was applied" in note for note in notes)
    assert any("stock and cash legs did not cancel cleanly" in note for note in notes)
    assert any("portfolio and position reset boundaries were not aligned" in note for note in notes)


def test_contribution_methodology_notes_report_residual_smoothing_and_alignment():
    notes = _contribution_methodology_notes(
        average_weight_sum_residual_bp=3,
        carino_invalid_domain_days=2,
        reset_alignment_counts={
            "portfolio_reset_without_position_reset_days": 1,
            "position_reset_without_portfolio_reset_days": 0,
        },
    )

    assert len(notes) == 3
    assert "maximum residual was 3 basis points" in notes[0]
    assert "Carino smoothing fell back" in notes[1]
    assert "grouped-return alignment remains under characterization" in notes[2]


def test_position_flow_balance_notes_distinguish_material_and_small_residuals():
    material_notes = _position_flow_balance_notes(
        {
            "position_flow_residual_days": 2,
            "position_flow_residual_max_bp": 100,
        }
    )
    small_notes = _position_flow_balance_notes(
        {
            "position_flow_residual_days": 1,
            "position_flow_residual_max_bp": 5,
        }
    )

    assert len(material_notes) == 1
    assert "materially non-flow-neutral scoped slice" in material_notes[0]
    assert len(small_notes) == 1
    assert "looks like a small non-flow-neutral scoped slice" in small_notes[0]
