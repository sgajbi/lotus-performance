from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.models.inspection_responses import (
    TWRInspectionResponse,
    TWRInspectionWorkflowPackRun,
    TWRInspectionWorkflowPackRunFinding,
)
from app.services.http_resilience import post_with_retry

_WORKFLOW_PACK_ID = "twr_inspection_support_brief.pack"
_WORKFLOW_PACK_VERSION = "v1"
_WORKFLOW_SURFACE = "twr-supportability-inspection"


@dataclass(frozen=True)
class SupportBriefWorkflowPackResult:
    generation_status: str
    artifact_markdown: str | None = None
    workflow_pack_run: TWRInspectionWorkflowPackRun | None = None


def generate_twr_inspection_support_brief(
    *,
    inspection: TWRInspectionResponse,
) -> SupportBriefWorkflowPackResult:
    settings = get_settings()
    base_url = (settings.LOTUS_AI_BASE_URL or "").strip()
    if not base_url:
        return SupportBriefWorkflowPackResult(generation_status="NOT_CONFIGURED")

    status_code, payload = asyncio.run(
        post_with_retry(
            url=f"{base_url.rstrip('/')}/platform/workflow-packs/execute",
            timeout_seconds=settings.LOTUS_AI_TIMEOUT_SECONDS,
            json_body=_build_workflow_pack_request(
                inspection=inspection,
                environment=settings.LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT,
            ),
            headers={},
            max_retries=settings.LOTUS_AI_MAX_RETRIES,
            backoff_seconds=settings.LOTUS_AI_RETRY_BACKOFF_SECONDS,
        )
    )
    if status_code != 200:
        return SupportBriefWorkflowPackResult(generation_status="UNAVAILABLE")

    return _support_brief_result_from_payload(payload)


def _support_brief_result_from_payload(payload: dict[str, Any]) -> SupportBriefWorkflowPackResult:
    workflow_pack_run = _map_workflow_pack_run(payload.get("workflow_pack_run"))
    execution = payload.get("execution")
    if not isinstance(execution, dict):
        return SupportBriefWorkflowPackResult(
            generation_status="UNAVAILABLE",
            workflow_pack_run=workflow_pack_run,
        )
    artifact_markdown = _completed_support_brief_markdown(execution)
    if artifact_markdown is not None:
        return SupportBriefWorkflowPackResult(
            generation_status="GENERATED",
            artifact_markdown=artifact_markdown,
            workflow_pack_run=workflow_pack_run,
        )
    if workflow_pack_run is not None:
        return SupportBriefWorkflowPackResult(
            generation_status="ACTION_REQUIRED",
            workflow_pack_run=workflow_pack_run,
        )
    return SupportBriefWorkflowPackResult(generation_status="UNAVAILABLE")


def _completed_support_brief_markdown(execution: dict[str, Any]) -> str | None:
    if str(execution.get("status", "")) != "COMPLETED":
        return None
    result = execution.get("result")
    message = result.get("message") if isinstance(result, dict) else None
    if not isinstance(message, str) or not message.strip():
        return None
    return message.strip()


def _build_workflow_pack_request(
    *,
    inspection: TWRInspectionResponse,
    environment: str,
) -> dict[str, object]:
    return {
        "pack_id": _WORKFLOW_PACK_ID,
        "version": _WORKFLOW_PACK_VERSION,
        "environment": environment,
        "caller_identity_class": "INTERNAL_SERVICE",
        "workflow_surface": _WORKFLOW_SURFACE,
        "task_request": {
            "task_id": "explain.v1",
            "input_mode": "STRUCTURED_CONTEXT",
            "caller": {
                "caller_app": "lotus-performance",
                "correlation_id": f"twr-inspection-support-brief-{inspection.inspection_id}",
                "tenant_id": "tenant-sg-001",
            },
            "context": {
                "summary": (
                    f"TWR inspection support brief request for inspection {inspection.inspection_id} "
                    f"with verdict {inspection.verdict.value}."
                ),
                "payload": {
                    "inspection": {
                        "inspection_id": str(inspection.inspection_id),
                        "portfolio_id": inspection.portfolio_id,
                        "subject_type": inspection.subject_type.value,
                        "inspection_profile": inspection.inspection_profile.value,
                        "verdict": inspection.verdict.value,
                    },
                    "findings": [
                        {
                            "code": finding.code,
                            "severity": finding.severity,
                            "category": finding.category,
                            "owner_repo": finding.owner_repo,
                            "summary": finding.summary,
                            "recommended_action": finding.recommended_action,
                        }
                        for finding in inspection.findings
                    ],
                    "owner_summary": inspection.owner_summary.model_dump(mode="json"),
                    "evidence_summary": dict(inspection.evidence_summary),
                    "check_coverage": inspection.check_coverage.model_dump(mode="json"),
                },
                "source_refs": _build_source_refs(inspection=inspection),
            },
            "expected_output_label": "EXPLANATION_ONLY",
        },
    }


