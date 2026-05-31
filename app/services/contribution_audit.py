from __future__ import annotations

from dataclasses import dataclass

from app.services.contribution_methodology import (
    _calculate_promotion_ready_rate_bp,
    _classify_average_weight_shadow_period,
)
from core.envelope import Diagnostics


@dataclass
class AverageWeightShadowAuditState:
    """Tracks reset-aware average-weight rollout evidence across contribution periods."""

    delta_positions: int = 0
    delta_max_bp: int = 0
    delta_sum_bp: int = 0
    noise_periods: int = 0
    warning_periods: int = 0
    material_periods: int = 0
    cutover_candidate_periods: int = 0
    promoted_periods: int = 0
    blocked_periods: int = 0
    blocked_by_weight_residual_periods: int = 0
    blocked_by_flow_balance_periods: int = 0
    blocked_by_reset_alignment_periods: int = 0
    blocked_by_timeseries_delta_periods: int = 0
    timeseries_total_delta_periods: int = 0

    @property
    def promotion_ready_rate_bp(self) -> int:
        return _calculate_promotion_ready_rate_bp(
            ready_periods=self.cutover_candidate_periods,
            material_periods=self.material_periods,
        )

    def record_shadow_observation(
        self,
        *,
        delta_positions: int,
        max_shadow_delta_bp: int,
        sum_shadow_delta_bp: int,
    ) -> None:
        self.delta_positions += delta_positions
        self.delta_max_bp = max(self.delta_max_bp, max_shadow_delta_bp)
        self.delta_sum_bp += sum_shadow_delta_bp

        shadow_period_bucket = _classify_average_weight_shadow_period(max_shadow_delta_bp)
        if shadow_period_bucket == "noise":
            self.noise_periods += 1
        elif shadow_period_bucket == "warning":
            self.warning_periods += 1
        elif shadow_period_bucket == "material":
            self.material_periods += 1

    def record_timeseries_total_delta(self) -> None:
        self.timeseries_total_delta_periods += 1

    def record_cutover_assessment(
        self,
        *,
        is_cutover_candidate: bool,
        blocker_reason_codes: set[str],
        is_promoted: bool = False,
    ) -> set[str]:
        """Records period rollout posture and returns blockers that should be emitted for the period."""
        if is_promoted:
            self.promoted_periods += 1

        if is_cutover_candidate:
            self.cutover_candidate_periods += 1
            return set()

        effective_blockers = set(blocker_reason_codes)
        if effective_blockers:
            self.blocked_periods += 1
        if "weight_residual" in effective_blockers:
            self.blocked_by_weight_residual_periods += 1
        if "flow_balance" in effective_blockers:
            self.blocked_by_flow_balance_periods += 1
        if "reset_alignment" in effective_blockers:
            self.blocked_by_reset_alignment_periods += 1
        if "timeseries_reconciliation" in effective_blockers:
            self.blocked_by_timeseries_delta_periods += 1
        return effective_blockers

    def append_diagnostic_notes(
        self,
        diagnostics: Diagnostics,
        *,
        average_weight_sum_residual_bp: int,
        carino_invalid_domain_days: int,
        reset_alignment_counts: dict[str, int],
        position_flow_balance_counts: dict[str, int],
    ) -> None:
        if self.delta_max_bp >= 500:
            diagnostics.notes.append(
                "Reset-aware average-weight shadow differs from the active mean-weight output for "
                f"{self.delta_positions} position-period rows."
            )
            diagnostics.notes.append(
                "Reset-aware average-weight shadow differs materially from the active average-weight "
                f"output, with a maximum delta of {self.delta_max_bp} basis points."
            )
        elif self.delta_positions > 0:
            diagnostics.notes.append(
                "Reset-aware average-weight shadow differs from the active mean-weight output for "
                f"{self.delta_positions} position-period rows. The maximum delta was "
                f"{self.delta_max_bp} basis points, which is still under characterization."
            )
        if self.cutover_candidate_periods > 0:
            diagnostics.notes.append(
                "Some periods show material reset-aware average-weight pressure while the surrounding "
                "bookkeeping remains clean. Those periods are strong candidates for a future denominator "
                f"cutover study ({self.cutover_candidate_periods} periods)."
            )
        if self.material_periods > 0:
            diagnostics.notes.append(
                "Reset-aware average-weight rollout readiness is currently "
                f"{self.promotion_ready_rate_bp} basis points of material-shadow periods "
                f"({self.cutover_candidate_periods} of {self.material_periods})."
            )
        if self.promoted_periods > 0:
            diagnostics.notes.append(
                "Reset-aware average-weight promotion was applied for "
                f"{self.promoted_periods} periods under the controlled rollout mode."
            )
        if self.blocked_periods > 0:
            diagnostics.notes.append(
                "Some material reset-aware average-weight periods remained shadow-only because one or "
                f"more rollout guardrails were not yet clean ({self.blocked_periods} periods)."
            )
        if self.blocked_by_weight_residual_periods > 0:
            diagnostics.notes.append(
                "Some material reset-aware average-weight periods were kept shadow-only because emitted "
                "position weights did not sum cleanly to 100%."
            )
        if self.blocked_by_flow_balance_periods > 0:
            diagnostics.notes.append(
                "Some material reset-aware average-weight periods were kept shadow-only because "
                "position-level stock and cash legs did not cancel cleanly."
            )
        if self.blocked_by_reset_alignment_periods > 0:
            diagnostics.notes.append(
                "Some material reset-aware average-weight periods were kept shadow-only because "
                "portfolio and position reset boundaries were not aligned."
            )
        if self.blocked_by_timeseries_delta_periods > 0:
            diagnostics.notes.append(
                "Some material reset-aware average-weight periods were kept shadow-only because emitted "
                "daily contribution series still drifted from the residual-adjusted period total."
            )
        if average_weight_sum_residual_bp > 1:
            diagnostics.notes.append(
                "Emitted position average weights do not sum to 100% exactly; the maximum residual was "
                f"{average_weight_sum_residual_bp} basis points."
            )
        if carino_invalid_domain_days > 0:
            diagnostics.notes.append(
                "Carino smoothing fell back to raw daily contribution arithmetic on "
                f"{carino_invalid_domain_days} portfolio days because the linked gross return factor "
                "left the valid logarithmic domain."
            )
        if (
            reset_alignment_counts["portfolio_reset_without_position_reset_days"] > 0
            or reset_alignment_counts["position_reset_without_portfolio_reset_days"] > 0
        ):
            diagnostics.notes.append(
                "Portfolio and position reset boundaries differ on some contribution dates; "
                "grouped-return alignment remains under characterization."
            )
        if position_flow_balance_counts["position_flow_residual_max_bp"] > 10:
            diagnostics.notes.append(
                "Summed position-level cash flows show a materially non-flow-neutral scoped slice on "
                f"{position_flow_balance_counts['position_flow_residual_days']} dates. This means the visible "
                "position set is not carrying both offsetting legs inside the current scope, so contribution "
                "is being explained on a partial flow story rather than a fully self-cancelling internal book. "
                f"The maximum residual was {position_flow_balance_counts['position_flow_residual_max_bp']} basis "
                "points of portfolio capital."
            )
        elif position_flow_balance_counts["position_flow_residual_days"] > 0:
            diagnostics.notes.append(
                "Summed position-level cash flows did not net to zero on "
                f"{position_flow_balance_counts['position_flow_residual_days']} dates. This looks like a small "
                "non-flow-neutral scoped slice rather than a material flow imbalance, but it should still be "
                f"reviewed. The maximum residual was {position_flow_balance_counts['position_flow_residual_max_bp']} "
                "basis points of portfolio capital."
            )
        if self.timeseries_total_delta_periods > 0:
            diagnostics.notes.append(
                "Some emitted daily contribution series remain raw path outputs and do not sum to the "
                "residual-adjusted period total for reset-heavy slices."
            )

    def to_audit_counts(
        self,
        *,
        average_weight_sum_residual_bp: int,
        carino_invalid_domain_days: int,
    ) -> dict[str, int]:
        return {
            "average_weight_shadow_delta_positions": self.delta_positions,
            "average_weight_shadow_delta_max_bp": self.delta_max_bp,
            "average_weight_shadow_delta_sum_bp": self.delta_sum_bp,
            "average_weight_shadow_noise_periods": self.noise_periods,
            "average_weight_shadow_warning_periods": self.warning_periods,
            "average_weight_shadow_material_periods": self.material_periods,
            "average_weight_shadow_cutover_candidate_periods": self.cutover_candidate_periods,
            "average_weight_shadow_promotion_ready_rate_bp": self.promotion_ready_rate_bp,
            "average_weight_shadow_promoted_periods": self.promoted_periods,
            "average_weight_shadow_blocked_periods": self.blocked_periods,
            "average_weight_shadow_blocked_by_weight_residual_periods": self.blocked_by_weight_residual_periods,
            "average_weight_shadow_blocked_by_flow_balance_periods": self.blocked_by_flow_balance_periods,
            "average_weight_shadow_blocked_by_reset_alignment_periods": self.blocked_by_reset_alignment_periods,
            "average_weight_shadow_blocked_by_timeseries_delta_periods": self.blocked_by_timeseries_delta_periods,
            "average_weight_sum_residual_bp": average_weight_sum_residual_bp,
            "carino_invalid_domain_days": carino_invalid_domain_days,
            "timeseries_total_delta_periods": self.timeseries_total_delta_periods,
        }
