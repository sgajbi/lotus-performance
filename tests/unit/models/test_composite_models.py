from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.composites import (
    CompositeDefinition,
    CompositeMemberReturnFact,
    CompositeMembership,
)


def _source_authority() -> dict:
    return {
        "definition_owner": "lotus-manage",
        "membership_owner": "lotus-manage",
        "member_return_owner": "lotus-performance",
        "asset_owner": "lotus-core",
        "benchmark_owner": "lotus-core",
        "policy_version": "composite-source-authority.v1",
    }


def test_composite_definition_requires_valid_lifecycle_window():
    payload = {
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "display_name": "Private Banking Global Balanced USD Composite",
        "strategy_code": "GLOBAL_BALANCED",
        "reporting_currency": "USD",
        "inception_date": "2026-01-01",
        "termination_date": "2025-12-31",
        "source_authority": _source_authority(),
    }

    with pytest.raises(ValidationError, match="termination_date cannot be before inception_date"):
        CompositeDefinition.model_validate(payload)


def test_membership_requires_reason_for_non_included_status():
    payload = {
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "effective_from": "2026-01-01",
        "status": "EXCLUDED",
        "source_snapshot_id": "membership-snapshot-1",
    }

    with pytest.raises(ValidationError, match="status_reason is required"):
        CompositeMembership.model_validate(payload)


def test_membership_rejects_reversed_effective_dates():
    payload = {
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "effective_from": "2026-02-01",
        "effective_to": "2026-01-31",
        "status": "INCLUDED",
        "source_snapshot_id": "membership-snapshot-1",
    }

    with pytest.raises(ValidationError, match="effective_to cannot be before effective_from"):
        CompositeMembership.model_validate(payload)


def test_member_return_fact_requires_reason_codes_for_degraded_status():
    payload = {
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "return_value": "0.0125",
        "beginning_market_value": "1000000.00",
        "ending_market_value": "1012500.00",
        "reporting_currency": "USD",
        "calculation_id": "7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce",
        "source_snapshot_id": "portfolio-twr-snapshot-1",
        "source_fingerprint": "sha256:portfolio-twr-snapshot-1",
        "status": "DEGRADED",
    }

    with pytest.raises(ValidationError, match="reason_codes are required"):
        CompositeMemberReturnFact.model_validate(payload)


def test_member_return_fact_rejects_negative_assets():
    payload = {
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "return_value": "0.0125",
        "beginning_market_value": "-1000000.00",
        "ending_market_value": "1012500.00",
        "reporting_currency": "USD",
        "calculation_id": "7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce",
        "source_snapshot_id": "portfolio-twr-snapshot-1",
        "source_fingerprint": "sha256:portfolio-twr-snapshot-1",
    }

    with pytest.raises(ValidationError):
        CompositeMemberReturnFact.model_validate(payload)


def test_member_return_fact_accepts_ready_persisted_fact():
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0125",
            "beginning_market_value": "1000000.00",
            "ending_market_value": "1012500.00",
            "reporting_currency": "USD",
            "calculation_id": "7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce",
            "source_snapshot_id": "portfolio-twr-snapshot-1",
            "source_fingerprint": "sha256:portfolio-twr-snapshot-1",
        }
    )

    assert fact.status.value == "READY"
    assert str(fact.return_value) == "0.0125"
