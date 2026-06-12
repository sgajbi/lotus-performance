from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.services.inspection.twr_inspection_service as service
from app.models.inspection_requests import (
    TWRInspectionProfile,
    TWRInspectionRequest,
    TWRInspectionSubjectType,
)
from app.models.inspection_responses import TWRInspectionVerdict
from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.models.twr_requests import TWRAnalyticsRequest
from app.services.execution_stage_names import (
    EXECUTION_STAGE_ARTIFACT_MATERIALIZATION,
    EXECUTION_STAGE_MATH_RECONCILIATION,
    EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT,
    EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT,
    EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION,
    EXECUTION_STAGE_SUBJECT_RESOLUTION,
)
from app.services.inspection.calculation_consistency import CalculationConsistencyCheckResult
from app.services.inspection.subject_resolution import ResolvedTWRInspectionSubject
from common.enums import Frequency, PeriodType


@dataclass
class _FakeExecutionRegistry:
    failed_stages: list[tuple[str, str]]
    completed_stages: list[str]

    def mark_running(self, _inspection_id):
        return None

    def start_stage(self, _inspection_id, _stage_name):
        return None

    def fail_stage(self, _inspection_id, stage_name, message):
        self.failed_stages.append((stage_name, message))

    def complete_stage(self, _inspection_id, stage_name, details=None):
        self.completed_stages.append(stage_name)

    def mark_complete(self, _inspection_id):
        return None


@pytest.fixture()
def fake_registry(monkeypatch) -> _FakeExecutionRegistry:
    registry = _FakeExecutionRegistry(failed_stages=[], completed_stages=[])
    monkeypatch.setattr(service, "execution_registry", registry)
    monkeypatch.setattr(service, "enqueue_twr_inspection_artifacts", lambda **_kwargs: None)
    return registry


