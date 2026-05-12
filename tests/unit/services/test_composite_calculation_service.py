from __future__ import annotations

from datetime import date

import pytest

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact
from app.services.composite_calculation_service import (
    CompositeDefinitionNotFoundError,
    calculate_composite_twr_from_persisted_facts,
)
from app.services.composite_metadata_store import CompositeMetadataStore


def _store(tmp_path) -> CompositeMetadataStore:
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'composite_metadata.db'}")
    store.create_schema()
    return store


def _definition() -> CompositeDefinition:
    return CompositeDefinition.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "display_name": "Private Banking Global Balanced USD Composite",
            "strategy_code": "GLOBAL_BALANCED",
            "reporting_currency": "USD",
            "inception_date": "2026-01-01",
            "source_authority": {
                "definition_owner": "lotus-manage",
                "membership_owner": "lotus-manage",
                "member_return_owner": "lotus-performance",
                "asset_owner": "lotus-core",
                "benchmark_owner": "lotus-core",
                "policy_version": "composite-source-authority.v1",
            },
        }
    )


def _fact(portfolio_id: str, return_value: str, beginning_market_value: str) -> CompositeMemberReturnFact:
    return CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": portfolio_id,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": return_value,
            "beginning_market_value": beginning_market_value,
            "ending_market_value": "1012500.00",
            "reporting_currency": "USD",
            "calculation_id": f"calc-{portfolio_id}",
            "source_snapshot_id": f"snapshot-{portfolio_id}",
            "source_fingerprint": f"sha256:{portfolio_id}",
        }
    )


def test_calculate_composite_twr_from_persisted_facts_requires_definition(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(CompositeDefinitionNotFoundError):
        calculate_composite_twr_from_persisted_facts(
            composite_id="PB_GLOBAL_BALANCED_USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            store=store,
        )


def test_calculate_composite_twr_from_persisted_facts_reads_store(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    store.upsert_member_return_fact(_fact("P1", "0.0100", "100.00"))
    store.upsert_member_return_fact(_fact("P2", "0.0300", "300.00"))

    result = calculate_composite_twr_from_persisted_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )

    assert result.status == "READY"
    assert str(result.cumulative_return) == "0.025000000000"
