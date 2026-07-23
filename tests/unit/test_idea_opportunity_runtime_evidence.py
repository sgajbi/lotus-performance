from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from app.evidence.idea_opportunity_runtime import (
    IDEA_BLOCKERS_CLEARED,
    IDEA_BLOCKERS_PRESERVED,
    MISSING_BENCHMARK_SCENARIO_ID,
    UNDERPERFORMANCE_SCENARIO_ID,
    copy_evidence,
    generate_idea_opportunity_runtime_evidence,
    validate_idea_opportunity_runtime_evidence,
)
from app.services.execution_registry import ExecutionRegistry


@pytest.mark.asyncio
async def test_generate_idea_opportunity_runtime_evidence_is_source_safe_and_bounded() -> None:
    evidence = await generate_idea_opportunity_runtime_evidence(
        generated_at_utc=datetime(2026, 5, 9, 8, 30, tzinfo=UTC),
    )

    validate_idea_opportunity_runtime_evidence(evidence)
    encoded = json.dumps(evidence, sort_keys=True)
    assert "PB_SG_GLOBAL_BAL_001" not in encoded
    assert "portfolio_returns" not in encoded
    assert "benchmark_returns" not in encoded
    assert evidence["portfolio_identity"]["raw_identifier_policy"] == "not_emitted"
    assert tuple(evidence["idea_blockers_cleared"]) == IDEA_BLOCKERS_CLEARED
    assert tuple(evidence["idea_blockers_preserved"]) == IDEA_BLOCKERS_PRESERVED
    assert evidence["unsupported_promotion_policy"]["supported_feature_promotion"] == "not_claimed"

    scenarios = {scenario["scenario_id"]: scenario for scenario in evidence["scenarios"]}
    underperformance = scenarios[UNDERPERFORMANCE_SCENARIO_ID]
    assert underperformance["readiness"]["supportability_state"] == "ready"
    assert underperformance["readiness"]["benchmark_context_state"] == "resolved"
    assert underperformance["readiness"]["benchmark_context"] == {
        "benchmark_id": "BMK_GLOBAL_60_40_USD",
        "return_source": "calculated",
    }
    assert underperformance["metric_summary"]["active_return_posture"] == "underperforming"
    assert underperformance["runtime_digests"]["source_payload_visibility"] == "digests_and_bounded_summaries_only"

    missing_benchmark = scenarios[MISSING_BENCHMARK_SCENARIO_ID]
    assert missing_benchmark["readiness"]["supportability_state"] == "ready"
    assert missing_benchmark["readiness"]["freshness"] == "current"
    assert missing_benchmark["readiness"]["benchmark_context_state"] == "missing"
    assert missing_benchmark["readiness"]["reason_codes"] == ["BENCHMARK_CONTEXT_MISSING"]
    assert missing_benchmark["metric_summary"]["active_return_posture"] == "not_applicable"


@pytest.mark.asyncio
async def test_validate_idea_opportunity_runtime_evidence_rejects_raw_client_identity() -> None:
    evidence = await generate_idea_opportunity_runtime_evidence()
    invalid = copy_evidence(evidence)
    invalid["portfolio_identity"]["raw_identifier"] = "PB_SG_GLOBAL_BAL_001"

    with pytest.raises(ValueError, match="source-safe evidence"):
        validate_idea_opportunity_runtime_evidence(invalid)


@pytest.mark.asyncio
async def test_validate_idea_opportunity_runtime_evidence_rejects_raw_series_payloads() -> None:
    evidence = await generate_idea_opportunity_runtime_evidence()
    invalid = copy_evidence(evidence)
    invalid["scenarios"][0]["series"] = {"portfolio_returns": [{"date": "2026-05-04", "return_value": "0.01"}]}

    with pytest.raises(ValueError, match="raw return-series"):
        validate_idea_opportunity_runtime_evidence(invalid)


@pytest.mark.asyncio
async def test_validate_idea_opportunity_runtime_evidence_rejects_blocker_overclaims() -> None:
    evidence = await generate_idea_opportunity_runtime_evidence()

    missing_preserved = copy_evidence(evidence)
    missing_preserved["idea_blockers_preserved"] = [
        blocker
        for blocker in missing_preserved["idea_blockers_preserved"]
        if blocker != "gateway_runtime_consumption_proof_missing"
    ]
    with pytest.raises(ValueError, match="preserve every non-Performance Idea blocker"):
        validate_idea_opportunity_runtime_evidence(missing_preserved)

    moved_to_cleared = copy_evidence(evidence)
    moved_to_cleared["idea_blockers_cleared"].append("gateway_runtime_consumption_proof_missing")
    moved_to_cleared["idea_blockers_preserved"] = [
        blocker
        for blocker in moved_to_cleared["idea_blockers_preserved"]
        if blocker != "gateway_runtime_consumption_proof_missing"
    ]
    with pytest.raises(ValueError, match="clear only Performance-owned Idea blockers"):
        validate_idea_opportunity_runtime_evidence(moved_to_cleared)


@pytest.mark.asyncio
async def test_generate_idea_opportunity_runtime_evidence_rejects_identity_overrides() -> None:
    with pytest.raises(ValueError, match="canonical fixed source-data scenario"):
        await generate_idea_opportunity_runtime_evidence(portfolio_id="PB_SG_OTHER_001")
    with pytest.raises(ValueError, match="canonical fixed source-data scenario"):
        await generate_idea_opportunity_runtime_evidence(benchmark_id="BMK_OTHER")
    with pytest.raises(ValueError, match="canonical fixed source-data scenario"):
        await generate_idea_opportunity_runtime_evidence(as_of_date=date(2026, 5, 9))


@pytest.mark.asyncio
async def test_validate_idea_opportunity_runtime_evidence_rejects_degraded_missing_benchmark() -> None:
    evidence = await generate_idea_opportunity_runtime_evidence()

    degraded_supportability = copy_evidence(evidence)
    degraded_supportability["scenarios"][1]["readiness"]["supportability_state"] = "degraded"
    with pytest.raises(ValueError, match="missing-benchmark scenario must be source-ready"):
        validate_idea_opportunity_runtime_evidence(degraded_supportability)

    partial_coverage = copy_evidence(evidence)
    partial_coverage["scenarios"][1]["readiness"]["coverage"]["missing_points"] = 1
    with pytest.raises(ValueError, match="complete portfolio coverage"):
        validate_idea_opportunity_runtime_evidence(partial_coverage)


@pytest.mark.asyncio
async def test_generate_idea_opportunity_runtime_evidence_can_write_valid_artifact(tmp_path: Path) -> None:
    evidence = await generate_idea_opportunity_runtime_evidence(
        generated_at_utc=datetime(2026, 5, 9, 8, 30, tzinfo=UTC),
    )
    output_path = tmp_path / "latest.json"
    output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    validate_idea_opportunity_runtime_evidence(loaded)


@pytest.mark.asyncio
async def test_generate_idea_opportunity_runtime_evidence_preserves_execution_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    monkeypatch.setattr("app.evidence.idea_opportunity_runtime.returns_series_service.execution_registry", store)

    evidence = await generate_idea_opportunity_runtime_evidence(
        generated_at_utc=datetime(2026, 5, 9, 8, 30, tzinfo=UTC),
    )

    for scenario in evidence["scenarios"]:
        receipt = scenario["execution_receipt"]
        execution = store.get_execution(UUID(receipt["calculation_id"]))
        assert execution is not None
        assert execution.input_fingerprint == receipt["input_fingerprint"]
        assert execution.calculation_hash == receipt["calculation_hash"]
