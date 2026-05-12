from __future__ import annotations

from datetime import date

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact, CompositeMembership
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


def test_composite_metadata_store_round_trips_definition_membership_and_fact(tmp_path):
    store = _store(tmp_path)
    definition = _definition()
    membership = CompositeMembership.model_validate(
        {
            "composite_id": definition.composite_id,
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "effective_from": "2026-01-01",
            "source_snapshot_id": "lotus-manage-membership-snapshot-1",
        }
    )
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": definition.composite_id,
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0125",
            "beginning_market_value": "1000000.00",
            "ending_market_value": "1012500.00",
            "reporting_currency": "USD",
            "calculation_id": "7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce",
            "source_snapshot_id": "portfolio-twr-snapshot-1",
        }
    )

    store.upsert_definition(definition)
    store.upsert_membership(membership)
    store.upsert_member_return_fact(fact)

    stored_definition = store.get_definition(definition.composite_id)
    memberships = store.list_memberships(definition.composite_id)
    facts = store.list_member_return_facts(
        composite_id=definition.composite_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    counts = store.count_records()

    assert stored_definition == definition
    assert memberships == [membership]
    assert facts == [fact]
    assert counts.definitions == 1
    assert counts.memberships == 1
    assert counts.member_return_facts == 1


def test_composite_metadata_store_upserts_member_return_facts_by_composite_portfolio_period(tmp_path):
    store = _store(tmp_path)
    first_fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "1000000.00",
            "ending_market_value": "1010000.00",
            "reporting_currency": "USD",
            "calculation_id": "initial-calculation",
            "source_snapshot_id": "initial-snapshot",
        }
    )
    restated_fact = CompositeMemberReturnFact.model_validate(
        first_fact.model_dump(mode="json")
        | {
            "return_value": "0.0125",
            "ending_market_value": "1012500.00",
            "calculation_id": "restated-calculation",
            "source_snapshot_id": "restated-snapshot",
        }
    )

    store.upsert_member_return_fact(first_fact)
    store.upsert_member_return_fact(restated_fact)

    facts = store.list_member_return_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )

    assert facts == [restated_fact]
    assert store.count_records().member_return_facts == 1
