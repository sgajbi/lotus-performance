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
class EngineDiagnosticSamples:
    outliers: list[OutlierSample] = field(default_factory=list)


@dataclass
class EnginePolicyDiagnostics:
    overrides: PolicyOverrideCounts = field(default_factory=PolicyOverrideCounts)
    ignored_days_count: int = 0
    outliers: OutlierDiagnostics = field(default_factory=OutlierDiagnostics)


@dataclass
class EngineResetEvent:
    date: date
    reason: str
    impacted_rows: int


@dataclass
class EngineDiagnostics:
    nip_days: int = 0
    reset_days: int = 0
    effective_period_start: date | None = None
    notes: list[str] = field(default_factory=list)
    resets: list[EngineResetEvent] = field(default_factory=list)
    policy: EnginePolicyDiagnostics = field(default_factory=EnginePolicyDiagnostics)
    samples: EngineDiagnosticSamples = field(default_factory=EngineDiagnosticSamples)
