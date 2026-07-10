from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from app.models.inspection_requests import TWRInspectionProfile, TWRInspectionRequest
from app.models.inspection_responses import (
    TWRInspectionCheckCoverage,
    TWRInspectionFinding,
    TWRInspectionOwnerSummary,
    TWRInspectionRelatedLineage,
    TWRInspectionResponse,
    TWRInspectionVerdict,
)
from app.models.requests import DailyInputData, PerformanceRequest
from app.models.responses import PerformanceResponse
from app.models.twr_requests import TWRResolvedExecutionRequest
from app.services.durable_store_time import format_timestamp
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import (
    EXECUTION_STAGE_ARTIFACT_MATERIALIZATION,
    EXECUTION_STAGE_FINDING_SYNTHESIS,
    EXECUTION_STAGE_MATH_RECONCILIATION,
    EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT,
    EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT,
    EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION,
    EXECUTION_STAGE_SUBJECT_RESOLUTION,
)
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
from app.services.inspection.subject_resolution import ResolvedTWRInspectionSubject, resolve_twr_inspection_subject
from app.services.inspection.support_brief_workflow_pack import (
    generate_twr_inspection_support_brief,
)

_ALL_CHECK_FAMILIES = [
    "calculation_consistency",
    "source_quality",
    "economic_plausibility",
    "reconciliation",
    "cashflow_classification",
]


@dataclass(frozen=True)
class _InspectionStageOutputs:
    findings: list[TWRInspectionFinding]
    completed_check_families: list[str]
    failed_check_families: list[str]
    evidence_summary: dict[str, object]
    artifact_payloads: dict[str, str]


@dataclass(frozen=True)
class _InspectionResponseSynthesis:
    response: TWRInspectionResponse
    artifact_payloads: dict[str, str]
    support_brief_generation_status: str


@dataclass(frozen=True)
class _InspectionFindingsContext:
    findings: list[TWRInspectionFinding]
    pending_check_families: list[str]
    evidence_summary: dict[str, object]


@dataclass(frozen=True)
class _SubjectInspectionInputs:
    consistency_findings: list[TWRInspectionFinding]
    completed_check_families: list[str]
    failed_check_families: list[str]
    evidence_summary: dict[str, object]
    performance_request: PerformanceRequest | None
    resolved_execution_request: TWRResolvedExecutionRequest | None


@dataclass(frozen=True)
class _SubjectAssessmentOutputs:
    source_quality_findings: list[TWRInspectionFinding]
    reconciliation_findings: list[TWRInspectionFinding]
    source_economics_findings: list[TWRInspectionFinding]
    completed_check_families: list[str]
    failed_check_families: list[str]
    evidence_summary: dict[str, object]
    artifact_payloads: dict[str, str]


@dataclass
class _SubjectAssessmentAggregation:
    completed_check_families: list[str]
    failed_check_families: list[str]
    evidence_summary: dict[str, object]
    artifact_payloads: dict[str, str]

    def merge(self, outputs: _InspectionStageOutputs) -> None:
        self.completed_check_families.extend(outputs.completed_check_families)
        self.failed_check_families.extend(outputs.failed_check_families)
        self.evidence_summary.update(outputs.evidence_summary)
        self.artifact_payloads.update(outputs.artifact_payloads)


def run_twr_inspection(request: TWRInspectionRequest) -> TWRInspectionResponse:
    execution_registry.mark_running(request.inspection_id)
    subject = _resolve_inspection_subject(request)
    subject_inputs = _resolve_subject_inspection_inputs(request=request, subject=subject)
    subject_assessments = _run_subject_assessments(
        request=request,
        subject=subject,
        subject_inputs=subject_inputs,
        base_evidence_summary=_base_inspection_evidence_summary(
            subject=subject,
            subject_inputs=subject_inputs,
        ),
    )
    response_synthesis = _complete_twr_inspection_response(
        request=request,
        subject=subject,
        subject_inputs=subject_inputs,
        subject_assessments=subject_assessments,
    )
    _materialize_twr_inspection_artifacts(
        request=request,
        response_synthesis=response_synthesis,
    )
    return response_synthesis.response


