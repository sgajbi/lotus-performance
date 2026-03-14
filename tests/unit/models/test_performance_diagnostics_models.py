from datetime import date

import pytest

from app.models.performance_diagnostics import (
    build_performance_diagnostics,
    build_reset_events,
)
from engine.diagnostics import (
    EngineDiagnostics,
    EngineDiagnosticSamples,
    EnginePolicyDiagnostics,
    EngineResetEvent,
    OutlierDiagnostics,
    OutlierSample,
    PolicyOverrideCounts,
)


def test_build_performance_diagnostics_maps_engine_payload():
    diagnostics = EngineDiagnostics(
        nip_days=3,
        reset_days=1,
        effective_period_start=date(2025, 1, 1),
        notes=["Applied overrides from the data_policy request."],
        policy=EnginePolicyDiagnostics(
            overrides=PolicyOverrideCounts(applied_mv_count=2, applied_cf_count=1),
            ignored_days_count=4,
            outliers=OutlierDiagnostics(flagged_rows=5),
        ),
        samples=EngineDiagnosticSamples(
            outliers=[OutlierSample(date="2025-01-10", raw_return=12.5, threshold=3.0)]
        ),
    )

    response_diagnostics = build_performance_diagnostics(diagnostics)

    assert response_diagnostics.nip_days == 3
    assert response_diagnostics.reset_days == 1
    assert response_diagnostics.effective_period_start == date(2025, 1, 1)
    assert response_diagnostics.policy.overrides["applied_mv_count"] == 2
    assert response_diagnostics.policy.outliers["flagged_rows"] == 5
    assert response_diagnostics.samples["outliers"][0]["date"] == "2025-01-10"


def test_build_reset_events_maps_engine_events():
    diagnostics = EngineDiagnostics(
        resets=[EngineResetEvent(date=date(2025, 1, 2), reason="NCTRL_1", impacted_rows=1)]
    )

    reset_events = build_reset_events(diagnostics)

    assert len(reset_events) == 1
    assert reset_events[0].reason == "NCTRL_1"


def test_build_performance_diagnostics_requires_effective_period_start():
    with pytest.raises(ValueError, match="effective_period_start"):
        build_performance_diagnostics(EngineDiagnostics())
