from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.models.composites import (  # noqa: E402
    CompositeDefinition,
    CompositeMemberReturnFact,
    CompositeMembership,
    CompositeReturnView,
)
from app.services.composite_metadata_store import composite_metadata_store  # noqa: E402
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores  # noqa: E402


@dataclass(frozen=True)
class MemberReturnSeed:
    composite_id: str
    portfolio_id: str
    period_start: str
    period_end: str
    return_value: str
    beginning_market_value: str
    ending_market_value: str
    calculation_id: str
    source_snapshot_id: str
    source_fingerprint: str
    restatement_version: str = "v1"
    status: str = "READY"
    reason_codes: tuple[str, ...] = ()


def _source_authority() -> dict[str, str]:
    return {
        "definition_owner": "lotus-manage",
        "membership_owner": "lotus-manage",
        "member_return_owner": "lotus-performance",
        "asset_owner": "lotus-core",
        "benchmark_owner": "lotus-core",
        "policy_version": "composite-source-authority.v1",
    }


def _upsert_definition(tenant_id: str, composite_id: str, display_name: str, strategy_code: str) -> None:
    composite_metadata_store.upsert_definition(
        CompositeDefinition.model_validate(
            {
                "composite_id": composite_id,
                "display_name": display_name,
                "strategy_code": strategy_code,
                "reporting_currency": "USD",
                "inception_date": "2026-01-01",
                "source_authority": _source_authority(),
            }
        ),
        tenant_id=tenant_id,
    )


def _upsert_membership(tenant_id: str, composite_id: str, portfolio_id: str) -> None:
    composite_metadata_store.upsert_membership(
        CompositeMembership.model_validate(
            {
                "composite_id": composite_id,
                "portfolio_id": portfolio_id,
                "effective_from": "2026-01-01",
                "status": "INCLUDED",
                "discretionary": True,
                "source_snapshot_id": f"lotus-manage-membership-{composite_id}-{portfolio_id}-2026-05-12",
            }
        ),
        tenant_id=tenant_id,
    )


def _upsert_fact(tenant_id: str, seed: MemberReturnSeed) -> None:
    composite_metadata_store.upsert_member_return_fact(
        CompositeMemberReturnFact.model_validate(
            {
                "composite_id": seed.composite_id,
                "portfolio_id": seed.portfolio_id,
                "period_start": seed.period_start,
                "period_end": seed.period_end,
                "return_value": Decimal(seed.return_value),
                "return_view": "NET_ACTUAL",
                "beginning_market_value": Decimal(seed.beginning_market_value),
                "ending_market_value": Decimal(seed.ending_market_value),
                "reporting_currency": "USD",
                "calculation_id": seed.calculation_id,
                "source_snapshot_id": seed.source_snapshot_id,
                "source_fingerprint": seed.source_fingerprint,
                "restatement_version": seed.restatement_version,
                "status": seed.status,
                "reason_codes": list(seed.reason_codes),
            }
        ),
        tenant_id=tenant_id,
    )


def _complete_publication(tenant_id: str, facts: tuple[MemberReturnSeed, ...]) -> None:
    first = facts[0]
    composite_metadata_store.complete_member_return_fact_publication(
        tenant_id=tenant_id,
        composite_id=first.composite_id,
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=1,
        period_start=min(date.fromisoformat(fact.period_start) for fact in facts),
        period_end=max(date.fromisoformat(fact.period_end) for fact in facts),
        expected_families={
            (fact.portfolio_id, date.fromisoformat(fact.period_start), date.fromisoformat(fact.period_end))
            for fact in facts
        },
        source_fingerprint=f"sha256:{first.composite_id.lower()}-net-actual-v1-publication",
    )


