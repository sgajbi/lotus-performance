from __future__ import annotations

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
from app.services.inspection.calculation_consistency import run_twr_calculation_consistency_checks
from app.services.inspection.artifact_service import enqueue_twr_inspection_artifacts
from app.services.inspection.subject_materialization import load_existing_twr_calculation_artifacts
from app.services.inspection.subject_resolution import resolve_twr_inspection_subject

_PENDING_CHECK_FAMILIES = [
    "source_quality",
    "economic_plausibility",
    "reconciliation",
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
    verdict = TWRInspectionVerdict.INSPECTION_FAILED
    if subject.subject_calculation_id is not None:
        execution_registry.start_stage(request.inspection_id, "math_reconciliation")
        try:
            existing_artifacts = load_existing_twr_calculation_artifacts(subject.subject_calculation_id)
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
        verdict = (
            TWRInspectionVerdict.NOT_SUPPORTABLE
            if consistency_findings
            else TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS
        )

    execution_registry.start_stage(request.inspection_id, "finding_synthesis")
    findings = list(consistency_findings)
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
                    "pending_check_families": ["calculation_consistency", *_PENDING_CHECK_FAMILIES],
                },
            )
        )
    response = TWRInspectionResponse(
        inspection_id=request.inspection_id,
        subject_type=request.subject_type,
        inspection_profile=request.inspection_profile,
        subject_calculation_id=subject.subject_calculation_id,
        portfolio_id=subject.portfolio_id,
        status="complete",
        verdict=verdict,
        findings=findings,
        owner_summary=TWRInspectionOwnerSummary(
            primary_owner_repo="lotus-performance",
            secondary_owner_repos=[],
        ),
        evidence_summary=evidence_summary,
        check_coverage=TWRInspectionCheckCoverage(
            completed_check_families=completed_check_families,
            pending_check_families=(
                list(_PENDING_CHECK_FAMILIES)
                if completed_check_families
                else ["calculation_consistency", *_PENDING_CHECK_FAMILIES]
            ),
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
        )
    except Exception as exc:
        execution_registry.fail_stage(request.inspection_id, "artifact_materialization", str(exc))
        raise
    execution_registry.mark_complete(request.inspection_id)
    return response
