from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPORT_PATH = Path("artifacts/contribution-rollout-readiness/latest.json")


@dataclass
class ContributionRolloutDecision:
    outcome: str
    approved: bool
    reason: str
    hold_category: str
    secondary_hold_categories: list[str]
    recommended_next_action: str
    report_path: str
    recommendation: str
    material_periods: int
    promotion_ready_rate_bp: int
    blocked_periods: int
    blocker_reason_counts: dict[str, int]


def _collect_hold_categories(
    blocker_reason_counts: dict[str, int],
    *,
    blocked_periods: int,
    material_periods: int,
    promotion_ready_rate_bp: int,
    minimum_ready_rate_bp: int,
) -> list[str]:
    categories: list[str] = []
    if material_periods <= 0:
        return ["insufficient_evidence"]
    if blocker_reason_counts.get("weight_residual", 0) > 0 or blocker_reason_counts.get("flow_balance", 0) > 0:
        categories.append("economic_integrity")
    if (
        blocker_reason_counts.get("reset_alignment", 0) > 0
        or blocker_reason_counts.get("timeseries_reconciliation", 0) > 0
    ):
        categories.append("methodology_guardrail")
    if blocked_periods > 0 and not categories:
        categories.append("blocked_periods")
    if promotion_ready_rate_bp < minimum_ready_rate_bp and not categories and blocked_periods == 0:
        categories.append("below_threshold")
    if not categories:
        categories.append("none")
    return categories


def _recommended_next_action(hold_category: str, secondary_hold_categories: list[str]) -> str:
    if hold_category == "insufficient_evidence":
        return "Gather broader non-prod contribution responses before making a rollout decision."
    if hold_category == "economic_integrity":
        if "methodology_guardrail" in secondary_hold_categories:
            return (
                "Keep broader rollout off, treat non-flow-neutral slices as promotion fences, and review reset-alignment "
                "guardrails separately before widening rollout."
            )
        return "Keep broader rollout off and treat economic-integrity blockers as promotion fences for now."
    if hold_category == "methodology_guardrail":
        return "Keep rollout shadow-only for blocked slices and review reset-alignment or timeseries guardrails before widening rollout."
    if hold_category == "blocked_periods":
        return "Review blocked material periods individually and classify them into economic or methodology blocker families."
    if hold_category == "below_threshold":
        return "Keep controlled rollout narrow and gather more promotion-ready material periods before widening."
    return "Controlled rollout can proceed under the configured threshold."


def load_rollout_report(report_path: Path) -> dict:
    return json.loads(report_path.read_text(encoding="utf-8"))


