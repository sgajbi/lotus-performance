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
    MethodologyShadowSample,
    OutlierDiagnostics,
    OutlierSample,
    PolicyOverrideCounts,
)


def test_build_performance_diagnostics_maps_engine_payload():
    diagnostics = EngineDiagnostics(
        nip_days=3,
        nip_rule_delta_days=1,
        reset_days=1,
        nctrl4_reset_days=1,
        nctrl4_exclusive_reset_days=1,
        account_reset_shadow_days=2,
        sod_reset_shadow_days=1,
        shadow_reset_overlap_days=1,
        shadow_only_candidate_reset_days=2,
        active_reset_with_shadow_days=1,
        candidate_canonical_reset_days=2,
        reset_delta_days=1,
        nip_days_since_last_reset=1,
        valid_days_since_last_reset=2,
        effective_period_start=date(2025, 1, 1),
        notes=["Applied overrides from the data_policy request."],
        policy=EnginePolicyDiagnostics(
            overrides=PolicyOverrideCounts(applied_mv_count=2, applied_cf_count=1),
            ignored_days_count=4,
            outliers=OutlierDiagnostics(flagged_rows=5),
        ),
        samples=EngineDiagnosticSamples(
            outliers=[OutlierSample(date="2025-01-10", raw_return=12.5, threshold=3.0)],
            methodology_shadows=[
                MethodologyShadowSample(
                    date="2025-01-02",
                    active_nip=0,
                    nip_rule_v1=0,
                    nip_rule_v2=1,
                    active_perf_reset=1,
                    candidate_canonical_perf_reset=1,
                    sod_reset_shadow=1,
                    account_reset_shadow=0,
                    previous_sign_zero=0,
                    initial_sign=1,
                    final_sign=1,
                    active_reset_reason_codes=["NCTRL_1"],
                    candidate_canonical_reset_reason_codes=["NCTRL_1", "SOD_RESET"],
                )
            ],
        ),
    )

    response_diagnostics = build_performance_diagnostics(diagnostics)

    assert response_diagnostics.nip_days == 3
    assert response_diagnostics.nip_rule_delta_days == 1
    assert response_diagnostics.reset_days == 1
    assert response_diagnostics.nctrl4_reset_days == 1
    assert response_diagnostics.nctrl4_exclusive_reset_days == 1
    assert response_diagnostics.account_reset_shadow_days == 2
    assert response_diagnostics.sod_reset_shadow_days == 1
    assert response_diagnostics.shadow_reset_overlap_days == 1
    assert response_diagnostics.shadow_only_candidate_reset_days == 2
    assert response_diagnostics.active_reset_with_shadow_days == 1
    assert response_diagnostics.candidate_canonical_reset_days == 2
    assert response_diagnostics.reset_delta_days == 1
    assert response_diagnostics.nip_days_since_last_reset == 1
    assert response_diagnostics.valid_days_since_last_reset == 2
    assert response_diagnostics.effective_period_start == date(2025, 1, 1)
    assert response_diagnostics.policy.overrides["applied_mv_count"] == 2
    assert response_diagnostics.policy.outliers["flagged_rows"] == 5
    assert response_diagnostics.samples["outliers"][0]["date"] == "2025-01-10"
    assert response_diagnostics.samples["methodology_shadows"][0]["sod_reset_shadow"] == 1
    assert response_diagnostics.samples["methodology_shadows"][0]["active_perf_reset"] == 1
    assert response_diagnostics.samples["methodology_shadows"][0]["candidate_canonical_perf_reset"] == 1


def test_build_reset_events_maps_engine_events():
    diagnostics = EngineDiagnostics(resets=[EngineResetEvent(date=date(2025, 1, 2), reason="NCTRL_1", impacted_rows=1)])

    reset_events = build_reset_events(diagnostics)

    assert len(reset_events) == 1
    assert reset_events[0].reason == "NCTRL_1"


def test_build_performance_diagnostics_requires_effective_period_start():
    with pytest.raises(ValueError, match="effective_period_start"):
        build_performance_diagnostics(EngineDiagnostics())