def _base_inspection_evidence_summary(
    *,
    subject: ResolvedTWRInspectionSubject,
    subject_inputs: _SubjectInspectionInputs,
) -> dict[str, object]:
    evidence_summary: dict[str, object] = {
        "artifact_queue_enabled": True,
        "related_execution_found": subject.related_execution is not None,
    }
    evidence_summary.update(subject_inputs.evidence_summary)
    return evidence_summary


def _complete_twr_inspection_response(
    *,
    request: TWRInspectionRequest,
    subject: ResolvedTWRInspectionSubject,
    subject_inputs: _SubjectInspectionInputs,
    subject_assessments: _SubjectAssessmentOutputs,
) -> _InspectionResponseSynthesis:
    execution_registry.start_stage(request.inspection_id, EXECUTION_STAGE_FINDING_SYNTHESIS)
    response_synthesis = _build_twr_inspection_response(
        request=request,
        subject_calculation_id=subject.subject_calculation_id,
        portfolio_id=subject.portfolio_id,
        consistency_findings=subject_inputs.consistency_findings,
        source_quality_findings=subject_assessments.source_quality_findings,
        reconciliation_findings=subject_assessments.reconciliation_findings,
        source_economics_findings=subject_assessments.source_economics_findings,
        completed_check_families=subject_assessments.completed_check_families,
        failed_check_families=subject_assessments.failed_check_families,
        evidence_summary=subject_assessments.evidence_summary,
        artifact_payloads=subject_assessments.artifact_payloads,
    )
    response = response_synthesis.response
    execution_registry.complete_stage(
        request.inspection_id,
        EXECUTION_STAGE_FINDING_SYNTHESIS,
        details={
            "verdict": response.verdict.value,
            "finding_count": len(response.findings),
            "support_brief_generation_status": response_synthesis.support_brief_generation_status,
        },
    )
    return response_synthesis


def _materialize_twr_inspection_artifacts(
    *,
    request: TWRInspectionRequest,
    response_synthesis: _InspectionResponseSynthesis,
) -> None:
    response = response_synthesis.response
    artifact_payloads = response_synthesis.artifact_payloads
    execution_registry.start_stage(request.inspection_id, EXECUTION_STAGE_ARTIFACT_MATERIALIZATION)
    try:
        enqueue_twr_inspection_artifacts(
            inspection_id=request.inspection_id,
            request_model=request,
            response_model=response,
            artifact_payloads=artifact_payloads,
        )
    except Exception as exc:
        execution_registry.fail_stage_and_execution(
            request.inspection_id,
            EXECUTION_STAGE_ARTIFACT_MATERIALIZATION,
            str(exc),
        )
        raise


def _run_subject_assessments(
    *,
    request: TWRInspectionRequest,
    subject: ResolvedTWRInspectionSubject,
    subject_inputs: _SubjectInspectionInputs,
    base_evidence_summary: dict[str, object],
) -> _SubjectAssessmentOutputs:
    aggregation = _SubjectAssessmentAggregation(
        completed_check_families=list(subject_inputs.completed_check_families),
        failed_check_families=list(subject_inputs.failed_check_families),
        evidence_summary=dict(base_evidence_summary),
        artifact_payloads={},
    )

    source_quality_findings: list[TWRInspectionFinding] = []
    if subject_inputs.performance_request is not None:
        source_quality_outputs = _run_source_quality_assessment(
            inspection_id=request.inspection_id,
            performance_request=subject_inputs.performance_request,
            inspection_profile=request.inspection_profile,
        )
        source_quality_findings = source_quality_outputs.findings
        aggregation.merge(source_quality_outputs)

    reconciliation_findings: list[TWRInspectionFinding] = []
    source_economics_findings: list[TWRInspectionFinding] = []
    if subject_inputs.resolved_execution_request is not None and subject.portfolio_id is not None:
        performance_request = subject_inputs.resolved_execution_request.portfolio
        reconciliation_outputs = _run_reconciliation_assessment(
            inspection_id=request.inspection_id,
            performance_request=performance_request,
            portfolio_id=subject.portfolio_id,
            inspection_profile=request.inspection_profile,
        )
        reconciliation_findings = reconciliation_outputs.findings
        aggregation.merge(reconciliation_outputs)

        source_economics_outputs = _run_source_economics_assessment(
            inspection_id=request.inspection_id,
            performance_request=performance_request,
            portfolio_id=subject.portfolio_id,
        )
        source_economics_findings = source_economics_outputs.findings
        aggregation.merge(source_economics_outputs)

    return _SubjectAssessmentOutputs(
        source_quality_findings=source_quality_findings,
        reconciliation_findings=reconciliation_findings,
        source_economics_findings=source_economics_findings,
        completed_check_families=aggregation.completed_check_families,
        failed_check_families=aggregation.failed_check_families,
        evidence_summary=aggregation.evidence_summary,
        artifact_payloads=aggregation.artifact_payloads,
    )