def evaluate_contribution_rollout_decision(
    report: dict,
    *,
    minimum_ready_rate_bp: int = 8000,
) -> ContributionRolloutDecision:
    recommendation = str(report.get("recommendation", "UNKNOWN"))
    material_periods = int(report.get("material_periods", 0))
    promotion_ready_rate_bp = int(report.get("promotion_ready_rate_bp", 0))
    blocked_periods = int(report.get("blocked_periods", 0))
    blocker_reason_counts = {
        str(key): int(value) for key, value in dict(report.get("blocker_reason_counts", {})).items()
    }
    hold_categories = _collect_hold_categories(
        blocker_reason_counts,
        blocked_periods=blocked_periods,
        material_periods=material_periods,
        promotion_ready_rate_bp=promotion_ready_rate_bp,
        minimum_ready_rate_bp=minimum_ready_rate_bp,
    )
    primary_hold_category = hold_categories[0]
    secondary_hold_categories = hold_categories[1:] if len(hold_categories) > 1 else []

    if material_periods <= 0:
        return ContributionRolloutDecision(
            outcome="HOLD",
            approved=False,
            reason="No material-shadow periods were observed; there is not enough rollout evidence yet.",
            hold_category=primary_hold_category,
            secondary_hold_categories=secondary_hold_categories,
            recommended_next_action=_recommended_next_action(primary_hold_category, secondary_hold_categories),
            report_path=str(report.get("report_path", "")),
            recommendation=recommendation,
            material_periods=material_periods,
            promotion_ready_rate_bp=promotion_ready_rate_bp,
            blocked_periods=blocked_periods,
            blocker_reason_counts=blocker_reason_counts,
        )

    if blocker_reason_counts.get("weight_residual", 0) > 0 or blocker_reason_counts.get("flow_balance", 0) > 0:
        return ContributionRolloutDecision(
            outcome="HOLD",
            approved=False,
            reason="Economic-integrity blockers are still present in material periods.",
            hold_category=primary_hold_category,
            secondary_hold_categories=secondary_hold_categories,
            recommended_next_action=_recommended_next_action(primary_hold_category, secondary_hold_categories),
            report_path=str(report.get("report_path", "")),
            recommendation=recommendation,
            material_periods=material_periods,
            promotion_ready_rate_bp=promotion_ready_rate_bp,
            blocked_periods=blocked_periods,
            blocker_reason_counts=blocker_reason_counts,
        )

    if (
        blocker_reason_counts.get("reset_alignment", 0) > 0
        or blocker_reason_counts.get("timeseries_reconciliation", 0) > 0
    ):
        return ContributionRolloutDecision(
            outcome="HOLD",
            approved=False,
            reason="Methodology guardrail blockers are still present in material periods.",
            hold_category=primary_hold_category,
            secondary_hold_categories=secondary_hold_categories,
            recommended_next_action=_recommended_next_action(primary_hold_category, secondary_hold_categories),
            report_path=str(report.get("report_path", "")),
            recommendation=recommendation,
            material_periods=material_periods,
            promotion_ready_rate_bp=promotion_ready_rate_bp,
            blocked_periods=blocked_periods,
            blocker_reason_counts=blocker_reason_counts,
        )

    if blocked_periods > 0:
        return ContributionRolloutDecision(
            outcome="HOLD",
            approved=False,
            reason="Some material periods remain blocked by rollout guardrails.",
            hold_category=primary_hold_category,
            secondary_hold_categories=secondary_hold_categories,
            recommended_next_action=_recommended_next_action(primary_hold_category, secondary_hold_categories),
            report_path=str(report.get("report_path", "")),
            recommendation=recommendation,
            material_periods=material_periods,
            promotion_ready_rate_bp=promotion_ready_rate_bp,
            blocked_periods=blocked_periods,
            blocker_reason_counts=blocker_reason_counts,
        )

    if promotion_ready_rate_bp < minimum_ready_rate_bp:
        return ContributionRolloutDecision(
            outcome="HOLD",
            approved=False,
            reason=(
                "Promotion-ready share of material periods is below the configured rollout threshold "
                f"({promotion_ready_rate_bp} < {minimum_ready_rate_bp})."
            ),
            hold_category=primary_hold_category,
            secondary_hold_categories=secondary_hold_categories,
            recommended_next_action=_recommended_next_action(primary_hold_category, secondary_hold_categories),
            report_path=str(report.get("report_path", "")),
            recommendation=recommendation,
            material_periods=material_periods,
            promotion_ready_rate_bp=promotion_ready_rate_bp,
            blocked_periods=blocked_periods,
            blocker_reason_counts=blocker_reason_counts,
        )

    return ContributionRolloutDecision(
        outcome="READY",
        approved=True,
        reason="Material periods are clean enough to support controlled rollout under the configured threshold.",
        hold_category=primary_hold_category,
        secondary_hold_categories=secondary_hold_categories,
        recommended_next_action=_recommended_next_action(primary_hold_category, secondary_hold_categories),
        report_path=str(report.get("report_path", "")),
        recommendation=recommendation,
        material_periods=material_periods,
        promotion_ready_rate_bp=promotion_ready_rate_bp,
        blocked_periods=blocked_periods,
        blocker_reason_counts=blocker_reason_counts,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate a contribution rollout-readiness artifact against explicit rollout thresholds."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path to a contribution rollout-readiness report JSON.",
    )
    parser.add_argument(
        "--minimum-ready-rate-bp",
        type=int,
        default=8000,
        help="Minimum promotion-ready share of material periods required to return READY.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = load_rollout_report(args.report)
    report["report_path"] = str(args.report)
    decision = evaluate_contribution_rollout_decision(
        report,
        minimum_ready_rate_bp=args.minimum_ready_rate_bp,
    )
    print(json.dumps(decision.__dict__, indent=2))
    return 0 if decision.approved else 1


if __name__ == "__main__":
    raise SystemExit(main())
