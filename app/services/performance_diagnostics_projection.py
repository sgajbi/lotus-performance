from __future__ import annotations

from datetime import date
from typing import Any

from app.models.responses import ResetEvent
from core.envelope import Diagnostics, PolicyDiagnostics
from engine.diagnostics import EngineDiagnostics


def build_performance_diagnostics(diagnostics: EngineDiagnostics) -> Diagnostics:
    """Project engine diagnostics into the public performance diagnostics envelope."""
    return Diagnostics(
        nip_days=diagnostics.nip_days,
        nip_rule_delta_days=diagnostics.nip_rule_delta_days,
        reset_days=diagnostics.reset_days,
        nctrl4_reset_days=diagnostics.nctrl4_reset_days,
        nctrl4_exclusive_reset_days=diagnostics.nctrl4_exclusive_reset_days,
        account_reset_shadow_days=diagnostics.account_reset_shadow_days,
        sod_reset_shadow_days=diagnostics.sod_reset_shadow_days,
        shadow_reset_overlap_days=diagnostics.shadow_reset_overlap_days,
        shadow_only_candidate_reset_days=diagnostics.shadow_only_candidate_reset_days,
        active_reset_with_shadow_days=diagnostics.active_reset_with_shadow_days,
        candidate_canonical_reset_days=diagnostics.candidate_canonical_reset_days,
        reset_delta_days=diagnostics.reset_delta_days,
        nip_days_since_last_reset=diagnostics.nip_days_since_last_reset,
        valid_days_since_last_reset=diagnostics.valid_days_since_last_reset,
        effective_period_start=_required_effective_period_start(diagnostics),
        notes=list(diagnostics.notes),
        policy=_build_policy_diagnostics(diagnostics),
        samples=_build_diagnostic_samples(diagnostics),
    )


def build_reset_events(diagnostics: EngineDiagnostics) -> list[ResetEvent]:
    return [
        ResetEvent(date=event.date, reason=event.reason, impacted_rows=event.impacted_rows)
        for event in diagnostics.resets
    ]


def _required_effective_period_start(diagnostics: EngineDiagnostics) -> date:
    if diagnostics.effective_period_start is None:
        raise ValueError("Engine diagnostics must include effective_period_start for performance responses.")
    return diagnostics.effective_period_start


def _build_policy_diagnostics(diagnostics: EngineDiagnostics) -> PolicyDiagnostics:
    return PolicyDiagnostics(
        overrides={
            "applied_mv_count": diagnostics.policy.overrides.applied_mv_count,
            "applied_cf_count": diagnostics.policy.overrides.applied_cf_count,
        },
        ignored_days_count=diagnostics.policy.ignored_days_count,
        outliers={"flagged_rows": diagnostics.policy.outliers.flagged_rows},
    )


def _build_diagnostic_samples(diagnostics: EngineDiagnostics) -> dict[str, list[dict[str, Any]]]:
    return {
        "outliers": _build_outlier_samples(diagnostics),
        "methodology_shadows": _build_methodology_shadow_samples(diagnostics),
    }


def _build_outlier_samples(diagnostics: EngineDiagnostics) -> list[dict[str, Any]]:
    return [
        {
            "date": sample.date,
            "raw_return": sample.raw_return,
            "threshold": sample.threshold,
        }
        for sample in diagnostics.samples.outliers
    ]


def _build_methodology_shadow_samples(diagnostics: EngineDiagnostics) -> list[dict[str, Any]]:
    return [
        {
            "date": sample.date,
            "active_nip": sample.active_nip,
            "nip_rule_v1": sample.nip_rule_v1,
            "nip_rule_v2": sample.nip_rule_v2,
            "active_perf_reset": sample.active_perf_reset,
            "candidate_canonical_perf_reset": sample.candidate_canonical_perf_reset,
            "sod_reset_shadow": sample.sod_reset_shadow,
            "account_reset_shadow": sample.account_reset_shadow,
            "previous_sign_zero": sample.previous_sign_zero,
            "initial_sign": sample.initial_sign,
            "final_sign": sample.final_sign,
            "active_reset_reason_codes": list(sample.active_reset_reason_codes),
            "candidate_canonical_reset_reason_codes": list(sample.candidate_canonical_reset_reason_codes),
        }
        for sample in diagnostics.samples.methodology_shadows
    ]