def _build_source_refs(*, inspection: TWRInspectionResponse) -> list[str]:
    refs = [
        f"lotus-performance:twr-inspection:{inspection.inspection_id}",
    ]
    if inspection.portfolio_id:
        refs.append(f"lotus-performance:portfolio:{inspection.portfolio_id}")
    if inspection.subject_calculation_id is not None:
        refs.append(f"lotus-performance:lineage:{inspection.subject_calculation_id}")
    return refs


def _map_workflow_pack_run(value: Any) -> TWRInspectionWorkflowPackRun | None:
    if not isinstance(value, dict):
        return None
    run_id = _workflow_pack_run_id(value)
    if run_id is None:
        return None
    return TWRInspectionWorkflowPackRun(
        run_id=run_id,
        runtime_state=str(value.get("runtime_state", "")),
        review_state=str(value.get("review_state", "")),
        allowed_review_actions=_string_items(value.get("allowed_review_actions")),
        supportability_status=str(value.get("supportability_status", "")),
        review_pending=_is_review_pending(value),
        superseded=_is_superseded(value),
        workflow_authority_owner=str(value.get("workflow_authority_owner", "")),
        current_summary_note=_build_summary_note(value),
        replacement_run_id=_optional_string(value.get("replacement_run_id")),
        findings=_map_workflow_pack_run_findings(value.get("findings")),
    )


def _workflow_pack_run_id(value: dict[str, Any]) -> str | None:
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    return run_id


def _map_workflow_pack_run_findings(value: Any) -> list[TWRInspectionWorkflowPackRunFinding]:
    if not isinstance(value, list):
        return []
    findings: list[TWRInspectionWorkflowPackRunFinding] = []
    for item in value:
        mapped_finding = _map_workflow_pack_run_finding(item)
        if mapped_finding is not None:
            findings.append(mapped_finding)
    return findings


def _map_workflow_pack_run_finding(value: Any) -> TWRInspectionWorkflowPackRunFinding | None:
    if not isinstance(value, dict):
        return None
    finding_id = value.get("finding_id")
    severity = value.get("severity")
    summary = value.get("summary")
    if not all(isinstance(part, str) and part.strip() for part in (finding_id, severity, summary)):
        return None
    return TWRInspectionWorkflowPackRunFinding(
        finding_id=finding_id,
        severity=severity,
        summary=summary,
    )


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _optional_string(value: Any) -> str | None:
    return str(value) if isinstance(value, str) else None


def _is_review_pending(value: dict[str, Any]) -> bool:
    return bool(value.get("review_state") == "AWAITING_REVIEW")


def _is_superseded(value: dict[str, Any]) -> bool:
    return bool(value.get("supportability_status") == "HISTORICAL")


def _build_summary_note(payload: dict[str, Any]) -> str:
    review_state = str(payload.get("review_state", ""))
    supportability_status = str(payload.get("supportability_status", ""))
    if supportability_status == "HISTORICAL":
        return "Run is historical due to replacement lineage."
    if review_state == "AWAITING_REVIEW":
        return "Run completed but still requires bounded human review before downstream use."
    if supportability_status == "READY":
        return "Run is ready for bounded downstream use."
    return "Workflow-pack run posture is available from lotus-ai."
