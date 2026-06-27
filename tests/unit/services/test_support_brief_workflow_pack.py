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


def test_generate_twr_inspection_support_brief_returns_unavailable_on_non_200(
    monkeypatch,
) -> None:
    captured_request: dict[str, object] = {}

    async def _fake_post_with_retry(**kwargs):
        captured_request.update(kwargs)
        return 503, {"detail": "lotus-ai unavailable"}

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            LOTUS_AI_BASE_URL="http://lotus-ai.dev.lotus/",
            LOTUS_AI_TIMEOUT_SECONDS=7.5,
            LOTUS_AI_MAX_RETRIES=3,
            LOTUS_AI_RETRY_BACKOFF_SECONDS=0.4,
            LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT="DEVELOPMENT",
        ),
    )
    monkeypatch.setattr(service, "post_with_retry", _fake_post_with_retry)

    result = service.generate_twr_inspection_support_brief(inspection=_inspection_response())

    assert result.generation_status == "UNAVAILABLE"
    assert result.artifact_markdown is None
    assert result.workflow_pack_run is None
    assert captured_request["url"] == "http://lotus-ai.dev.lotus/platform/workflow-packs/execute"
    assert captured_request["timeout_seconds"] == 7.5
    assert captured_request["max_retries"] == 3
    assert captured_request["backoff_seconds"] == 0.4


def test_support_brief_result_from_payload_maps_action_required_run_without_markdown() -> None:
    result = service._support_brief_result_from_payload(
        {
            "execution": {
                "status": "COMPLETED",
                "result": {"message": "   "},
            },
            "workflow_pack_run": {
                "run_id": "packrun_twr_inspection_support_brief_req_review_001",
                "runtime_state": "COMPLETED",
                "review_state": "AWAITING_REVIEW",
                "allowed_review_actions": ["ACCEPT"],
                "supportability_status": "ACTION_REQUIRED",
                "workflow_authority_owner": "lotus-performance",
            },
        }
    )

    assert result.generation_status == "ACTION_REQUIRED"
    assert result.artifact_markdown is None
    assert result.workflow_pack_run is not None
    assert result.workflow_pack_run.run_id == "packrun_twr_inspection_support_brief_req_review_001"
    assert result.workflow_pack_run.review_pending is True


def test_support_brief_result_from_payload_preserves_run_when_execution_is_malformed() -> None:
    result = service._support_brief_result_from_payload(
        {
            "execution": "not-an-execution-payload",
            "workflow_pack_run": {
                "run_id": "packrun_twr_inspection_support_brief_req_invalid_execution_001",
                "runtime_state": "COMPLETED",
                "review_state": "AWAITING_REVIEW",
                "allowed_review_actions": ["ACCEPT"],
                "supportability_status": "ACTION_REQUIRED",
                "workflow_authority_owner": "lotus-performance",
            },
        }
    )

    assert result.generation_status == "UNAVAILABLE"
    assert result.artifact_markdown is None
    assert result.workflow_pack_run is not None
    assert result.workflow_pack_run.run_id == "packrun_twr_inspection_support_brief_req_invalid_execution_001"


def test_support_brief_result_from_payload_returns_unavailable_without_run_or_markdown() -> None:
    result = service._support_brief_result_from_payload(
        {
            "execution": {
                "status": "COMPLETED",
                "result": {"message": "   "},
            },
            "workflow_pack_run": {"run_id": "   "},
        }
    )

    assert result.generation_status == "UNAVAILABLE"
    assert result.artifact_markdown is None
    assert result.workflow_pack_run is None


def test_completed_support_brief_markdown_trims_completed_message() -> None:
    assert (
        service._completed_support_brief_markdown(
            {
                "status": "COMPLETED",
                "result": {"message": "  # Support brief\n\nReview evidence.  "},
            }
        )
        == "# Support brief\n\nReview evidence."
    )


def test_completed_support_brief_markdown_suppresses_failed_or_blank_message() -> None:
    assert (
        service._completed_support_brief_markdown(
            {
                "status": "FAILED",
                "result": {"message": "# Failed support brief"},
            }
        )
        is None
    )
    assert service._completed_support_brief_markdown({"status": "COMPLETED", "result": {"message": "   "}}) is None
    assert service._completed_support_brief_markdown({"status": "COMPLETED", "result": "not-a-result"}) is None


