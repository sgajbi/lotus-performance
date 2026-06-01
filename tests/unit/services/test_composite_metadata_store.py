from __future__ import annotations

from datetime import date

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact, CompositeMembership
from app.services.composite_metadata_store import (
    INVALID_COMPOSITE_REASON_CODES_PAYLOAD,
    CompositeDefinitionModel,
    CompositeMemberReturnFactModel,
    CompositeMetadataStore,
)


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
            "source_fingerprint": "sha256:portfolio-twr-snapshot-1",
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
            "source_fingerprint": "sha256:initial-snapshot",
        }
    )
    restated_fact = CompositeMemberReturnFact.model_validate(
        first_fact.model_dump(mode="json")
        | {
            "return_value": "0.0125",
            "ending_market_value": "1012500.00",
            "calculation_id": "restated-calculation",
            "source_snapshot_id": "restated-snapshot",
            "source_fingerprint": "sha256:restated-snapshot",
            "restatement_version": "v2",
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


def test_composite_metadata_store_bounds_malformed_definition_source_authority(tmp_path, caplog):
    store = _store(tmp_path)
    definition = _definition()
    store.upsert_definition(definition)
    with store._session() as session:
        row = session.get(CompositeDefinitionModel, definition.composite_id)
        assert row is not None
        row.source_authority_json = "{not-json"

    with caplog.at_level("WARNING", logger="app.services.composite_metadata_store"):
        stored_definition = store.get_definition(definition.composite_id)

    assert stored_definition is None
    assert f"row={definition.composite_id}" in caplog.text


def test_composite_metadata_store_bounds_malformed_member_return_reason_codes(tmp_path, caplog):
    store = _store(tmp_path)
    fact = CompositeMemberReturnFact.model_validate(
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
            "source_fingerprint": "sha256:initial-snapshot",
            "status": "DEGRADED",
            "reason_codes": ["missing_final_valuation"],
        }
    )
    store.upsert_member_return_fact(fact)
    with store._session() as session:
        row = session.get(
            CompositeMemberReturnFactModel,
            "PB_GLOBAL_BALANCED_USD|PB_SG_GLOBAL_BAL_001|2026-01-01|2026-01-31",
        )
        assert row is not None
        row.reason_codes_json = "{not-json"

    with caplog.at_level("WARNING", logger="app.services.composite_metadata_store"):
        facts = store.list_member_return_facts(
            composite_id="PB_GLOBAL_BALANCED_USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

    assert len(facts) == 1
    assert facts[0].reason_codes == [INVALID_COMPOSITE_REASON_CODES_PAYLOAD]
    assert "row=PB_GLOBAL_BALANCED_USD|PB_SG_GLOBAL_BAL_001|2026-01-01|2026-01-31" in caplog.text
