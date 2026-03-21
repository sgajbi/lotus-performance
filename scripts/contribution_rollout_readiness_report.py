from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_PATH = Path("artifacts/contribution-rollout-readiness/latest.json")


@dataclass
class PeriodMethodologyRecord:
    source_file: str
    period_name: str
    status: str
    max_shadow_delta_bp: int
    is_material_shadow: bool
    is_cutover_candidate: bool
    is_promoted: bool
    blocker_reason_codes: list[str]


@dataclass
class ContributionRolloutReadinessReport:
    input_files: list[str]
    total_periods: int
    material_periods: int
    promotion_ready_periods: int
    promoted_periods: int
    blocked_periods: int
    blocked_economic_periods: int
    blocked_methodology_periods: int
    promotion_ready_rate_bp: int
    max_shadow_delta_bp: int
    status_counts: dict[str, int]
    blocker_reason_counts: dict[str, int]
    blocker_category_counts: dict[str, int]
    recommendation: str
    periods: list[dict[str, Any]]


def _load_response_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_period_records(path: Path) -> list[PeriodMethodologyRecord]:
    payload = _load_response_payload(path)
    records: list[PeriodMethodologyRecord] = []
    results_by_period = payload.get("results_by_period", {})
    for period_name, period_payload in results_by_period.items():
        methodology_status = period_payload.get("average_weight_methodology_status")
        if not methodology_status:
            continue
        records.append(
            PeriodMethodologyRecord(
                source_file=str(path),
                period_name=period_name,
                status=str(methodology_status.get("status", "UNDER_REVIEW")),
                max_shadow_delta_bp=int(methodology_status.get("max_shadow_delta_bp", 0)),
                is_material_shadow=bool(methodology_status.get("is_material_shadow", False)),
                is_cutover_candidate=bool(methodology_status.get("is_cutover_candidate", False)),
                is_promoted=bool(methodology_status.get("is_promoted", False)),
                blocker_reason_codes=sorted(str(code) for code in methodology_status.get("blocker_reason_codes", [])),
            )
        )
    return records


def _calculate_promotion_ready_rate_bp(*, ready_periods: int, material_periods: int) -> int:
    if material_periods <= 0:
        return 0
    return round((ready_periods / material_periods) * 10000)


def _recommendation_for(records: list[PeriodMethodologyRecord]) -> str:
    material_records = [record for record in records if record.is_material_shadow]
    if not material_records:
        return "NO_MATERIAL_SHADOW_TRAFFIC"

    blocker_codes = {code for record in material_records for code in record.blocker_reason_codes}
    ready_count = sum(1 for record in material_records if record.is_cutover_candidate)
    material_count = len(material_records)
    ready_rate_bp = _calculate_promotion_ready_rate_bp(ready_periods=ready_count, material_periods=material_count)

    if "weight_residual" in blocker_codes or "flow_balance" in blocker_codes:
        return "HOLD_BLOCKERS_PRESENT"
    if ready_rate_bp == 10000:
        return "READY_FOR_CONTROLLED_ROLLOUT"
    if ready_rate_bp > 0:
        return "MIXED_READYNESS_KEEP_CANDIDATE_ONLY"
    return "KEEP_SHADOW_ONLY_GATHER_MORE_EVIDENCE"


def _blocked_period_has_any_reason(record: PeriodMethodologyRecord, reasons: set[str]) -> bool:
    return any(code in reasons for code in record.blocker_reason_codes)


def build_contribution_rollout_readiness_report(paths: list[Path]) -> ContributionRolloutReadinessReport:
    records = [record for path in paths for record in _extract_period_records(path)]
    status_counts = Counter(record.status for record in records)
    blocker_reason_counts = Counter(
        code for record in records for code in record.blocker_reason_codes
    )
    economic_reason_codes = {"weight_residual", "flow_balance"}
    methodology_reason_codes = {"reset_alignment", "timeseries_reconciliation"}
    material_periods = sum(1 for record in records if record.is_material_shadow)
    promotion_ready_periods = sum(1 for record in records if record.is_cutover_candidate)
    promoted_periods = sum(1 for record in records if record.is_promoted)
    blocked_periods = sum(1 for record in records if record.status == "BLOCKED")
    blocked_economic_periods = sum(
        1 for record in records if record.status == "BLOCKED" and _blocked_period_has_any_reason(record, economic_reason_codes)
    )
    blocked_methodology_periods = sum(
        1 for record in records if record.status == "BLOCKED" and _blocked_period_has_any_reason(record, methodology_reason_codes)
    )
    promotion_ready_rate_bp = _calculate_promotion_ready_rate_bp(
        ready_periods=promotion_ready_periods,
        material_periods=material_periods,
    )
    max_shadow_delta_bp = max((record.max_shadow_delta_bp for record in records), default=0)

    return ContributionRolloutReadinessReport(
        input_files=[str(path) for path in paths],
        total_periods=len(records),
        material_periods=material_periods,
        promotion_ready_periods=promotion_ready_periods,
        promoted_periods=promoted_periods,
        blocked_periods=blocked_periods,
        blocked_economic_periods=blocked_economic_periods,
        blocked_methodology_periods=blocked_methodology_periods,
        promotion_ready_rate_bp=promotion_ready_rate_bp,
        max_shadow_delta_bp=max_shadow_delta_bp,
        status_counts=dict(status_counts),
        blocker_reason_counts=dict(blocker_reason_counts),
        blocker_category_counts={
            "economic_integrity": blocked_economic_periods,
            "methodology_guardrail": blocked_methodology_periods,
        },
        recommendation=_recommendation_for(records),
        periods=[asdict(record) for record in records],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate contribution rollout-readiness evidence from saved contribution response payloads."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Contribution response JSON files to summarize.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output path for the aggregated readiness report JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_contribution_rollout_readiness_report(args.inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(asdict(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