def test_map_workflow_pack_run_filters_invalid_projection_fields() -> None:
    run = service._map_workflow_pack_run(
        {
            "run_id": "packrun_twr_inspection_support_brief_req_historical_001",
            "runtime_state": "COMPLETED",
            "review_state": "CLOSED",
            "allowed_review_actions": ["VIEW", 3, None],
            "supportability_status": "HISTORICAL",
            "workflow_authority_owner": "lotus-performance",
            "replacement_run_id": "packrun_twr_inspection_support_brief_req_002",
            "findings": [
                {
                    "finding_id": "historical",
                    "severity": "INFO",
                    "summary": "Run was superseded.",
                },
                {"finding_id": "missing-summary", "severity": "INFO"},
                "not-a-finding",
            ],
        }
    )

    assert run is not None
    assert run.allowed_review_actions == ["VIEW"]
    assert run.replacement_run_id == "packrun_twr_inspection_support_brief_req_002"
    assert run.superseded is True
    assert run.review_pending is False
    assert run.current_summary_note == "Run is historical due to replacement lineage."
    assert [finding.finding_id for finding in run.findings] == ["historical"]


def test_build_workflow_pack_request_maps_optional_source_refs() -> None:
    inspection_without_refs = _inspection_response(portfolio_id=None, subject_calculation_id=None)
    request_without_refs = service._build_workflow_pack_request(
        inspection=inspection_without_refs,
        environment="DEVELOPMENT",
    )

    context_without_refs = request_without_refs["task_request"]["context"]  # type: ignore[index]

    assert context_without_refs["source_refs"] == [  # type: ignore[index]
        f"lotus-performance:twr-inspection:{inspection_without_refs.inspection_id}"
    ]

    subject_calculation_id = uuid4()
    inspection_with_lineage = _inspection_response(subject_calculation_id=subject_calculation_id)
    request_with_lineage = service._build_workflow_pack_request(
        inspection=inspection_with_lineage,
        environment="PRODUCTION",
    )

    task_request = request_with_lineage["task_request"]  # type: ignore[index]
    context_with_lineage = task_request["context"]

    assert request_with_lineage["environment"] == "PRODUCTION"
    assert context_with_lineage["source_refs"] == [  # type: ignore[index]
        f"lotus-performance:twr-inspection:{inspection_with_lineage.inspection_id}",
        "lotus-performance:portfolio:PB_SG_GLOBAL_BAL_001",
        f"lotus-performance:lineage:{subject_calculation_id}",
    ]


def test_map_workflow_pack_run_rejects_invalid_run_payloads() -> None:
    assert service._map_workflow_pack_run("not-a-run") is None
    assert service._map_workflow_pack_run({"run_id": "   "}) is None


def test_map_workflow_pack_run_handles_ready_and_default_summary_notes() -> None:
    ready_run = service._map_workflow_pack_run(
        {
            "run_id": "packrun_twr_inspection_support_brief_req_ready_001",
            "runtime_state": "COMPLETED",
            "review_state": "CLOSED",
            "allowed_review_actions": "VIEW",
            "supportability_status": "READY",
            "workflow_authority_owner": "lotus-performance",
            "findings": "not-a-list",
        }
    )
    default_run = service._map_workflow_pack_run(
        {
            "run_id": "packrun_twr_inspection_support_brief_req_unknown_001",
            "runtime_state": "QUEUED",
            "review_state": "NOT_REQUIRED",
            "allowed_review_actions": [],
            "supportability_status": "QUEUED",
            "workflow_authority_owner": "lotus-ai",
        }
    )

    assert ready_run is not None
    assert ready_run.allowed_review_actions == []
    assert ready_run.findings == []
    assert ready_run.current_summary_note == "Run is ready for bounded downstream use."
    assert default_run is not None
    assert default_run.current_summary_note == "Workflow-pack run posture is available from lotus-ai."


def _inspection_response(
    *,
    portfolio_id: str | None = "PB_SG_GLOBAL_BAL_001",
    subject_calculation_id=None,
) -> TWRInspectionResponse:
    return TWRInspectionResponse(
        inspection_id=uuid4(),
        subject_type=TWRInspectionSubjectType.TWR_REQUEST,
        inspection_profile=TWRInspectionProfile.SUPPORT_TRIAGE,
        subject_calculation_id=subject_calculation_id,
        portfolio_id=portfolio_id,
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