def _resolve_subject_inspection_inputs(
    *,
    request: TWRInspectionRequest,
    subject: ResolvedTWRInspectionSubject,
) -> _SubjectInspectionInputs:
    if subject.subject_calculation_id is None:
        return _request_subject_inspection_inputs(subject)

    consistency_findings: list[TWRInspectionFinding] = []
    failed_check_families: list[str] = []
    execution_registry.start_stage(request.inspection_id, EXECUTION_STAGE_MATH_RECONCILIATION)
    try:
        subject_inputs = _existing_calculation_subject_inspection_inputs(subject)
    except Exception as exc:
        _record_check_failure(
            inspection_id=request.inspection_id,
            findings=consistency_findings,
            failed_check_families=failed_check_families,
            families=["calculation_consistency"],
            stage=EXECUTION_STAGE_MATH_RECONCILIATION,
            error=exc,
        )
        return _SubjectInspectionInputs(
            consistency_findings=consistency_findings,
            completed_check_families=[],
            failed_check_families=failed_check_families,
            evidence_summary={},
            performance_request=None,
            resolved_execution_request=None,
        )

    execution_registry.complete_stage(
        request.inspection_id,
        EXECUTION_STAGE_MATH_RECONCILIATION,
        details=subject_inputs.evidence_summary,
    )
    return subject_inputs


def _request_subject_inspection_inputs(subject: ResolvedTWRInspectionSubject) -> _SubjectInspectionInputs:
    return _SubjectInspectionInputs(
        consistency_findings=[],
        completed_check_families=[],
        failed_check_families=[],
        evidence_summary={},
        performance_request=extract_performance_request_from_payload(subject.request_payload),
        resolved_execution_request=None,
    )


def _existing_calculation_subject_inspection_inputs(
    subject: ResolvedTWRInspectionSubject,
) -> _SubjectInspectionInputs:
    if subject.subject_calculation_id is None:
        return _request_subject_inspection_inputs(subject)

    existing_artifacts = load_existing_twr_calculation_artifacts(subject.subject_calculation_id)
    resolved_execution_request = extract_resolved_execution_request_from_payload(existing_artifacts.request_payload)
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
    return _SubjectInspectionInputs(
        consistency_findings=consistency_result.findings,
        completed_check_families=["calculation_consistency"],
        failed_check_families=[],
        evidence_summary=consistency_result.evidence_summary,
        performance_request=performance_request,
        resolved_execution_request=resolved_execution_request,
    )


def _resolve_inspection_subject(request: TWRInspectionRequest) -> ResolvedTWRInspectionSubject:
    execution_registry.start_stage(request.inspection_id, EXECUTION_STAGE_SUBJECT_RESOLUTION)
    try:
        subject = resolve_twr_inspection_subject(request)
    except Exception as exc:
        execution_registry.fail_stage(request.inspection_id, EXECUTION_STAGE_SUBJECT_RESOLUTION, str(exc))
        raise
    execution_registry.complete_stage(
        request.inspection_id,
        EXECUTION_STAGE_SUBJECT_RESOLUTION,
        details={
            "subject_type": request.subject_type.value,
            "portfolio_id": subject.portfolio_id,
            "subject_calculation_id": (
                str(subject.subject_calculation_id) if subject.subject_calculation_id is not None else None
            ),
        },
    )
    return subject


