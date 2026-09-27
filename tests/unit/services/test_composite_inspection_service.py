from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models.composites import CompositeDefinition, CompositeInspectionFinding, CompositeMemberReturnFact
from app.services.composite_calculation_service import CompositeDefinitionNotFoundError
from app.services.composite_inspection_service import (
    _build_artifacts,
    _composite_inspection_verdict,
    _composite_return_rows,
    _member_input_rows,
    _optional_artifact_text,
    _period_weight_rows,
    inspect_composite_twr_from_persisted_facts,
)
from app.services.composite_metadata_store import CompositeMetadataStore
from engine.composites import CompositeCalculationResult, CompositeMemberContribution, CompositePeriodResult


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


def _complete_publication(store: CompositeMetadataStore, *facts: CompositeMemberReturnFact) -> None:
    first = facts[0]
    store.complete_member_return_fact_publication(
        composite_id=first.composite_id,
        return_view=first.return_view,
        reporting_currency=first.reporting_currency,
        restatement_sequence=first.restatement_sequence,
        period_start=first.period_start,
        period_end=first.period_end,
        expected_families={(fact.portfolio_id, fact.period_start, fact.period_end) for fact in facts},
        source_fingerprint=f"sha256:test-publication-{first.reporting_currency}",
    )


def _inspection_finding(*, code: str, severity: str) -> CompositeInspectionFinding:
    return CompositeInspectionFinding(
        code=code,
        severity=severity,
        category="composite_calculation_supportability",
        owner_repo="lotus-performance",
        summary=f"Composite calculation reported {code}.",
        recommended_action="Review member inputs.",
        evidence={"reason_code": code.lower()},
    )


def test_composite_inspection_generates_classified_artifacts(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    facts = (_fact("P1"), _fact("P2"))
    for fact in facts:
        store.upsert_member_return_fact(fact)
    _complete_publication(store, *facts)

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
        '"restatement_sequences": [1], "restatement_versions": ["v1"], '
        '"source_fingerprints": ["sha256:P1", "sha256:P2"]}'
    )
    store.close()


def test_build_artifacts_preserves_names_classifications_lineage_and_brief():
    period_result = CompositePeriodResult(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        status="DEGRADED",
        return_value=Decimal("0.0125"),
        cumulative_return=Decimal("0.0125"),
        beginning_market_value=Decimal("400"),
        ending_market_value=Decimal("405"),
        member_count=1,
        excluded_member_count=1,
        dispersion_equal_weight=Decimal("0.0000"),
        return_view="NET_ACTUAL",
        reporting_currency="USD",
        source_fingerprints=["sha256:P1"],
        restatement_versions=["v1"],
        reason_codes=["missing_final_valuation"],
        member_contributions=[
            CompositeMemberContribution(
                portfolio_id="P1",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                return_value=Decimal("0.0125"),
                beginning_market_value=Decimal("400"),
                weight=Decimal("1.000000000000"),
                contribution=Decimal("0.012500000000"),
                source_snapshot_id="snapshot-P1",
                source_fingerprint="sha256:P1",
                restatement_version="v1",
                restatement_sequence=1,
                calculation_id="calc-P1",
            )
        ],
    )
    result = CompositeCalculationResult(
        composite_id="PB_GLOBAL_BALANCED_USD",
        status="DEGRADED",
        period_results=[period_result],
        cumulative_return=Decimal("0.0125"),
        reason_codes=["missing_final_valuation"],
    )

    artifacts = _build_artifacts(composite_id="PB_GLOBAL_BALANCED_USD", facts=[_fact("P1")], result=result)
    artifact_by_name = {artifact.artifact_name: artifact for artifact in artifacts}

    assert list(artifact_by_name) == [
        "member_inputs.csv",
        "period_weights.csv",
        "composite_returns.csv",
        "lineage_manifest.json",
        "support_brief.md",
    ]
    assert artifact_by_name["member_inputs.csv"].access_classification == "operator_only"
    assert artifact_by_name["period_weights.csv"].access_classification == "operator_only"
    assert artifact_by_name["composite_returns.csv"].access_classification == "customer_consumable"
    assert "source_fingerprint" in artifact_by_name["member_inputs.csv"].artifact_content.splitlines()[0]
    assert "beginning_asset_weight" in artifact_by_name["period_weights.csv"].artifact_content.splitlines()[0]
    assert artifact_by_name["lineage_manifest.json"].artifact_content == (
        '{"calculation_status": "DEGRADED", "composite_id": "PB_GLOBAL_BALANCED_USD", '
        '"restatement_sequences": [1], "restatement_versions": ["v1"], '
        '"source_fingerprints": ["sha256:P1"]}'
    )
    assert "- Reason codes: missing_final_valuation" in artifact_by_name["support_brief.md"].artifact_content


