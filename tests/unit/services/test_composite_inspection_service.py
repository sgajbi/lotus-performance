from __future__ import annotations

from datetime import date
from uuid import UUID

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact
from app.services.composite_calculation_service import CompositeDefinitionNotFoundError
from app.services.composite_inspection_service import inspect_composite_twr_from_persisted_facts
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


def _fact(
    portfolio_id: str,
    reporting_currency: str = "USD",
    *,
    status: str = "READY",
    reason_codes: list[str] | None = None,
) -> CompositeMemberReturnFact:
    return CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": portfolio_id,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": reporting_currency,
            "calculation_id": f"calc-{portfolio_id}",
            "source_snapshot_id": f"snapshot-{portfolio_id}",
            "source_fingerprint": f"sha256:{portfolio_id}",
            "status": status,
            "reason_codes": reason_codes or [],
        }
    )


def test_composite_inspection_generates_classified_artifacts(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    store.upsert_member_return_fact(_fact("P1"))
    store.upsert_member_return_fact(_fact("P2"))

    response = inspect_composite_twr_from_persisted_facts(
        inspection_id=UUID("8d1e37d2-aeca-488c-bd43-77dbf6739103"),
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )

    artifacts = {artifact.artifact_name: artifact for artifact in response.artifacts}
    assert response.verdict == "supportable"
    assert response.evidence_summary["member_return_fact_count"] == 2
    assert artifacts["member_inputs.csv"].access_classification == "operator_only"
    assert "source_fingerprint" in artifacts["member_inputs.csv"].artifact_content
    assert artifacts["composite_returns.csv"].access_classification == "customer_consumable"
    assert artifacts["lineage_manifest.json"].artifact_content == (
        '{"calculation_status": "READY", "composite_id": "PB_GLOBAL_BALANCED_USD", '
        '"restatement_versions": ["v1"], "source_fingerprints": ["sha256:P1", "sha256:P2"]}'
    )
    store.close()


def test_composite_inspection_reports_blocking_findings(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    store.upsert_member_return_fact(_fact("P1", reporting_currency="USD"))
    store.upsert_member_return_fact(_fact("P2", reporting_currency="SGD"))

    response = inspect_composite_twr_from_persisted_facts(
        inspection_id=UUID("8d1e37d2-aeca-488c-bd43-77dbf6739103"),
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )

    assert response.verdict == "not_supportable"
    assert response.findings[0].code == "MIXED_MEMBER_REPORTING_CURRENCIES"
    assert response.findings[0].severity == "critical"
    store.close()


def test_composite_inspection_rejects_missing_definition(tmp_path):
    store = _store(tmp_path)

    try:
        inspect_composite_twr_from_persisted_facts(
            inspection_id=UUID("8d1e37d2-aeca-488c-bd43-77dbf6739103"),
            composite_id="PB_GLOBAL_BALANCED_USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            store=store,
        )
    except CompositeDefinitionNotFoundError as exc:
        assert "PB_GLOBAL_BALANCED_USD" in str(exc)
    else:
        raise AssertionError("Expected missing composite definition to fail")
    store.close()


def test_composite_inspection_reports_no_member_return_facts(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())

    response = inspect_composite_twr_from_persisted_facts(
        inspection_id=UUID("8d1e37d2-aeca-488c-bd43-77dbf6739103"),
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )

    assert response.verdict == "not_supportable"
    assert response.findings[0].code == "NO_MEMBER_RETURN_FACTS"
    assert response.findings[0].evidence == {"fact_count": 0}
    store.close()


def test_composite_inspection_reports_degraded_verdict(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    store.upsert_member_return_fact(_fact("P1"))
    store.upsert_member_return_fact(_fact("P2", status="DEGRADED", reason_codes=["missing_final_valuation"]))

    response = inspect_composite_twr_from_persisted_facts(
        inspection_id=UUID("8d1e37d2-aeca-488c-bd43-77dbf6739103"),
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )

    assert response.verdict == "supportable_with_warnings"
    assert response.findings[0].code == "MISSING_FINAL_VALUATION"
    assert response.findings[0].severity == "warning"
    store.close()