def _build_twr_inspection_response(
    *,
    request: TWRInspectionRequest,
    subject_calculation_id: UUID | None,
    portfolio_id: str | None,
    consistency_findings: list[TWRInspectionFinding],
    source_quality_findings: list[TWRInspectionFinding],
    reconciliation_findings: list[TWRInspectionFinding],
    source_economics_findings: list[TWRInspectionFinding],
    completed_check_families: list[str],
    failed_check_families: list[str],
    evidence_summary: dict[str, object],
    artifact_payloads: dict[str, str],
) -> _InspectionResponseSynthesis:
    findings_context = _build_inspection_findings_context(
        consistency_findings=consistency_findings,
        source_quality_findings=source_quality_findings,
        reconciliation_findings=reconciliation_findings,
        source_economics_findings=source_economics_findings,
        completed_check_families=completed_check_families,
        failed_check_families=failed_check_families,
        evidence_summary=evidence_summary,
    )
    verdict = _synthesize_verdict(
        findings=findings_context.findings,
        completed_check_families=completed_check_families,
        failed_check_families=failed_check_families,
        pending_check_families=findings_context.pending_check_families,
    )
    response = _build_twr_inspection_response_model(
        request=request,
        subject_calculation_id=subject_calculation_id,
        portfolio_id=portfolio_id,
        findings_context=findings_context,
        completed_check_families=completed_check_families,
        verdict=verdict,
        artifact_payloads=artifact_payloads,
    )
    return _attach_support_brief_to_inspection_response(
        response=response,
        artifact_payloads=artifact_payloads,
    )


def _build_twr_inspection_response_model(
    *,
    request: TWRInspectionRequest,
    subject_calculation_id: UUID | None,
    portfolio_id: str | None,
    findings_context: _InspectionFindingsContext,
    completed_check_families: list[str],
    verdict: TWRInspectionVerdict,
    artifact_payloads: dict[str, str],
) -> TWRInspectionResponse:
    return TWRInspectionResponse(
        inspection_id=request.inspection_id,
        subject_type=request.subject_type,
        inspection_profile=request.inspection_profile,
        subject_calculation_id=subject_calculation_id,
        portfolio_id=portfolio_id,
        status="complete",
        verdict=verdict,
        findings=findings_context.findings,
        owner_summary=_build_owner_summary(findings_context.findings),
        evidence_summary=findings_context.evidence_summary,
        check_coverage=TWRInspectionCheckCoverage(
            completed_check_families=completed_check_families,
            pending_check_families=findings_context.pending_check_families,
        ),
        related_lineage=TWRInspectionRelatedLineage(
            calculation_id=subject_calculation_id,
            lineage_path=f"/performance/lineage/{subject_calculation_id}"
            if subject_calculation_id is not None
            else None,
        ),
        artifacts=_build_twr_inspection_artifact_links(
            inspection_id=request.inspection_id,
            artifact_payloads=artifact_payloads,
        ),
        workflow_pack_run=None,
        generated_at_utc=format_timestamp(datetime.now(UTC)) or "",
    )


def _attach_support_brief_to_inspection_response(
    *,
    response: TWRInspectionResponse,
    artifact_payloads: dict[str, str],
) -> _InspectionResponseSynthesis:
    support_brief_result = generate_twr_inspection_support_brief(inspection=response)
    evidence_summary = dict(response.evidence_summary)
    evidence_summary["support_brief_generation_status"] = support_brief_result.generation_status
    if support_brief_result.workflow_pack_run is not None:
        evidence_summary["support_brief_workflow_pack_run_id"] = support_brief_result.workflow_pack_run.run_id
    if support_brief_result.artifact_markdown is not None:
        artifact_payloads["support_brief.md"] = support_brief_result.artifact_markdown
    updated_response = response.model_copy(
        update={
            "evidence_summary": evidence_summary,
            "artifacts": _build_twr_inspection_artifact_links(
                inspection_id=response.inspection_id,
                artifact_payloads=artifact_payloads,
            ),
            "workflow_pack_run": support_brief_result.workflow_pack_run,
        }
    )
    return _InspectionResponseSynthesis(
        response=updated_response,
        artifact_payloads=artifact_payloads,
        support_brief_generation_status=support_brief_result.generation_status,
    )


def _build_inspection_findings_context(
    *,
    consistency_findings: list[TWRInspectionFinding],
    source_quality_findings: list[TWRInspectionFinding],
    reconciliation_findings: list[TWRInspectionFinding],
    source_economics_findings: list[TWRInspectionFinding],
    completed_check_families: list[str],
    failed_check_families: list[str],
    evidence_summary: dict[str, object],
) -> _InspectionFindingsContext:
    findings = [
        *consistency_findings,
        *source_quality_findings,
        *reconciliation_findings,
        *source_economics_findings,
    ]
    evidence = dict(evidence_summary)
    if failed_check_families:
        evidence["failed_check_families"] = failed_check_families
    if not completed_check_families and not findings:
        findings.append(_build_no_check_family_executed_finding())
    return _InspectionFindingsContext(
        findings=findings,
        pending_check_families=_pending_check_families(completed_check_families),
        evidence_summary=evidence,
    )