def test_run_source_quality_assessment_records_success_outputs(fake_registry, monkeypatch):
    monkeypatch.setattr(
        service,
        "run_source_quality_checks",
        lambda **_kwargs: SimpleNamespace(
            findings=[],
            evidence_summary={"invalid_capital_base_count": 0},
            artifact_payload={"invalid_capital_base_count": 0},
        ),
    )

    outputs = service._run_source_quality_assessment(
        inspection_id=uuid4(),
        performance_request=_build_performance_request(),
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert outputs.findings == []
    assert outputs.completed_check_families == ["source_quality", "economic_plausibility"]
    assert outputs.failed_check_families == []
    assert outputs.evidence_summary == {"invalid_capital_base_count": 0}
    assert outputs.artifact_payloads == {"source_quality_summary.json": '{\n  "invalid_capital_base_count": 0\n}'}
    assert EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT in fake_registry.completed_stages


def test_resolve_inspection_subject_records_subject_resolution_stage(fake_registry, monkeypatch):
    calculation_id = uuid4()
    request = TWRInspectionRequest(
        subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
        subject_calculation_id=calculation_id,
    )
    monkeypatch.setattr(
        service,
        "resolve_twr_inspection_subject",
        lambda _request: ResolvedTWRInspectionSubject(
            subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
            subject_calculation_id=calculation_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            related_execution=None,
            request_payload=None,
        ),
    )

    subject = service._resolve_inspection_subject(request)

    assert subject.subject_calculation_id == calculation_id
    assert subject.portfolio_id == "PB_SG_GLOBAL_BAL_001"
    assert EXECUTION_STAGE_SUBJECT_RESOLUTION in fake_registry.completed_stages


def test_resolve_subject_inspection_inputs_uses_direct_request_payload_without_math_stage(fake_registry, monkeypatch):
    performance_request = _build_performance_request()
    request = TWRInspectionRequest(
        subject_type=TWRInspectionSubjectType.TWR_REQUEST,
        request=_build_twr_request(),
    )
    subject = ResolvedTWRInspectionSubject(
        subject_type=TWRInspectionSubjectType.TWR_REQUEST,
        subject_calculation_id=None,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        related_execution=None,
        request_payload={"request": "payload"},
    )
    monkeypatch.setattr(service, "extract_performance_request_from_payload", lambda _payload: performance_request)

    inputs = service._resolve_subject_inspection_inputs(request=request, subject=subject)

    assert inputs.performance_request is performance_request
    assert inputs.resolved_execution_request is None
    assert inputs.consistency_findings == []
    assert inputs.completed_check_families == []
    assert inputs.failed_check_families == []
    assert EXECUTION_STAGE_MATH_RECONCILIATION not in fake_registry.completed_stages
    assert not fake_registry.failed_stages


def test_run_source_quality_assessment_preserves_failure_outputs(fake_registry, monkeypatch):
    def raise_source_quality_failure(**_kwargs):
        raise RuntimeError("source quality dependency unavailable")

    monkeypatch.setattr(service, "run_source_quality_checks", raise_source_quality_failure)

    outputs = service._run_source_quality_assessment(
        inspection_id=uuid4(),
        performance_request=_build_performance_request(),
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert outputs.completed_check_families == []
    assert outputs.failed_check_families == ["source_quality", "economic_plausibility"]
    assert outputs.evidence_summary == {}
    assert outputs.artifact_payloads == {}
    assert outputs.findings[0].code == "INSPECTION_CHECK_FAMILY_FAILED"
    assert outputs.findings[0].evidence["stage"] == EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT
    assert (EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT, "source quality dependency unavailable") in (
        fake_registry.failed_stages
    )


def test_run_reconciliation_assessment_records_success_outputs(fake_registry, monkeypatch):
    monkeypatch.setattr(
        service,
        "run_reconciliation_checks",
        lambda **_kwargs: SimpleNamespace(
            findings=[],
            evidence_summary={"position_rows_checked": 2},
            artifact_payload={"position_rows_checked": 2},
        ),
    )

    outputs = service._run_reconciliation_assessment(
        inspection_id=uuid4(),
        performance_request=_build_performance_request(),
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert outputs.findings == []
    assert outputs.completed_check_families == ["reconciliation"]
    assert outputs.failed_check_families == []
    assert outputs.evidence_summary == {"position_rows_checked": 2}
    assert outputs.artifact_payloads == {"reconciliation_summary.json": '{\n  "position_rows_checked": 2\n}'}
    assert EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION in fake_registry.completed_stages


def test_run_reconciliation_assessment_preserves_failure_outputs(fake_registry, monkeypatch):
    def raise_reconciliation_failure(**_kwargs):
        raise RuntimeError("position source down")

    monkeypatch.setattr(service, "run_reconciliation_checks", raise_reconciliation_failure)

    outputs = service._run_reconciliation_assessment(
        inspection_id=uuid4(),
        performance_request=_build_performance_request(),
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
    )

    assert outputs.completed_check_families == []
    assert outputs.failed_check_families == ["reconciliation"]
    assert outputs.evidence_summary == {}
    assert outputs.artifact_payloads == {}
    assert outputs.findings[0].code == "INSPECTION_CHECK_FAMILY_FAILED"
    assert outputs.findings[0].evidence["stage"] == EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION
    assert (EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION, "position source down") in fake_registry.failed_stages


def test_run_source_economics_assessment_records_success_outputs(fake_registry, monkeypatch):
    monkeypatch.setattr(
        service,
        "run_source_economics_checks",
        lambda **_kwargs: SimpleNamespace(
            findings=[],
            evidence_summary={"cashflow_rows_checked": 3},
            artifact_payload={"cashflow_rows_checked": 3},
        ),
    )

    outputs = service._run_source_economics_assessment(
        inspection_id=uuid4(),
        performance_request=_build_performance_request(),
        portfolio_id="PB_SG_GLOBAL_BAL_001",
    )

    assert outputs.findings == []
    assert outputs.completed_check_families == ["cashflow_classification"]
    assert outputs.failed_check_families == []
    assert outputs.evidence_summary == {"cashflow_rows_checked": 3}
    assert outputs.artifact_payloads == {"source_economics_summary.json": '{\n  "cashflow_rows_checked": 3\n}'}
    assert EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT in fake_registry.completed_stages


def test_run_source_economics_assessment_preserves_failure_outputs(fake_registry, monkeypatch):
    def raise_source_economics_failure(**_kwargs):
        raise RuntimeError("portfolio source down")

    monkeypatch.setattr(service, "run_source_economics_checks", raise_source_economics_failure)

    outputs = service._run_source_economics_assessment(
        inspection_id=uuid4(),
        performance_request=_build_performance_request(),
        portfolio_id="PB_SG_GLOBAL_BAL_001",
    )

    assert outputs.completed_check_families == []
    assert outputs.failed_check_families == ["cashflow_classification"]
    assert outputs.evidence_summary == {}
    assert outputs.artifact_payloads == {}
    assert outputs.findings[0].code == "INSPECTION_CHECK_FAMILY_FAILED"
    assert outputs.findings[0].evidence["stage"] == EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT
    assert (EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT, "portfolio source down") in fake_registry.failed_stages


def test_twr_inspection_preserves_runtime_finding_when_only_check_family_fails(fake_registry, monkeypatch):
    def raise_source_quality_failure(**_kwargs):
        raise RuntimeError("source quality dependency unavailable")

    monkeypatch.setattr(service, "run_source_quality_checks", raise_source_quality_failure)

    response = service.run_twr_inspection(
        TWRInspectionRequest(
            subject_type=TWRInspectionSubjectType.TWR_REQUEST,
            inspection_profile=TWRInspectionProfile.CANONICAL_VALIDATION,
            request=_build_twr_request(),
        )
    )

    assert response.verdict == TWRInspectionVerdict.INSPECTION_FAILED
    assert response.check_coverage.completed_check_families == []
    assert response.evidence_summary["failed_check_families"] == ["source_quality", "economic_plausibility"]
    assert (EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT, "source quality dependency unavailable") in (
        fake_registry.failed_stages
    )

    finding = response.findings[0]
    assert finding.code == "INSPECTION_CHECK_FAMILY_FAILED"
    assert finding.category == "inspection_runtime"
    assert finding.evidence["check_families"] == ["source_quality", "economic_plausibility"]
    assert finding.evidence["stage"] == EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT
    assert finding.evidence["error_type"] == "RuntimeError"


def test_twr_inspection_keeps_completed_evidence_when_later_check_family_fails(fake_registry, monkeypatch):
    calculation_id = uuid4()
    performance_request = _build_performance_request()

    monkeypatch.setattr(
        service,
        "resolve_twr_inspection_subject",
        lambda _request: ResolvedTWRInspectionSubject(
            subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
            subject_calculation_id=calculation_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            related_execution=None,
            request_payload=None,
        ),
    )
    monkeypatch.setattr(
        service,
        "load_existing_twr_calculation_artifacts",
        lambda _calculation_id: SimpleNamespace(request_payload={}, response_model=object()),
    )
    monkeypatch.setattr(service, "extract_resolved_execution_request_from_payload", lambda _payload: None)
    monkeypatch.setattr(service, "extract_performance_request_from_payload", lambda _payload: performance_request)
    monkeypatch.setattr(
        service,
        "run_twr_calculation_consistency_checks",
        lambda _response: CalculationConsistencyCheckResult(
            findings=[],
            evidence_summary={
                "period_count": 1,
                "linked_blocks_checked": 1,
                "relative_rows_checked": 0,
                "consistency_findings": 0,
            },
        ),
    )
    monkeypatch.setattr(service, "_scope_request_to_response_master_window", lambda request, _response: request)
    monkeypatch.setattr(
        service,
        "_scope_resolved_request_to_response_master_window",
        lambda request, _response: request,
    )

    def raise_source_quality_failure(**_kwargs):
        raise RuntimeError("source quality source timed out")

    monkeypatch.setattr(service, "run_source_quality_checks", raise_source_quality_failure)

    response = service.run_twr_inspection(
        TWRInspectionRequest(
            subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
            subject_calculation_id=calculation_id,
        )
    )

    assert response.verdict == TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS
    assert response.check_coverage.completed_check_families == ["calculation_consistency"]
    assert response.evidence_summary["period_count"] == 1
    assert response.evidence_summary["failed_check_families"] == ["source_quality", "economic_plausibility"]
    assert EXECUTION_STAGE_MATH_RECONCILIATION in fake_registry.completed_stages
    assert (EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT, "source quality source timed out") in fake_registry.failed_stages
    assert [finding.code for finding in response.findings] == ["INSPECTION_CHECK_FAMILY_FAILED"]


def test_twr_inspection_records_math_failure_for_missing_existing_artifacts(fake_registry, monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(
        service,
        "resolve_twr_inspection_subject",
        lambda _request: ResolvedTWRInspectionSubject(
            subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
            subject_calculation_id=calculation_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            related_execution=None,
            request_payload=None,
        ),
    )
    monkeypatch.setattr(
        service,
        "load_existing_twr_calculation_artifacts",
        lambda _calculation_id: (_ for _ in ()).throw(KeyError("missing response")),
    )

    response = service.run_twr_inspection(
        TWRInspectionRequest(
            subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
            subject_calculation_id=calculation_id,
        )
    )

    assert response.verdict == TWRInspectionVerdict.INSPECTION_FAILED
    assert response.evidence_summary["failed_check_families"] == ["calculation_consistency"]
    assert (EXECUTION_STAGE_MATH_RECONCILIATION, "'missing response'") in fake_registry.failed_stages


def test_twr_inspection_preserves_source_quality_when_stateful_reconciliation_checks_fail(
    fake_registry,
    monkeypatch,
):
    calculation_id = uuid4()
    performance_request = _build_performance_request()
    resolved_request = SimpleNamespace(portfolio=performance_request)

    monkeypatch.setattr(
        service,
        "resolve_twr_inspection_subject",
        lambda _request: ResolvedTWRInspectionSubject(
            subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
            subject_calculation_id=calculation_id,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            related_execution=None,
            request_payload=None,
        ),
    )
    monkeypatch.setattr(
        service,
        "load_existing_twr_calculation_artifacts",
        lambda _calculation_id: SimpleNamespace(request_payload={}, response_model=object()),
    )
    monkeypatch.setattr(service, "extract_resolved_execution_request_from_payload", lambda _payload: resolved_request)
    monkeypatch.setattr(service, "extract_performance_request_from_payload", lambda _payload: performance_request)
    monkeypatch.setattr(
        service,
        "run_twr_calculation_consistency_checks",
        lambda _response: CalculationConsistencyCheckResult(findings=[], evidence_summary={"period_count": 1}),
    )
    monkeypatch.setattr(service, "_scope_request_to_response_master_window", lambda request, _response: request)
    monkeypatch.setattr(
        service, "_scope_resolved_request_to_response_master_window", lambda request, _response: request
    )
    monkeypatch.setattr(
        service,
        "run_source_quality_checks",
        lambda **_kwargs: SimpleNamespace(
            findings=[], evidence_summary={"invalid_capital_base_count": 0}, artifact_payload={}
        ),
    )
    monkeypatch.setattr(
        service,
        "run_reconciliation_checks",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("position source down")),
    )
    monkeypatch.setattr(
        service,
        "run_source_economics_checks",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("portfolio source down")),
    )

    response = service.run_twr_inspection(
        TWRInspectionRequest(
            subject_type=TWRInspectionSubjectType.TWR_CALCULATION,
            subject_calculation_id=calculation_id,
        )
    )

    assert response.verdict == TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS
    assert response.evidence_summary["failed_check_families"] == ["reconciliation", "cashflow_classification"]
    assert (EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION, "position source down") in fake_registry.failed_stages
    assert (EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT, "portfolio source down") in fake_registry.failed_stages


def test_twr_inspection_marks_artifact_materialization_failure(fake_registry, monkeypatch):
    monkeypatch.setattr(
        service,
        "run_source_quality_checks",
        lambda **_kwargs: SimpleNamespace(findings=[], evidence_summary={}, artifact_payload={}),
    )
    monkeypatch.setattr(
        service,
        "enqueue_twr_inspection_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("artifact store offline")),
    )

    with pytest.raises(RuntimeError, match="artifact store offline"):
        service.run_twr_inspection(
            TWRInspectionRequest(
                subject_type=TWRInspectionSubjectType.TWR_REQUEST,
                request=_build_twr_request(),
            )
        )

    assert (EXECUTION_STAGE_ARTIFACT_MATERIALIZATION, "artifact store offline") in fake_registry.failed_stages


def test_twr_inspection_reports_no_check_family_when_subject_has_no_inspectable_payload(fake_registry, monkeypatch):
    monkeypatch.setattr(
        service,
        "resolve_twr_inspection_subject",
        lambda _request: ResolvedTWRInspectionSubject(
            subject_type=TWRInspectionSubjectType.TWR_REQUEST,
            subject_calculation_id=None,
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            related_execution=None,
            request_payload=None,
        ),
    )

    response = service.run_twr_inspection(
        TWRInspectionRequest(
            subject_type=TWRInspectionSubjectType.TWR_REQUEST,
            request=_build_twr_request(),
        )
    )

    assert response.verdict == TWRInspectionVerdict.SUPPORTABLE_WITH_WARNINGS
    assert response.check_coverage.completed_check_families == []
    assert response.findings[0].code == "INSPECTION_NO_CHECK_FAMILY_EXECUTED"
    assert "runtime skeleton" not in response.findings[0].summary


def test_build_twr_inspection_response_adds_no_check_finding_and_support_brief(monkeypatch):
    monkeypatch.setattr(
        service,
        "generate_twr_inspection_support_brief",
        lambda inspection: SimpleNamespace(
            generation_status="generated",
            workflow_pack_run=None,
            artifact_markdown=f"# Support brief for {inspection.inspection_id}",
        ),
    )
    request = TWRInspectionRequest(
        subject_type=TWRInspectionSubjectType.TWR_REQUEST,
        request=_build_twr_request(),
    )

    synthesis = service._build_twr_inspection_response(
        request=request,
        subject_calculation_id=None,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        consistency_findings=[],
        source_quality_findings=[],
        reconciliation_findings=[],
        source_economics_findings=[],
        completed_check_families=[],
        failed_check_families=[],
        evidence_summary={"artifact_queue_enabled": True},
        artifact_payloads={},
    )

    assert synthesis.support_brief_generation_status == "generated"
    assert synthesis.response.findings[0].code == "INSPECTION_NO_CHECK_FAMILY_EXECUTED"
    assert synthesis.response.evidence_summary["support_brief_generation_status"] == "generated"
    assert synthesis.artifact_payloads["support_brief.md"].startswith("# Support brief")
    assert "support_brief.md" in synthesis.response.artifacts


def test_build_inspection_findings_context_adds_no_check_finding_and_failed_family_evidence():
    evidence_summary = {"artifact_queue_enabled": True}

    context = service._build_inspection_findings_context(
        consistency_findings=[],
        source_quality_findings=[],
        reconciliation_findings=[],
        source_economics_findings=[],
        completed_check_families=[],
        failed_check_families=["source_quality"],
        evidence_summary=evidence_summary,
    )

    assert context.findings[0].code == "INSPECTION_NO_CHECK_FAMILY_EXECUTED"
    assert context.pending_check_families == [
        "calculation_consistency",
        "source_quality",
        "economic_plausibility",
        "reconciliation",
        "cashflow_classification",
    ]
    assert context.evidence_summary["failed_check_families"] == ["source_quality"]
    assert "failed_check_families" not in evidence_summary


def test_twr_inspection_verdict_and_window_helpers_cover_clean_and_unscoped_paths():
    assert (
        service._synthesize_verdict(
            findings=[],
            completed_check_families=["source_quality"],
            failed_check_families=[],
            pending_check_families=[],
        )
        == TWRInspectionVerdict.SUPPORTABLE
    )
    performance_request = _build_performance_request()
    response_without_window = SimpleNamespace(meta=SimpleNamespace(periods={}))
    assert (
        service._scope_request_to_response_master_window(performance_request, response_without_window)
        is performance_request
    )
    assert service._scope_request_to_response_master_window(None, response_without_window) is None
    assert service._response_master_window(SimpleNamespace(meta=SimpleNamespace(periods={"master_start": "bad"}))) == (
        None,
        None,
    )


def test_build_twr_inspection_artifact_links_keeps_required_and_available_artifacts():
    inspection_id = uuid4()
    links = service._build_twr_inspection_artifact_links(
        inspection_id=inspection_id,
        artifact_payloads={
            "source_quality_summary.json": "{}",
            "source_economics_summary.json": "{}",
            "support_brief.md": "brief",
        },
    )

    assert links == {
        "inspection_summary.json": f"/performance/inspections/{inspection_id}/artifacts/inspection_summary.json",
        "findings.json": f"/performance/inspections/{inspection_id}/artifacts/findings.json",
        "source_quality_summary.json": (
            f"/performance/inspections/{inspection_id}/artifacts/source_quality_summary.json"
        ),
        "source_economics_summary.json": (
            f"/performance/inspections/{inspection_id}/artifacts/source_economics_summary.json"
        ),
        "support_brief.md": f"/performance/inspections/{inspection_id}/artifacts/support_brief.md",
    }
    assert "reconciliation_summary.json" not in links


def test_build_twr_inspection_artifact_links_omits_unavailable_optional_artifacts():
    inspection_id = uuid4()
    links = service._build_twr_inspection_artifact_links(inspection_id=inspection_id, artifact_payloads={})

    assert links == {
        "inspection_summary.json": f"/performance/inspections/{inspection_id}/artifacts/inspection_summary.json",
        "findings.json": f"/performance/inspections/{inspection_id}/artifacts/findings.json",
    }


def _build_twr_request() -> TWRAnalyticsRequest:
    return TWRAnalyticsRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 1, 1),
        metric_basis="NET",
        report_end_date=date(2026, 1, 2),
        analyses=[Analysis(period=PeriodType.YTD, frequencies=[Frequency.DAILY])],
        valuation_points=_valuation_points(),
    )


def _build_performance_request() -> PerformanceRequest:
    return PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 1, 1),
        metric_basis="NET",
        report_end_date=date(2026, 1, 2),
        analyses=[Analysis(period=PeriodType.YTD, frequencies=[Frequency.DAILY])],
        valuation_points=_valuation_points(),
    )


def _valuation_points() -> list[DailyInputData]:
    return [
        DailyInputData(
            perf_date=date(2026, 1, 2),
            begin_mv=1000.0,
            end_mv=1005.0,
        )
    ]