def seed_canonical_composite_fixture(*, tenant_id: str) -> None:
    ready_composite_id = "PB_GLOBAL_BALANCED_USD"
    degraded_composite_id = "PB_GLOBAL_BALANCED_USD_DEGRADED"

    _upsert_definition(
        tenant_id,
        ready_composite_id,
        "Private Banking Global Balanced USD Composite",
        "GLOBAL_BALANCED",
    )
    _upsert_definition(
        tenant_id,
        degraded_composite_id,
        "Private Banking Global Balanced USD Composite - Degraded Evidence",
        "GLOBAL_BALANCED",
    )

    portfolios = ("PB_SG_GLOBAL_BAL_001", "PB_SG_GLOBAL_BAL_002")
    for composite_id in (ready_composite_id, degraded_composite_id):
        for portfolio_id in portfolios:
            _upsert_membership(tenant_id, composite_id, portfolio_id)

    ready_facts = (
        MemberReturnSeed(
            composite_id=ready_composite_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            period_start="2026-01-01",
            period_end="2026-01-31",
            return_value="0.0100",
            beginning_market_value="100.00",
            ending_market_value="101.00",
            calculation_id="calc-pb-sg-global-bal-001-2026-01",
            source_snapshot_id="snapshot-pb-sg-global-bal-001-2026-01",
            source_fingerprint="sha256:pb-sg-global-bal-001-2026-01-net-actual-v1",
        ),
        MemberReturnSeed(
            composite_id=ready_composite_id,
            portfolio_id="PB_SG_GLOBAL_BAL_002",
            period_start="2026-01-01",
            period_end="2026-01-31",
            return_value="0.0300",
            beginning_market_value="300.00",
            ending_market_value="309.00",
            calculation_id="calc-pb-sg-global-bal-002-2026-01",
            source_snapshot_id="snapshot-pb-sg-global-bal-002-2026-01",
            source_fingerprint="sha256:pb-sg-global-bal-002-2026-01-net-actual-v1",
        ),
        MemberReturnSeed(
            composite_id=ready_composite_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            period_start="2026-02-01",
            period_end="2026-02-28",
            return_value="-0.0100",
            beginning_market_value="110.00",
            ending_market_value="108.90",
            calculation_id="calc-pb-sg-global-bal-001-2026-02",
            source_snapshot_id="snapshot-pb-sg-global-bal-001-2026-02",
            source_fingerprint="sha256:pb-sg-global-bal-001-2026-02-net-actual-v1",
        ),
        MemberReturnSeed(
            composite_id=ready_composite_id,
            portfolio_id="PB_SG_GLOBAL_BAL_002",
            period_start="2026-02-01",
            period_end="2026-02-28",
            return_value="0.0300",
            beginning_market_value="330.00",
            ending_market_value="339.90",
            calculation_id="calc-pb-sg-global-bal-002-2026-02",
            source_snapshot_id="snapshot-pb-sg-global-bal-002-2026-02",
            source_fingerprint="sha256:pb-sg-global-bal-002-2026-02-net-actual-v1",
        ),
    )

    degraded_facts = (
        MemberReturnSeed(
            composite_id=degraded_composite_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            period_start="2026-01-01",
            period_end="2026-01-31",
            return_value="0.0100",
            beginning_market_value="100.00",
            ending_market_value="101.00",
            calculation_id="calc-pb-sg-global-bal-001-2026-01",
            source_snapshot_id="snapshot-pb-sg-global-bal-001-2026-01",
            source_fingerprint="sha256:pb-sg-global-bal-001-2026-01-net-actual-v1",
        ),
        MemberReturnSeed(
            composite_id=degraded_composite_id,
            portfolio_id="PB_SG_GLOBAL_BAL_002",
            period_start="2026-01-01",
            period_end="2026-01-31",
            return_value="0.0300",
            beginning_market_value="300.00",
            ending_market_value="309.00",
            calculation_id="calc-pb-sg-global-bal-002-2026-01",
            source_snapshot_id="snapshot-pb-sg-global-bal-002-2026-01",
            source_fingerprint="sha256:pb-sg-global-bal-002-2026-01-net-actual-v1",
            status="DEGRADED",
            reason_codes=("missing_final_valuation",),
        ),
    )

    for fact in (*ready_facts, *degraded_facts):
        _upsert_fact(tenant_id, fact)
    _complete_publication(tenant_id, ready_facts)
    _complete_publication(tenant_id, degraded_facts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic RFC 049 composite performance live proof data.")
    parser.add_argument("--tenant-id", required=True, help="Admitted tenant that owns the seeded composite data.")
    args = parser.parse_args()

    bootstrap_durable_metadata_stores()
    seed_canonical_composite_fixture(tenant_id=args.tenant_id)
    counts = composite_metadata_store.count_records(tenant_id=args.tenant_id)
    print(
        "Seeded RFC 049 composite fixture: "
        f"definitions={counts.definitions}, memberships={counts.memberships}, "
        f"member_return_facts={counts.member_return_facts}"
    )


if __name__ == "__main__":
    main()