def _pending_check_families(completed_check_families: list[str]) -> list[str]:
    return [family for family in _ALL_CHECK_FAMILIES if family not in completed_check_families]


def _run_source_quality_assessment(
    *,
    inspection_id: UUID,
    performance_request: PerformanceRequest,
    inspection_profile: TWRInspectionProfile,
) -> _InspectionStageOutputs:
    findings: list[TWRInspectionFinding] = []
    failed_check_families: list[str] = []
    execution_registry.start_stage(inspection_id, EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT)
    try:
        source_quality_result = run_source_quality_checks(
            performance_request=performance_request,
            inspection_profile=inspection_profile,
        )
    except Exception as exc:
        _record_check_failure(
            inspection_id=inspection_id,
            findings=findings,
            failed_check_families=failed_check_families,
            families=["source_quality", "economic_plausibility"],
            stage=EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT,
            error=exc,
        )
        return _InspectionStageOutputs(
            findings=findings,
            completed_check_families=[],
            failed_check_families=failed_check_families,
            evidence_summary={},
            artifact_payloads={},
        )

    execution_registry.complete_stage(
        inspection_id,
        EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT,
        details=source_quality_result.evidence_summary,
    )
    return _InspectionStageOutputs(
        findings=source_quality_result.findings,
        completed_check_families=["source_quality", "economic_plausibility"],
        failed_check_families=[],
        evidence_summary=source_quality_result.evidence_summary,
        artifact_payloads={
            "source_quality_summary.json": json.dumps(
                source_quality_result.artifact_payload,
                indent=2,
            )
        },
    )


def _run_reconciliation_assessment(
    *,
    inspection_id: UUID,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    inspection_profile: TWRInspectionProfile,
) -> _InspectionStageOutputs:
    findings: list[TWRInspectionFinding] = []
    failed_check_families: list[str] = []
    execution_registry.start_stage(inspection_id, EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION)
    try:
        reconciliation_result = run_reconciliation_checks(
            performance_request=performance_request,
            portfolio_id=portfolio_id,
            inspection_profile=inspection_profile,
        )
    except Exception as exc:
        _record_check_failure(
            inspection_id=inspection_id,
            findings=findings,
            failed_check_families=failed_check_families,
            families=["reconciliation"],
            stage=EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION,
            error=exc,
        )
        return _InspectionStageOutputs(
            findings=findings,
            completed_check_families=[],
            failed_check_families=failed_check_families,
            evidence_summary={},
            artifact_payloads={},
        )

    execution_registry.complete_stage(
        inspection_id,
        EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION,
        details=reconciliation_result.evidence_summary,
    )
    return _InspectionStageOutputs(
        findings=reconciliation_result.findings,
        completed_check_families=["reconciliation"],
        failed_check_families=[],
        evidence_summary=reconciliation_result.evidence_summary,
        artifact_payloads={
            "reconciliation_summary.json": json.dumps(
                reconciliation_result.artifact_payload,
                indent=2,
            )
        },
    )


def _run_source_economics_assessment(
    *,
    inspection_id: UUID,
    performance_request: PerformanceRequest,
    portfolio_id: str,
) -> _InspectionStageOutputs:
    findings: list[TWRInspectionFinding] = []
    failed_check_families: list[str] = []
    execution_registry.start_stage(inspection_id, EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT)
    try:
        source_economics_result = run_source_economics_checks(
            performance_request=performance_request,
            portfolio_id=portfolio_id,
        )
    except Exception as exc:
        _record_check_failure(
            inspection_id=inspection_id,
            findings=findings,
            failed_check_families=failed_check_families,
            families=["cashflow_classification"],
            stage=EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT,
            error=exc,
        )
        return _InspectionStageOutputs(
            findings=findings,
            completed_check_families=[],
            failed_check_families=failed_check_families,
            evidence_summary={},
            artifact_payloads={},
        )

    execution_registry.complete_stage(
        inspection_id,
        EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT,
        details=source_economics_result.evidence_summary,
    )
    return _InspectionStageOutputs(
        findings=source_economics_result.findings,
        completed_check_families=["cashflow_classification"],
        failed_check_families=[],
        evidence_summary=source_economics_result.evidence_summary,
        artifact_payloads={
            "source_economics_summary.json": json.dumps(
                source_economics_result.artifact_payload,
                indent=2,
            )
        },
    )