def test_composite_inspection_selects_one_reporting_currency_identity(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    usd_fact = _fact("P1", reporting_currency="USD")
    sgd_fact = _fact("P2", reporting_currency="SGD")
    store.upsert_member_return_fact(usd_fact)
    store.upsert_member_return_fact(sgd_fact)
    _complete_publication(store, usd_fact)

    response = inspect_composite_twr_from_persisted_facts(
        inspection_id=UUID("8d1e37d2-aeca-488c-bd43-77dbf6739103"),
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )

    assert response.verdict == "supportable"
    assert response.evidence_summary["member_return_fact_count"] == 1
    assert response.findings == []
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
    facts = (
        _fact("P1"),
        _fact("P2", status="DEGRADED", reason_codes=["missing_final_valuation"]),
    )
    for fact in facts:
        store.upsert_member_return_fact(fact)
    _complete_publication(store, *facts)

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


def test_composite_inspection_verdict_policy_preserves_status_priority():
    assert _composite_inspection_verdict(result_status="READY", findings=[]) == "supportable"
    assert (
        _composite_inspection_verdict(
            result_status="READY",
            findings=[
                _inspection_finding(
                    code="MISSING_FINAL_VALUATION",
                    severity="warning",
                )
            ],
        )
        == "supportable_with_warnings"
    )
    assert _composite_inspection_verdict(result_status="DEGRADED", findings=[]) == "supportable_with_warnings"
    assert (
        _composite_inspection_verdict(
            result_status="BLOCKED",
            findings=[
                _inspection_finding(
                    code="MIXED_MEMBER_REPORTING_CURRENCIES",
                    severity="critical",
                )
            ],
        )
        == "not_supportable"
    )


def test_member_input_rows_preserve_operator_lineage_values():
    rows = _member_input_rows([_fact("P1", status="DEGRADED", reason_codes=["missing_final_valuation"])])

    assert rows == [
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_view": "NET_ACTUAL",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "status": "DEGRADED",
            "reason_codes": "missing_final_valuation",
            "source_fingerprint": "sha256:P1",
            "restatement_version": "v1",
            "restatement_sequence": 1,
        }
    ]


def test_period_weight_rows_preserve_contribution_lineage_order():
    rows = _period_weight_rows(
        [
            CompositePeriodResult(
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                status="READY",
                return_value=Decimal("0.0100"),
                cumulative_return=Decimal("0.0100"),
                beginning_market_value=Decimal("100"),
                ending_market_value=Decimal("101"),
                member_count=1,
                excluded_member_count=0,
                dispersion_equal_weight=Decimal("0"),
                return_view="NET_ACTUAL",
                reporting_currency="USD",
                source_fingerprints=["sha256:P1"],
                restatement_versions=["v1"],
                reason_codes=[],
                member_contributions=[
                    CompositeMemberContribution(
                        portfolio_id="P1",
                        period_start=date(2026, 1, 1),
                        period_end=date(2026, 1, 31),
                        return_value=Decimal("0.0100"),
                        beginning_market_value=Decimal("100"),
                        weight=Decimal("1.000000000000"),
                        contribution=Decimal("0.010000000000"),
                        source_snapshot_id="snapshot-P1",
                        source_fingerprint="sha256:P1",
                        restatement_version="v1",
                        restatement_sequence=1,
                        calculation_id="calc-P1",
                    )
                ],
            )
        ]
    )

    assert rows == [
        {
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "beginning_asset_weight": "1.000000000000",
            "contribution": "0.010000000000",
            "source_fingerprint": "sha256:P1",
            "restatement_version": "v1",
            "restatement_sequence": 1,
        }
    ]


def test_optional_artifact_text_formats_missing_and_decimal_values():
    assert _optional_artifact_text(None) == ""
    assert _optional_artifact_text(Decimal("0.0000")) == "0.0000"


def test_composite_return_rows_formats_optional_customer_consumable_values():
    rows = _composite_return_rows(
        [
            CompositePeriodResult(
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                status="DEGRADED",
                return_value=None,
                cumulative_return=Decimal("0.0125"),
                beginning_market_value=Decimal("100"),
                ending_market_value=Decimal("101"),
                member_count=2,
                excluded_member_count=1,
                dispersion_equal_weight=None,
                return_view=None,
                reporting_currency=None,
                source_fingerprints=[],
                restatement_versions=[],
                reason_codes=["missing_member"],
                member_contributions=[],
            )
        ]
    )

    assert rows == [
        {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "status": "DEGRADED",
            "return_view": "",
            "reporting_currency": "",
            "return_value": "",
            "cumulative_return": "0.0125",
            "member_count": 2,
            "excluded_member_count": 1,
            "dispersion_equal_weight": "",
            "reason_codes": "missing_member",
        }
    ]
