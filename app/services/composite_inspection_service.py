from __future__ import annotations

import csv
import io
import json
from datetime import date as dt_date
from uuid import UUID

from app.models.composites import (
    CompositeInspectionArtifact,
    CompositeInspectionFinding,
    CompositeInspectionResponse,
)
from app.services.composite_calculation_service import CompositeDefinitionNotFoundError
from app.services.composite_metadata_store import CompositeMetadataStore, composite_metadata_store
from app.services.durable_store_runtime import RuntimeStoreProxy
from engine.composites import CompositePeriodResult, calculate_asset_weighted_composite_twr


def _csv_text(fieldnames: list[str], rows: list[dict[str, object]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _artifact(name: str, content_type: str, classification: str, artifact_content: str) -> CompositeInspectionArtifact:
    return CompositeInspectionArtifact(
        artifact_name=name,
        content_type=content_type,
        access_classification=classification,
        artifact_content=artifact_content,
    )


def inspect_composite_twr_from_persisted_facts(
    *,
    inspection_id: UUID,
    composite_id: str,
    period_start: dt_date,
    period_end: dt_date,
    store: CompositeMetadataStore | RuntimeStoreProxy[CompositeMetadataStore] = composite_metadata_store,
) -> CompositeInspectionResponse:
    definition = store.get_definition(composite_id)
    if definition is None:
        raise CompositeDefinitionNotFoundError(f"Composite definition not found: {composite_id}")

    facts = store.list_member_return_facts(
        composite_id=composite_id,
        period_start=period_start,
        period_end=period_end,
    )
    result = calculate_asset_weighted_composite_twr(composite_id=composite_id, member_return_facts=facts)
    findings = _build_findings(result_status=result.status, reason_codes=result.reason_codes, fact_count=len(facts))
    artifacts = _build_artifacts(composite_id=composite_id, facts=facts, result=result)
    verdict = "supportable"
    if result.status == "BLOCKED":
        verdict = "not_supportable"
    elif findings or result.status == "DEGRADED":
        verdict = "supportable_with_warnings"

    return CompositeInspectionResponse(
        inspection_id=inspection_id,
        composite_id=composite_id,
        period_start=period_start,
        period_end=period_end,
        status="complete",
        verdict=verdict,
        findings=findings,
        evidence_summary={
            "member_return_fact_count": len(facts),
            "period_count": len(result.period_results),
            "calculation_status": result.status,
            "reason_codes": result.reason_codes,
            "artifact_count": len(artifacts),
        },
        artifacts=artifacts,
    )


def _build_findings(
    *, result_status: str, reason_codes: list[str], fact_count: int
) -> list[CompositeInspectionFinding]:
    findings: list[CompositeInspectionFinding] = []
    if fact_count == 0:
        findings.append(
            CompositeInspectionFinding(
                code="NO_MEMBER_RETURN_FACTS",
                severity="critical",
                category="member_return_fact_quality",
                owner_repo="lotus-performance",
                summary="No persisted member-return facts were available for the composite inspection window.",
                recommended_action="Materialize member-return facts before calculating or publishing composite performance.",
                evidence={"fact_count": fact_count},
            )
        )
    for code in reason_codes:
        severity = "critical" if result_status == "BLOCKED" else "warning"
        findings.append(
            CompositeInspectionFinding(
                code=code.upper(),
                severity=severity,
                category="composite_calculation_supportability",
                owner_repo="lotus-performance",
                summary=f"Composite calculation reported {code}.",
                recommended_action="Review member inputs, source fingerprints, return views, currency, and restatement versions.",
                evidence={"reason_code": code},
            )
        )
    return findings


def _member_input_rows(facts) -> list[dict[str, object]]:
    return [
        {
            "composite_id": fact.composite_id,
            "portfolio_id": fact.portfolio_id,
            "period_start": fact.period_start.isoformat(),
            "period_end": fact.period_end.isoformat(),
            "return_view": fact.return_view.value,
            "return_value": str(fact.return_value),
            "beginning_market_value": str(fact.beginning_market_value),
            "ending_market_value": str(fact.ending_market_value),
            "reporting_currency": fact.reporting_currency,
            "status": fact.status.value,
            "reason_codes": "|".join(fact.reason_codes),
            "source_fingerprint": fact.source_fingerprint,
            "restatement_version": fact.restatement_version,
        }
        for fact in facts
    ]


def _period_weight_rows(period_results: list[CompositePeriodResult]) -> list[dict[str, object]]:
    return [
        {
            "portfolio_id": contribution.portfolio_id,
            "period_start": contribution.period_start.isoformat(),
            "period_end": contribution.period_end.isoformat(),
            "beginning_asset_weight": str(contribution.weight),
            "contribution": str(contribution.contribution),
            "source_fingerprint": contribution.source_fingerprint,
            "restatement_version": contribution.restatement_version,
        }
        for period in period_results
        for contribution in period.member_contributions
    ]


def _build_artifacts(*, composite_id: str, facts, result) -> list[CompositeInspectionArtifact]:
    member_rows = _member_input_rows(facts)
    weight_rows = _period_weight_rows(result.period_results)
    composite_rows = _composite_return_rows(result.period_results)
    lineage_manifest = {
        "composite_id": composite_id,
        "calculation_status": result.status,
        "source_fingerprints": sorted({fact.source_fingerprint for fact in facts}),
        "restatement_versions": sorted({fact.restatement_version for fact in facts}),
    }
    support_brief = (
        f"# Composite Inspection Brief\n\n"
        f"- Composite: {composite_id}\n"
        f"- Status: {result.status}\n"
        f"- Periods inspected: {len(result.period_results)}\n"
        f"- Member-return facts inspected: {len(facts)}\n"
        f"- Reason codes: {', '.join(result.reason_codes) if result.reason_codes else 'none'}\n"
    )

    return [
        _artifact(
            "member_inputs.csv",
            "text/csv",
            "operator_only",
            _csv_text(
                [
                    "composite_id",
                    "portfolio_id",
                    "period_start",
                    "period_end",
                    "return_view",
                    "return_value",
                    "beginning_market_value",
                    "ending_market_value",
                    "reporting_currency",
                    "status",
                    "reason_codes",
                    "source_fingerprint",
                    "restatement_version",
                ],
                member_rows,
            ),
        ),
        _artifact(
            "period_weights.csv",
            "text/csv",
            "operator_only",
            _csv_text(
                [
                    "portfolio_id",
                    "period_start",
                    "period_end",
                    "beginning_asset_weight",
                    "contribution",
                    "source_fingerprint",
                    "restatement_version",
                ],
                weight_rows,
            ),
        ),
        _artifact(
            "composite_returns.csv",
            "text/csv",
            "customer_consumable",
            _csv_text(
                [
                    "period_start",
                    "period_end",
                    "status",
                    "return_view",
                    "reporting_currency",
                    "return_value",
                    "cumulative_return",
                    "member_count",
                    "excluded_member_count",
                    "dispersion_equal_weight",
                    "reason_codes",
                ],
                composite_rows,
            ),
        ),
        _artifact(
            "lineage_manifest.json",
            "application/json",
            "operator_only",
            json.dumps(lineage_manifest, sort_keys=True),
        ),
        _artifact("support_brief.md", "text/markdown", "operator_only", support_brief),
    ]


def _composite_return_rows(period_results: list[CompositePeriodResult]) -> list[dict[str, object]]:
    return [
        {
            "period_start": period.period_start.isoformat(),
            "period_end": period.period_end.isoformat(),
            "status": period.status,
            "return_view": period.return_view or "",
            "reporting_currency": period.reporting_currency or "",
            "return_value": "" if period.return_value is None else str(period.return_value),
            "cumulative_return": "" if period.cumulative_return is None else str(period.cumulative_return),
            "member_count": period.member_count,
            "excluded_member_count": period.excluded_member_count,
            "dispersion_equal_weight": ""
            if period.dispersion_equal_weight is None
            else str(period.dispersion_equal_weight),
            "reason_codes": "|".join(period.reason_codes),
        }
        for period in period_results
    ]