def _build_twr_inspection_artifact_links(
    *,
    inspection_id: UUID,
    artifact_payloads: dict[str, str],
) -> dict[str, str]:
    artifact_links = {
        "inspection_summary.json": f"/performance/inspections/{inspection_id}/artifacts/inspection_summary.json",
        "findings.json": f"/performance/inspections/{inspection_id}/artifacts/findings.json",
    }
    for artifact_name in (
        "source_quality_summary.json",
        "reconciliation_summary.json",
        "source_economics_summary.json",
        "support_brief.md",
    ):
        if artifact_name in artifact_payloads:
            artifact_links[artifact_name] = f"/performance/inspections/{inspection_id}/artifacts/{artifact_name}"
    return artifact_links


def _synthesize_verdict(
    *,
    findings: list[TWRInspectionFinding],
    completed_check_families: list[str],
    failed_check_families: list[str],
    pending_check_families: list[str],
) -> TWRInspectionVerdict:
    if _only_failed_check_families(
        completed_check_families=completed_check_families,
        failed_check_families=failed_check_families,
    ):
        return TWRInspectionVerdict.INSPECTION_FAILED
    if _has_not_supportable_finding(findings):
        return TWRInspectionVerdict.NOT_SUPPORTABLE
    if findings or pending_check_families:
        return TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS
    return TWRInspectionVerdict.SUPPORTABLE


def _only_failed_check_families(
    *,
    completed_check_families: list[str],
    failed_check_families: list[str],
) -> bool:
    return bool(failed_check_families) and not completed_check_families


def _has_not_supportable_finding(findings: list[TWRInspectionFinding]) -> bool:
    return any(finding.severity in {"high", "critical"} for finding in findings)


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


def _build_no_check_family_executed_finding() -> TWRInspectionFinding:
    return TWRInspectionFinding(
        code="INSPECTION_NO_CHECK_FAMILY_EXECUTED",
        severity="warning",
        category="inspection_runtime",
        owner_repo="lotus-performance",
        summary="No TWR inspection check family executed for the resolved subject.",
        explanation=(
            "The inspector could resolve the subject envelope, but no inspectable TWR request payload or persisted "
            "calculation artifacts were available to run calculation, source-quality, reconciliation, or "
            "source-economics checks."
        ),
        recommended_action=(
            "Verify that the inspection request includes a valid TWR request payload or that the inspected "
            "calculation has retained request and response artifacts, then rerun the inspection."
        ),
        evidence={
            "completed_check_families": [],
            "pending_check_families": list(_ALL_CHECK_FAMILIES),
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
    scoped_points = _valuation_points_in_window(
        performance_request.valuation_points,
        start_date=master_start,
        end_date=master_end,
    )
    if not scoped_points:
        return performance_request
    return performance_request.model_copy(
        update={
            "performance_start_date": master_start,
            "report_end_date": master_end,
            "valuation_points": scoped_points,
        }
    )


def _valuation_points_in_window(
    valuation_points: list[DailyInputData],
    *,
    start_date: date,
    end_date: date,
) -> list[DailyInputData]:
    return [point for point in valuation_points if start_date <= point.perf_date <= end_date]


def _response_master_window(response_model: PerformanceResponse) -> tuple[date | None, date | None]:
    master_window_values = _response_master_window_values(response_model)
    if master_window_values is None:
        return None, None
    master_start_raw, master_end_raw = master_window_values
    try:
        return date.fromisoformat(master_start_raw), date.fromisoformat(master_end_raw)
    except ValueError:
        return None, None


def _response_master_window_values(response_model: PerformanceResponse) -> tuple[str, str] | None:
    periods = response_model.meta.periods
    if not isinstance(periods, dict):
        return None
    master_start_raw = periods.get("master_start")
    master_end_raw = periods.get("master_end")
    if not isinstance(master_start_raw, str) or not isinstance(master_end_raw, str):
        return None
    return master_start_raw, master_end_raw


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
