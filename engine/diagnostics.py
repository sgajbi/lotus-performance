from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class PolicyOverrideCounts:
    applied_mv_count: int = 0
    applied_cf_count: int = 0


@dataclass
class OutlierDiagnostics:
    flagged_rows: int = 0


@dataclass
class OutlierSample:
    date: str
    raw_return: Any
    threshold: Any


@dataclass
class MethodologyShadowSample:
    """Captures methodology shadow signals for characterization without changing engine outputs."""

    date: str
    active_nip: int
    nip_rule_v1: int
    nip_rule_v2: int
    active_perf_reset: int
    candidate_canonical_perf_reset: int
    sod_reset_shadow: int
    account_reset_shadow: int
    previous_sign_zero: int
    initial_sign: int
    final_sign: int
    active_reset_reason_codes: list[str] = field(default_factory=list)
    candidate_canonical_reset_reason_codes: list[str] = field(default_factory=list)


@dataclass
class EngineDiagnosticSamples:
    outliers: list[OutlierSample] = field(default_factory=list)
    methodology_shadows: list[MethodologyShadowSample] = field(default_factory=list)


@dataclass
class EnginePolicyDiagnostics:
    overrides: PolicyOverrideCounts = field(default_factory=PolicyOverrideCounts)
    ignored_days_count: int = 0
    outliers: OutlierDiagnostics = field(default_factory=OutlierDiagnostics)


@dataclass
class EngineResetEvent:
    """Explains a day on which the engine reset cumulative compounding."""

    date: date
    reason: str
    impacted_rows: int


@dataclass
class EngineDiagnostics:
    """Typed engine diagnostics carried into public performance diagnostics."""

    nip_days: int = 0
    nip_rule_delta_days: int = 0
    reset_days: int = 0
    nctrl4_reset_days: int = 0
    nctrl4_exclusive_reset_days: int = 0
    account_reset_shadow_days: int = 0
    sod_reset_shadow_days: int = 0
    shadow_reset_overlap_days: int = 0
    shadow_only_candidate_reset_days: int = 0
    active_reset_with_shadow_days: int = 0
    candidate_canonical_reset_days: int = 0
    reset_delta_days: int = 0
    nip_days_since_last_reset: int = 0
    valid_days_since_last_reset: int = 0
    effective_period_start: date | None = None
    notes: list[str] = field(default_factory=list)
    resets: list[EngineResetEvent] = field(default_factory=list)
    policy: EnginePolicyDiagnostics = field(default_factory=EnginePolicyDiagnostics)
    samples: EngineDiagnosticSamples = field(default_factory=EngineDiagnosticSamples)
