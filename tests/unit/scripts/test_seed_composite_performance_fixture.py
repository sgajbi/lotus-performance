from __future__ import annotations

from app.services.composite_metadata_store import CompositeMetadataStore
from scripts import seed_composite_performance_fixture


def test_seed_canonical_composite_fixture_upserts_expected_records(tmp_path, monkeypatch):
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'composite-fixture.db'}")
    store.create_schema()
    monkeypatch.setattr(seed_composite_performance_fixture, "composite_metadata_store", store)

    seed_composite_performance_fixture.seed_canonical_composite_fixture()

    counts = store.count_records()
    assert counts.definitions == 2
    assert counts.memberships == 4
    assert counts.member_return_facts == 6

    ready_facts = store.list_member_return_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start="2026-01-01",
        period_end="2026-02-28",
    )
    assert {fact.portfolio_id for fact in ready_facts} == {
        "PB_SG_GLOBAL_BAL_001",
        "PB_SG_GLOBAL_BAL_002",
    }
    assert all(fact.status == "READY" for fact in ready_facts)

    degraded_facts = store.list_member_return_facts(
        composite_id="PB_GLOBAL_BALANCED_USD_DEGRADED",
        period_start="2026-01-01",
        period_end="2026-01-31",
    )
    assert [fact.status for fact in degraded_facts] == ["READY", "DEGRADED"]
    assert degraded_facts[1].reason_codes == ["missing_final_valuation"]
