from __future__ import annotations

import json
from datetime import datetime, timezone

from app.models.inspection_requests import TWRInspectionRequest
from app.models.inspection_responses import (
    TWRInspectionCheckCoverage,
    TWRInspectionFinding,
    TWRInspectionOwnerSummary,
    TWRInspectionRelatedLineage,
    TWRInspectionResponse,
    TWRInspectionVerdict,
)
from app.services.execution_registry import execution_registry
from app.services.inspection.artifact_service import enqueue_twr_inspection_artifacts
from app.services.inspection.calculation_consistency import run_twr_calculation_consistency_checks
from app.services.inspection.reconciliation import run_reconciliation_checks
from app.services.inspection.source_economics import run_source_economics_checks
from app.services.inspection.source_quality import run_source_quality_checks
from app.services.inspection.subject_materialization import (
    extract_performance_request_from_payload,
    extract_resolved_execution_request_from_payload,
    load_existing_twr_calculation_artifacts,
)
from app.services.inspection.subject_resolution import resolve_twr_inspection_subject

_ALL_CHECK_FAMILIES = [
    "calculation_consistency",
    "source_quality",
    "economic_plausibility",
    "reconciliation",
    "cashflow_classification",
]


def run_twr_inspection(request: TWRInspectionRequest) -> TWRInspectionResponse:
    execution_registry.mark_running(request.inspection_id)
    execution_registry.start_stage(request.inspection_id, "subject_resolution")
    try:
        subject = resolve_twr_inspection_subject(request)
    except Exception as exc:
        execution_registry.fail_stage(request.inspection_id, "subject_resolution", str(exc))
        raise
    execution_registry.complete_stage(
        request.inspection_id,
        "subject_resolution",
        details={
            "subject_type": request.subject_type.value,
            "portfolio_id": subject.portfolio_id,
            "subject_calculation_id": (
                str(subject.subject_calculation_id) if subject.subject_calculation_id is not None else None
            ),
        },
    )

    consistency_findings = []
    completed_check_families: list[str] = []
    evidence_summary = {
        "artifact_queue_enabled": True,
        "related_execution_found": subject.related_execution is not None,
    }
    artifact_payloads: dict[str, str] = {}
    performance_request = None
    resolved_execution_request = None
    if subject.subject_calculation_id is not None:
        execution_registry.start_stage(request.inspection_id, "math_reconciliation")
        try:
            existing_artifacts = load_existing_twr_calculation_artifacts(subject.subject_calculation_id)
            resolved_execution_request = extract_resolved_execution_request_from_payload(
                existing_artifacts.request_payload
            )
            performance_request = extract_performance_request_from_payload(existing_artifacts.request_payload)
            consistency_result = run_twr_calculation_consistency_checks(existing_artifacts.response_model)
        except Exception as exc:
            execution_registry.fail_stage(request.inspection_id, "math_reconciliation", str(exc))
            raise
        execution_registry.complete_stage(
            request.inspection_id,
            "math_reconciliation",
            details=consistency_result.evidence_summary,
        )
        consistency_findings = consistency_result.findings
        completed_check_families.append("calculation_consistency")
        evidence_summary.update(consistency_result.evidence_summary)
    else:
        performance_request = extract_performance_request_from_payload(subject.request_payload)

    source_quality_findings = []
    if performance_request is not None:
        execution_registry.start_stage(request.inspection_id, "source_quality_assessment")
        try:
            source_quality_result = run_source_quality_checks(
                performance_request=performance_request,
                inspection_profile=request.inspection_profile,
            )
        except Exception as exc:
            execution_registry.fail_stage(request.inspection_id, "source_quality_assessment", str(exc))
            raise
        execution_registry.complete_stage(
            request.inspection_id,
            "source_quality_assessment",
            details=source_quality_result.evidence_summary,
        )
        source_quality_findings = source_quality_result.findings
        completed_check_families.extend(["source_quality", "economic_plausibility"])
        evidence_summary.update(source_quality_result.evidence_summary)
        artifact_payloads["source_quality_summary.json"] = json.dumps(
            source_quality_result.artifact_payload,
            indent=2,
        )

    reconciliation_findings = []
    if resolved_execution_request is not None and subject.portfolio_id is not None:
        execution_registry.start_stage(request.inspection_id, "source_state_reconciliation")
        try:
            reconciliation_result = run_reconciliation_checks(
                performance_request=resolved_execution_request.portfolio,
                portfolio_id=subject.portfolio_id,
                inspection_profile=request.inspection_profile,
            )
        except Exception as exc:
            execution_registry.fail_stage(request.inspection_id, "source_state_reconciliation", str(exc))
            raise
        execution_registry.complete_stage(
            request.inspection_id,
            "source_state_reconciliation",
            details=reconciliation_result.evidence_summary,
        )
        reconciliation_findings = reconciliation_result.findings
        completed_check_families.append("reconciliation")
        evidence_summary.update(reconciliation_result.evidence_summary)
        artifact_payloads["reconciliation_summary.json"] = json.dumps(
            reconciliation_result.artifact_payload,
            indent=2,
        )

    source_economics_findings = []
    if resolved_execution_request is not None and subject.portfolio_id is not None:
        execution_registry.start_stage(request.inspection_id, "source_economics_assessment")
        try:
            source_economics_result = run_source_economics_checks(
                performance_request=resolved_execution_request.portfolio,
                portfolio_id=subject.portfolio_id,
            )
        except Exception as exc:
            execution_registry.fail_stage(request.inspection_id, "source_economics_assessment", str(exc))
            raise
        execution_registry.complete_stage(
            request.inspection_id,
            "source_economics_assessment",
            details=source_economics_result.evidence_summary,
        )
        source_economics_findings = source_economics_result.findings
        completed_check_families.append("cashflow_classification")
        evidence_summary.update(source_economics_result.evidence_summary)
        artifact_payloads["source_economics_summary.json"] = json.dumps(
            source_economics_result.artifact_payload,
            indent=2,
        )

    execution_registry.start_stage(request.inspection_id, "finding_synthesis")
    findings = [
        *consistency_findings,
        *source_quality_findings,
        *reconciliation_findings,
        *source_economics_findings,
    ]
    if not completed_check_families:
        findings.append(
            TWRInspectionFinding(
                code="INSPECTION_CHECKS_PENDING_IMPLEMENTATION",
                severity="warning",
                category="inspection_runtime",
                owner_repo="lotus-performance",
                summary="Inspection runtime skeleton is active, but supportability checks are not implemented yet.",
                explanation=(
                    "RFC-045 slice 1 establishes the durable inspection contract, async runtime path, "
                    "and artifact plumbing. Calculation-consistency, source-quality, plausibility, "
                    "and reconciliation checks are deferred to later slices."
                ),
                recommended_action=(
                    "Treat this inspection as a runtime-contract proof only and wait for later slices "
                    "before relying on verdicts for operational supportability."
                ),
                evidence={
                    "implemented_slice": "slice_1_contract_runtime_skeleton",
                    "completed_check_families": [],
                    "pending_check_families": list(_ALL_CHECK_FAMILIES),
                },
            )
        )
    pending_check_families = [family for family in _ALL_CHECK_FAMILIES if family not in completed_check_families]
    verdict = _synthesize_verdict(findings=findings, pending_check_families=pending_check_families)
    response = TWRInspectionResponse(
        inspection_id=request.inspection_id,
        subject_type=request.subject_type,
        inspection_profile=request.inspection_profile,
        subject_calculation_id=subject.subject_calculation_id,
        portfolio_id=subject.portfolio_id,
        status="complete",
        verdict=verdict,
        findings=findings,
        owner_summary=_build_owner_summary(findings),
        evidence_summary=evidence_summary,
        check_coverage=TWRInspectionCheckCoverage(
            completed_check_families=completed_check_families,
            pending_check_families=pending_check_families,
        ),
        related_lineage=(
            TWRInspectionRelatedLineage(
                calculation_id=subject.subject_calculation_id,
                lineage_path=(
                    f"/performance/lineage/{subject.subject_calculation_id}"
                    if subject.subject_calculation_id is not None
                    else None
                ),
            )
        ),
        artifacts={
            "inspection_summary.json": (
                f"/performance/inspections/{request.inspection_id}/artifacts/inspection_summary.json"
            ),
            "findings.json": f"/performance/inspections/{request.inspection_id}/artifacts/findings.json",
            **(
                {
                    "source_quality_summary.json": (
                        f"/performance/inspections/{request.inspection_id}/artifacts/source_quality_summary.json"
                    )
                }
                if "source_quality_summary.json" in artifact_payloads
                else {}
            ),
            **(
                {
                    "reconciliation_summary.json": (
                        f"/performance/inspections/{request.inspection_id}/artifacts/reconciliation_summary.json"
                    )
                }
                if "reconciliation_summary.json" in artifact_payloads
                else {}
            ),
            **(
                {
                    "source_economics_summary.json": (
                        f"/performance/inspections/{request.inspection_id}/artifacts/source_economics_summary.json"
                    )
                }
                if "source_economics_summary.json" in artifact_payloads
                else {}
            ),
        },
        generated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    execution_registry.complete_stage(
        request.inspection_id,
        "finding_synthesis",
        details={
            "verdict": response.verdict.value,
            "finding_count": len(response.findings),
        },
    )

    execution_registry.start_stage(request.inspection_id, "artifact_materialization")
    try:
        enqueue_twr_inspection_artifacts(
            inspection_id=request.inspection_id,
            request_model=request,
            response_model=response,
            artifact_payloads=artifact_payloads,
        )
    except Exception as exc:
        execution_registry.fail_stage(request.inspection_id, "artifact_materialization", str(exc))
        raise
    execution_registry.mark_complete(request.inspection_id)
    return response


def _synthesize_verdict(
    *,
    findings: list[TWRInspectionFinding],
    pending_check_families: list[str],
) -> TWRInspectionVerdict:
    if any(finding.severity in {"high", "critical"} for finding in findings):
        return TWRInspectionVerdict.NOT_SUPPORTABLE
    if findings or pending_check_families:
        return TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS
    return TWRInspectionVerdict.SUPPORTABLE


def _build_owner_summary(findings: list[TWRInspectionFinding]) -> TWRInspectionOwnerSummary:
    if not findings:
        return TWRInspectionOwnerSummary(primary_owner_repo="lotus-performance", secondary_owner_repos=[])

    severity_weights = {"info": 1, "warning": 2, "high": 3, "critical": 4}
    owner_scores: dict[str, int] = {}
    for finding in findings:
        owner_scores[finding.owner_repo] = owner_scores.get(finding.owner_repo, 0) + severity_weights.get(
            finding.severity,
            0,
        )
    ordered_owners = sorted(owner_scores, key=lambda owner: (-owner_scores[owner], owner))
    return TWRInspectionOwnerSummary(
        primary_owner_repo=ordered_owners[0],
        secondary_owner_repos=ordered_owners[1:],
    )
