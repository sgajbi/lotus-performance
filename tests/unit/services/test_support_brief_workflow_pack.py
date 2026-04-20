from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import app.services.inspection.support_brief_workflow_pack as service
from app.models.inspection_requests import TWRInspectionProfile, TWRInspectionSubjectType
from app.models.inspection_responses import (
    TWRInspectionCheckCoverage,
    TWRInspectionOwnerSummary,
    TWRInspectionResponse,
    TWRInspectionVerdict,
)


def test_generate_twr_inspection_support_brief_returns_not_configured_when_base_url_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            LOTUS_AI_BASE_URL="",
            LOTUS_AI_TIMEOUT_SECONDS=10.0,
            LOTUS_AI_MAX_RETRIES=2,
            LOTUS_AI_RETRY_BACKOFF_SECONDS=0.2,
            LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT="DEVELOPMENT",
        ),
    )

    result = service.generate_twr_inspection_support_brief(inspection=_inspection_response())

    assert result.generation_status == "NOT_CONFIGURED"
    assert result.artifact_markdown is None
    assert result.workflow_pack_run is None


def test_generate_twr_inspection_support_brief_returns_markdown_and_run(monkeypatch) -> None:
    async def _fake_post_with_retry(**kwargs):
        return (
            200,
            {
                "execution": {
                    "status": "COMPLETED",
                    "result": {"message": "# Support brief\n\nReview source economics first."},
                },
                "workflow_pack_run": {
                    "run_id": "packrun_twr_inspection_support_brief_req_001",
                    "runtime_state": "COMPLETED",
                    "review_state": "AWAITING_REVIEW",
                    "allowed_review_actions": ["ACCEPT", "REJECT", "REVISE"],
                    "supportability_status": "ACTION_REQUIRED",
                    "workflow_authority_owner": "lotus-performance",
                    "findings": [
                        {
                            "finding_id": "review_pending",
                            "severity": "ACTION_REQUIRED",
                            "summary": "Run is awaiting review.",
                        }
                    ],
                },
            },
        )

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            LOTUS_AI_BASE_URL="http://lotus-ai.dev.lotus",
            LOTUS_AI_TIMEOUT_SECONDS=10.0,
            LOTUS_AI_MAX_RETRIES=2,
            LOTUS_AI_RETRY_BACKOFF_SECONDS=0.2,
            LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT="DEVELOPMENT",
        ),
    )
    monkeypatch.setattr(service, "post_with_retry", _fake_post_with_retry)

    result = service.generate_twr_inspection_support_brief(inspection=_inspection_response())

    assert result.generation_status == "GENERATED"
    assert result.artifact_markdown == "# Support brief\n\nReview source economics first."
    assert result.workflow_pack_run is not None
    assert result.workflow_pack_run.run_id == "packrun_twr_inspection_support_brief_req_001"
    assert result.workflow_pack_run.workflow_authority_owner == "lotus-performance"


def test_generate_twr_inspection_support_brief_preserves_failed_run_posture(monkeypatch) -> None:
    async def _fake_post_with_retry(**kwargs):
        return (
            200,
            {
                "execution": {
                    "status": "FAILED",
                    "result": {"message": "LIVE_EXECUTION_NOT_ENABLED"},
                },
                "workflow_pack_run": {
                    "run_id": "packrun_twr_inspection_support_brief_req_failed_001",
                    "runtime_state": "FAILED",
                    "review_state": "AWAITING_REVIEW",
                    "allowed_review_actions": ["ABANDON"],
                    "supportability_status": "ACTION_REQUIRED",
                    "workflow_authority_owner": "lotus-performance",
                },
            },
        )

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            LOTUS_AI_BASE_URL="http://lotus-ai.dev.lotus",
            LOTUS_AI_TIMEOUT_SECONDS=10.0,
            LOTUS_AI_MAX_RETRIES=2,
            LOTUS_AI_RETRY_BACKOFF_SECONDS=0.2,
            LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT="DEVELOPMENT",
        ),
    )
    monkeypatch.setattr(service, "post_with_retry", _fake_post_with_retry)

    result = service.generate_twr_inspection_support_brief(inspection=_inspection_response())

    assert result.generation_status == "ACTION_REQUIRED"
    assert result.artifact_markdown is None
    assert result.workflow_pack_run is not None
    assert result.workflow_pack_run.runtime_state == "FAILED"


def _inspection_response() -> TWRInspectionResponse:
    return TWRInspectionResponse(
        inspection_id=uuid4(),
        subject_type=TWRInspectionSubjectType.TWR_REQUEST,
        inspection_profile=TWRInspectionProfile.SUPPORT_TRIAGE,
        subject_calculation_id=None,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        status="complete",
        verdict=TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS,
        findings=[],
        owner_summary=TWRInspectionOwnerSummary(
            primary_owner_repo="lotus-performance",
            secondary_owner_repos=["lotus-core"],
        ),
        evidence_summary={"completed_check_families": 5},
        check_coverage=TWRInspectionCheckCoverage(
            completed_check_families=["source_quality"],
            pending_check_families=[],
        ),
        related_lineage=None,
        artifacts={},
        workflow_pack_run=None,
        generated_at_utc="2026-04-20T00:00:00Z",
    )
