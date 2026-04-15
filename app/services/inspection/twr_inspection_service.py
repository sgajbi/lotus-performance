from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import UUID

from app.models.inspection_requests import TWRInspectionRequest
from app.models.inspection_responses import (
    TWRInspectionCheckCoverage,
    TWRInspectionFinding,
    TWRInspectionOwnerSummary,
    TWRInspectionRelatedLineage,
    TWRInspectionResponse,
    TWRInspectionVerdict,
)
from app.models.requests import PerformanceRequest
from app.models.responses import PerformanceResponse
from app.models.twr_requests import TWRResolvedExecutionRequest
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

    consistency_findings: list[TWRInspectionFinding] = []
    completed_check_families: list[str] = []
    failed_check_families: list[str] = []
    evidence_summary: dict[str, object] = {
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
            performance_request = _scope_request_to_response_master_window(
                performance_request,
                existing_artifacts.response_model,
            )
            resolved_execution_request = _scope_resolved_request_to_response_master_window(
                resolved_execution_request,
                existing_artifacts.response_model,
            )
        except Exception as exc:
            _record_check_failure(
                inspection_id=request.inspection_id,
                findings=consistency_findings,
                failed_check_families=failed_check_families,
                families=["calculation_consistency"],
                stage="math_reconciliation",
                error=exc,
            )
        else:
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

    source_quality_findings: list[TWRInspectionFinding] = []
    if performance_request is not None:
        execution_registry.start_stage(request.inspection_id, "source_quality_assessment")
        try:
            source_quality_result = run_source_quality_checks(
                performance_request=performance_request,
                inspection_profile=request.inspection_profile,
            )
        except Exception as exc:
            _record_check_failure(
                inspection_id=request.inspection_id,
                findings=source_quality_findings,
                failed_check_families=failed_check_families,
                families=["source_quality", "economic_plausibility"],
                stage="source_quality_assessment",
                error=exc,
            )
        else:
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

    reconciliation_findings: list[TWRInspectionFinding] = []
    if resolved_execution_request is not None and subject.portfolio_id is not None:
        execution_registry.start_stage(request.inspection_id, "source_state_reconciliation")
        try:
            reconciliation_result = run_reconciliation_checks(
                performance_request=resolved_execution_request.portfolio,
                portfolio_id=subject.portfolio_id,
                inspection_profile=request.inspection_profile,
            )
        except Exception as exc:
            _record_check_failure(
                inspection_id=request.inspection_id,
                findings=reconciliation_findings,
                failed_check_families=failed_check_families,
                families=["reconciliation"],
                stage="source_state_reconciliation",
                error=exc,
            )
        else:
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

    source_economics_findings: list[TWRInspectionFinding] = []
    if resolved_execution_request is not None and subject.portfolio_id is not None:
        execution_registry.start_stage(request.inspection_id, "source_economics_assessment")
        try:
            source_economics_result = run_source_economics_checks(
                performance_request=resolved_execution_request.portfolio,
                portfolio_id=subject.portfolio_id,
            )
        except Exception as exc:
            _record_check_failure(
                inspection_id=request.inspection_id,
                findings=source_economics_findings,
                failed_check_families=failed_check_families,
                families=["cashflow_classification"],
                stage="source_economics_assessment",
                error=exc,
            )
        else:
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
    if failed_check_families:
        evidence_summary["failed_check_families"] = failed_check_families
    if not completed_check_families and not findings:
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
    verdict = _synthesize_verdict(
        findings=findings,
        completed_check_families=completed_check_families,
        failed_check_families=failed_check_families,
        pending_check_families=pending_check_families,
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
    completed_check_families: list[str],
    failed_check_families: list[str],
    pending_check_families: list[str],
) -> TWRInspectionVerdict:
    if failed_check_families and not completed_check_families:
        return TWRInspectionVerdict.INSPECTION_FAILED
    if any(finding.severity in {"high", "critical"} for finding in findings):
        return TWRInspectionVerdict.NOT_SUPPORTABLE
    if findings or pending_check_families:
        return TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS
    return TWRInspectionVerdict.SUPPORTABLE


def _record_check_failure(
    *,
    inspection_id: UUID,
    findings: list[TWRInspectionFinding],
    failed_check_families: list[str],
    families: list[str],
    stage: str,
    error: Exception,
) -> None:
    execution_registry.fail_stage(inspection_id, stage, str(error))
    failed_check_families.extend(families)
    findings.append(
        _build_check_failure_finding(
            families=families,
            stage=stage,
            error=error,
        )
    )


def _build_check_failure_finding(
    *,
    families: list[str],
    stage: str,
    error: Exception,
) -> TWRInspectionFinding:
    family_label = ", ".join(f"`{family}`" for family in families)
    return TWRInspectionFinding(
        code="INSPECTION_CHECK_FAMILY_FAILED",
        severity="warning",
        category="inspection_runtime",
        owner_repo="lotus-performance",
        summary=f"Inspection check family {family_label} failed before producing supportability evidence.",
        explanation=(
            "The inspector preserved this failure as runtime evidence so other completed check families can still be "
            "reviewed truthfully."
        ),
        recommended_action=(
            "Review the failed inspection stage and rerun the inspection after the runtime or upstream dependency is "
            "healthy."
        ),
        evidence={
            "check_families": families,
            "stage": stage,
            "error_type": type(error).__name__,
            "error_message": str(error),
        },
    )


def _scope_resolved_request_to_response_master_window(
    resolved_request: TWRResolvedExecutionRequest | None,
    response_model: PerformanceResponse,
) -> TWRResolvedExecutionRequest | None:
    if resolved_request is None:
        return None
    scoped_portfolio = _scope_request_to_response_master_window(resolved_request.portfolio, response_model)
    if scoped_portfolio is None:
        return resolved_request
    return resolved_request.model_copy(update={"portfolio": scoped_portfolio})


def _scope_request_to_response_master_window(
    performance_request: PerformanceRequest | None,
    response_model: PerformanceResponse,
) -> PerformanceRequest | None:
    if performance_request is None:
        return None
    master_start, master_end = _response_master_window(response_model)
    if master_start is None or master_end is None:
        return performance_request
    scoped_points = [
        point for point in performance_request.valuation_points if master_start <= point.perf_date <= master_end
    ]
    if not scoped_points:
        return performance_request
    return performance_request.model_copy(
        update={
            "performance_start_date": master_start,
            "report_end_date": master_end,
            "valuation_points": scoped_points,
        }
    )


def _response_master_window(response_model: PerformanceResponse) -> tuple[date | None, date | None]:
    periods = response_model.meta.periods
    master_start_raw = periods.get("master_start") if isinstance(periods, dict) else None
    master_end_raw = periods.get("master_end") if isinstance(periods, dict) else None
    if not isinstance(master_start_raw, str) or not isinstance(master_end_raw, str):
        return None, None
    try:
        return date.fromisoformat(master_start_raw), date.fromisoformat(master_end_raw)
    except ValueError:
        return None, None


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
