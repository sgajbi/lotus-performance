from __future__ import annotations

from app.models.responses import ResetEvent
from core.envelope import Diagnostics, PolicyDiagnostics
from engine.diagnostics import EngineDiagnostics


def build_performance_diagnostics(diagnostics: EngineDiagnostics) -> Diagnostics:
    if diagnostics.effective_period_start is None:
        raise ValueError("Engine diagnostics must include effective_period_start for performance responses.")
    return Diagnostics(
        nip_days=diagnostics.nip_days,
        reset_days=diagnostics.reset_days,
        effective_period_start=diagnostics.effective_period_start,
        notes=list(diagnostics.notes),
        policy=PolicyDiagnostics(
            overrides={
                "applied_mv_count": diagnostics.policy.overrides.applied_mv_count,
                "applied_cf_count": diagnostics.policy.overrides.applied_cf_count,
            },
            ignored_days_count=diagnostics.policy.ignored_days_count,
            outliers={"flagged_rows": diagnostics.policy.outliers.flagged_rows},
        ),
        samples={
            "outliers": [
                {
                    "date": sample.date,
                    "raw_return": sample.raw_return,
                    "threshold": sample.threshold,
                }
                for sample in diagnostics.samples.outliers
            ]
        },
    )


def build_reset_events(diagnostics: EngineDiagnostics) -> list[ResetEvent]:
    return [
        ResetEvent(date=event.date, reason=event.reason, impacted_rows=event.impacted_rows)
        for event in diagnostics.resets
    ]
