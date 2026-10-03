from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.models.source_corrections import (
    RetainedCalculationResult,
    SourceCorrectionImpact,
    SourceCorrectionRequest,
    SourceCorrectionResponse,
)
from app.observability import record_source_correction, tenant_id_var
from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_ATTRIBUTION,
    ANALYTICS_WORKFLOW_BENCHMARK,
    ANALYTICS_WORKFLOW_CONTRIBUTION,
    ANALYTICS_WORKFLOW_RETURNS_SERIES,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)
from app.services.compute_job_store import (
    ComputeJobRegistrationStatus,
    ComputeJobStatus,
    compute_job_store,
)
from app.services.core_tenant_authority import admitted_tenant_authority, require_tenant_authority
from app.services.execution_registry import ExecutionRegistrationStatus, ExecutionStatus, execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_SUBMISSION
from app.services.source_correction_store import (
    SourceCorrectionRecord,
    SourceCorrectionRegistrationStatus,
    source_correction_store,
)
from core.errors import APIConflictError, APINotFoundError

_SUPPORTED_RECALCULATION_ANALYTICS = frozenset(
    {
        ANALYTICS_WORKFLOW_ATTRIBUTION,
        ANALYTICS_WORKFLOW_BENCHMARK,
        ANALYTICS_WORKFLOW_CONTRIBUTION,
        ANALYTICS_WORKFLOW_RETURNS_SERIES,
        ANALYTICS_WORKFLOW_TWR,
        ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
    }
)
_COVERAGE_LIMITS = [
    "Performance consumes a versioned correction contract; lotus-core owns correction command admission.",
    "Only retained stateful calculations with overlapping requested windows are recalculated.",
    "FX correction impact requires the corrected pair to appear explicitly in the retained request.",
]


def submit_source_correction(request: SourceCorrectionRequest) -> SourceCorrectionResponse:
    tenant_id = _required_tenant_id()
    latest = source_correction_store.latest_for_scope(
        tenant_id=tenant_id,
        source_product=request.source_product,
        target_type=request.target_type,
        target_id=request.target_id,
    )
    coalesced_impacts, coalesced_start, coalesced_end = _coalescing_context(
        latest=latest,
        request=request,
        tenant_id=tenant_id,
    )
    submitted_payload = request.model_dump(mode="json")
    fingerprint = _payload_fingerprint(submitted_payload)
    payload = dict(submitted_payload)
    payload["coalesced_effective_start_date"] = coalesced_start.isoformat()
    payload["coalesced_effective_end_date"] = coalesced_end.isoformat()
    registration = source_correction_store.register(
        tenant_id=tenant_id,
        correction_id=request.correction_id,
        request_fingerprint=fingerprint,
        request_payload=payload,
    )
    _reject_registration_conflict(registration.status, request=request)

    record = registration.record
    replayed = registration.status == SourceCorrectionRegistrationStatus.REPLAY
    if replayed and record.state in {"no_effect", "complete", "partial_failure", "superseded", "cancelled"}:
        response = _response_for_record(record, replayed=True)
        record_source_correction(
            source_product=request.source_product,
            target_type=request.target_type,
            outcome="replay",
        )
        return response
    if not record.impacts and source_correction_store.has_newer_scope_event(record):
        source_correction_store.update(
            tenant_id=tenant_id,
            correction_id=request.correction_id,
            state="superseded",
            impacts=[],
        )
        response = _response_for_record(
            source_correction_store.get(tenant_id=tenant_id, correction_id=request.correction_id),
            replayed=replayed,
        )
        record_source_correction(
            source_product=request.source_product,
            target_type=request.target_type,
            outcome="superseded",
        )
        return response

    _ensure_recalculation_schedule(
        record=record,
        request=request,
        tenant_id=tenant_id,
        existing_impacts=coalesced_impacts,
    )
    response = get_source_correction(request.correction_id, replayed=replayed)
    record_source_correction(
        source_product=request.source_product,
        target_type=request.target_type,
        outcome="replay" if replayed else "no_effect" if response.state == "no_effect" else "accepted",
    )
    return response


def _reject_registration_conflict(
    status: SourceCorrectionRegistrationStatus,
    *,
    request: SourceCorrectionRequest,
) -> None:
    if status not in {
        SourceCorrectionRegistrationStatus.CONFLICT,
        SourceCorrectionRegistrationStatus.REVISION_CONFLICT,
    }:
        return
    record_source_correction(
        source_product=request.source_product,
        target_type=request.target_type,
        outcome="conflict",
    )
    if status == SourceCorrectionRegistrationStatus.REVISION_CONFLICT:
        raise APIConflictError(
            "supersedes_source_revision does not identify the latest admitted source revision.",
            error_code="SOURCE_CORRECTION_REVISION_CONFLICT",
        )
    raise APIConflictError(
        "This correction_id already identifies a different source correction for the admitted tenant.",
        error_code="SOURCE_CORRECTION_ID_CONFLICT",
    )


def _ensure_recalculation_schedule(
    *,
    record: SourceCorrectionRecord,
    request: SourceCorrectionRequest,
    tenant_id: str,
    existing_impacts: list[dict[str, Any]],
) -> None:
    if record.impacts:
        return
    impacts = _schedule_impacted_calculations(
        request=request,
        tenant_id=tenant_id,
        existing_impacts=existing_impacts,
    )
    source_correction_store.update(
        tenant_id=tenant_id,
        correction_id=request.correction_id,
        state="recalculation_pending" if impacts else "no_effect",
        impacts=impacts,
    )


def get_source_correction(correction_id: str, *, replayed: bool = False) -> SourceCorrectionResponse:
    tenant_id = _required_tenant_id()
    record = source_correction_store.get(tenant_id=tenant_id, correction_id=correction_id)
    if record is None:
        raise APINotFoundError("Source correction not found.", error_code="SOURCE_CORRECTION_NOT_FOUND")
    reconciled = _reconcile_record(record)
    return _response_for_record(reconciled, replayed=replayed)


def cancel_source_correction(correction_id: str) -> SourceCorrectionResponse:
    tenant_id = _required_tenant_id()
    record = source_correction_store.get(tenant_id=tenant_id, correction_id=correction_id)
    if record is None:
        raise APINotFoundError("Source correction not found.", error_code="SOURCE_CORRECTION_NOT_FOUND")
    if record.state in {"complete", "partial_failure", "superseded", "no_effect", "cancelled"}:
        return _response_for_record(record, replayed=True)

    corrected_ids = [UUID(str(stored["corrected_calculation_id"])) for stored in record.impacts]
    if not compute_job_store.cancel_pending_jobs(
        corrected_ids,
        tenant_id=tenant_id,
        reason="Source correction recalculation cancelled before worker acquisition.",
    ):
        raise APIConflictError(
            "Source correction recalculation is already running and cannot be cancelled by this endpoint.",
            error_code="SOURCE_CORRECTION_CANCELLATION_CONFLICT",
        )

    for corrected_id in corrected_ids:
        execution_registry.mark_failed(corrected_id, "Source correction recalculation cancelled.")
    source_correction_store.cancel_impacts(
        tenant_id=tenant_id,
        corrected_calculation_ids={str(calculation_id) for calculation_id in corrected_ids},
        failure_code="SOURCE_CORRECTION_CANCELLED",
    )
    refreshed = source_correction_store.get(tenant_id=tenant_id, correction_id=correction_id)
    response = _response_for_record(refreshed, replayed=False)
    record_source_correction(
        source_product=record.source_product,
        target_type=record.target_type,
        outcome="cancelled",
    )
    return response


def get_retained_calculation_result(calculation_id: UUID) -> RetainedCalculationResult:
    tenant_id = _required_tenant_id()
    execution = execution_registry.get_execution_for_tenant(calculation_id, tenant_id=tenant_id)
    if execution is None or execution.response_payload is None:
        raise APINotFoundError("Retained calculation result not found.", error_code="RETAINED_RESULT_NOT_FOUND")
    return RetainedCalculationResult(
        calculation_id=calculation_id,
        analytics_type=execution.analytics_type,
        calculation_hash=execution.calculation_hash,
        input_fingerprint=execution.input_fingerprint,
        response=execution.response_payload,
    )


def _required_tenant_id() -> str:
    authority = require_tenant_authority(
        admitted_tenant_authority(tenant_id_var.get()),
        operation="performance source correction",
    )
    return authority.tenant_id


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _record_observed_at(record: SourceCorrectionRecord) -> datetime:
    return datetime.fromisoformat(record.observed_at_utc.replace("Z", "+00:00"))


def _schedule_impacted_calculations(
    *,
    request: SourceCorrectionRequest,
    tenant_id: str,
    existing_impacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    direct_target = request.target_id if request.source_product == "portfolio_timeseries" else None
    candidates = execution_registry.list_completed_executions_for_tenant_target(
        tenant_id=tenant_id,
        target_id=direct_target,
    )
    impacts = [dict(item) for item in existing_impacts]
    existing_original_ids = {str(item["original_calculation_id"]) for item in impacts}
    for execution in candidates:
        if not _is_impacted(execution, request):
            continue
        if str(execution.calculation_id) in existing_original_ids:
            continue
        impacts.append(_schedule_recalculation(execution=execution, request=request, tenant_id=tenant_id))
    return impacts


def _schedule_recalculation(*, execution: Any, request: SourceCorrectionRequest, tenant_id: str) -> dict[str, Any]:
    replacement_id = uuid5(
        NAMESPACE_URL,
        f"lotus-performance:{tenant_id}:{request.correction_id}:{execution.calculation_id}",
    )
    retained_payload = execution.request_payload or {}
    replacement_payload = dict(retained_payload.get("source_request", retained_payload))
    replacement_payload["calculation_id"] = str(replacement_id)
    registration = execution_registry.register_execution(
        calculation_id=replacement_id,
        tenant_id=tenant_id,
        analytics_type=execution.analytics_type,
        portfolio_id=execution.portfolio_id,
        execution_mode="async",
        requested_window=execution.requested_window,
        input_fingerprint=None,
        calculation_hash=None,
        request_payload=replacement_payload,
    )
    if registration.status == ExecutionRegistrationStatus.CONFLICT:
        raise APIConflictError(
            "Correction recalculation identity conflicts with an existing execution.",
            error_code="SOURCE_CORRECTION_RECALCULATION_CONFLICT",
        )
    created = registration.status == ExecutionRegistrationStatus.CREATED
    if created:
        execution_registry.start_stage(replacement_id, EXECUTION_STAGE_SUBMISSION)
    _register_recalculation_job(
        execution=execution,
        replacement_id=replacement_id,
        replacement_payload=replacement_payload,
        tenant_id=tenant_id,
        created=created,
    )
    if created:
        _complete_recalculation_submission(execution, replacement_id, request)
    return _pending_impact(execution=execution, replacement_id=replacement_id)


def _register_recalculation_job(
    *,
    execution: Any,
    replacement_id: UUID,
    replacement_payload: dict[str, Any],
    tenant_id: str,
    created: bool,
) -> None:
    registration = compute_job_store.register_job(
        calculation_id=replacement_id,
        analytics_type=execution.analytics_type,
        tenant_id=tenant_id,
        request_payload=replacement_payload,
    )
    if registration.status != ComputeJobRegistrationStatus.CONFLICT:
        return
    if created:
        execution_registry.delete_execution(replacement_id)
    raise APIConflictError(
        "Correction recalculation job conflicts with an existing durable job.",
        error_code="SOURCE_CORRECTION_RECALCULATION_CONFLICT",
    )


def _complete_recalculation_submission(execution: Any, replacement_id: UUID, request: SourceCorrectionRequest) -> None:
    execution_registry.complete_stage(
        replacement_id,
        EXECUTION_STAGE_SUBMISSION,
        details={
            "offload_reason": "source_correction_recalculation",
            "source_correction_id": request.correction_id,
            "source_revision": request.source_revision,
            "supersedes_calculation_id": str(execution.calculation_id),
        },
    )


def _pending_impact(*, execution: Any, replacement_id: UUID) -> dict[str, Any]:
    return {
        "original_calculation_id": str(execution.calculation_id),
        "corrected_calculation_id": str(replacement_id),
        "analytics_type": execution.analytics_type,
        "state": "pending",
        "original_result_path": f"/performance/executions/{execution.calculation_id}/retained-result",
        "corrected_result_path": f"/performance/executions/{replacement_id}/retained-result",
        "original_calculation_hash": execution.calculation_hash,
        "corrected_calculation_hash": None,
        "original_response_fingerprint": _economic_response_fingerprint(execution.response_payload),
        "corrected_response_fingerprint": None,
        "output_changed": None,
        "failure_code": None,
    }


def _coalescing_context(
    *,
    latest: SourceCorrectionRecord | None,
    request: SourceCorrectionRequest,
    tenant_id: str,
) -> tuple[list[dict[str, Any]], date, date]:
    if latest is not None and latest.correction_id == request.correction_id:
        return (
            [],
            date.fromisoformat(str(latest.request_payload["coalesced_effective_start_date"])),
            date.fromisoformat(str(latest.request_payload["coalesced_effective_end_date"])),
        )
    if latest is None or latest.state != "recalculation_pending":
        return [], request.effective_start_date, request.effective_end_date
    latest_start = date.fromisoformat(str(latest.request_payload["coalesced_effective_start_date"]))
    latest_end = date.fromisoformat(str(latest.request_payload["coalesced_effective_end_date"]))
    if latest_end < request.effective_start_date or request.effective_end_date < latest_start:
        return [], request.effective_start_date, request.effective_end_date
    if not _all_impacts_pending(latest.impacts, tenant_id=tenant_id):
        return [], request.effective_start_date, request.effective_end_date
    return (
        latest.impacts,
        min(latest_start, request.effective_start_date),
        max(latest_end, request.effective_end_date),
    )


def _all_impacts_pending(impacts: list[dict[str, Any]], *, tenant_id: str) -> bool:
    for impact in impacts:
        job = compute_job_store.get_job_for_tenant(
            UUID(str(impact["corrected_calculation_id"])),
            tenant_id=tenant_id,
        )
        if job is None or job.job_status != ComputeJobStatus.PENDING:
            return False
    return True


def _is_impacted(execution: Any, request: SourceCorrectionRequest) -> bool:
    payload = execution.request_payload or {}
    if execution.analytics_type not in _SUPPORTED_RECALCULATION_ANALYTICS or not _uses_stateful_input(payload):
        return False
    if not _source_target_matches([payload, execution.requested_window], request):
        return False
    window_start, window_end = _execution_window(execution.requested_window)
    return window_start <= request.effective_end_date and window_end >= request.effective_start_date


def _uses_stateful_input(payload: dict[str, Any]) -> bool:
    source_request = payload.get("source_request", payload)
    return isinstance(source_request, dict) and str(source_request.get("input_mode", "")).lower() == "stateful"


def _source_target_matches(payload: Any, request: SourceCorrectionRequest) -> bool:
    if request.source_product == "benchmark_returns":
        return _payload_contains_value(payload, {"benchmark_id"}, request.target_id)
    if request.source_product != "fx_rates":
        return True
    pair_currencies = {value for value in request.target_id.replace("-", "/").split("/") if value}
    request_currencies = _payload_values(
        payload,
        {"currency", "report_ccy", "reporting_currency", "source_currency", "target_currency"},
    )
    return len(pair_currencies) == 2 and pair_currencies.issubset(request_currencies)


def _payload_contains_value(payload: Any, keys: set[str], expected: str) -> bool:
    if isinstance(payload, dict):
        return any(
            (key in keys and str(value) == expected) or _payload_contains_value(value, keys, expected)
            for key, value in payload.items()
        )
    if isinstance(payload, list):
        return any(_payload_contains_value(item, keys, expected) for item in payload)
    return False


def _payload_values(payload: Any, keys: set[str]) -> set[str]:
    if isinstance(payload, dict):
        values = {str(value) for key, value in payload.items() if key in keys and isinstance(value, str)}
        for nested_value in payload.values():
            values.update(_payload_values(nested_value, keys))
        return values
    if isinstance(payload, list):
        list_values: set[str] = set()
        for item in payload:
            list_values.update(_payload_values(item, keys))
        return list_values
    return set()


def _execution_window(requested_window: dict[str, Any]) -> tuple[date, date]:
    start = _first_date(
        requested_window,
        "start_date",
        "report_start_date",
        "window_start_date",
        "from_date",
        "performance_start_date",
        "benchmark_start_date",
    )
    end = _first_date(
        requested_window,
        "end_date",
        "report_end_date",
        "window_end_date",
        "to_date",
        "as_of",
        "as_of_date",
    )
    return start or date.min, end or date.max


def _first_date(payload: dict[str, Any], *keys: str) -> date | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _reconcile_record(record: SourceCorrectionRecord) -> SourceCorrectionRecord:
    if not record.impacts or record.state in {"superseded", "cancelled"}:
        return record
    impacts = [_reconcile_impact(stored, tenant_id=record.tenant_id) for stored in record.impacts]
    state = _reconciled_state(impacts)
    if state != record.state or impacts != record.impacts:
        source_correction_store.update(
            tenant_id=record.tenant_id,
            correction_id=record.correction_id,
            state=state,
            impacts=impacts,
        )
        refreshed = source_correction_store.get(tenant_id=record.tenant_id, correction_id=record.correction_id)
        if refreshed is not None:
            return refreshed
    return record


def _reconcile_impact(stored: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    impact = dict(stored)
    calculation_id = UUID(str(impact["corrected_calculation_id"]))
    job = compute_job_store.get_job_for_tenant(calculation_id, tenant_id=tenant_id)
    execution = execution_registry.get_execution_for_tenant(calculation_id, tenant_id=tenant_id)
    if job is None or execution is None:
        impact.update(state="failed", failure_code="DURABLE_RECALCULATION_MISSING")
        return impact
    if _recalculation_is_complete(job, execution):
        return _completed_impact(impact, execution=execution, tenant_id=tenant_id)
    if _recalculation_failed(job, execution):
        impact.update(state="failed", failure_code=job.error_type or "RECALCULATION_FAILED")
        return impact
    impact["state"] = "running" if job.job_status in {ComputeJobStatus.LEASED, ComputeJobStatus.RUNNING} else "pending"
    return impact


def _recalculation_is_complete(job: Any, execution: Any) -> bool:
    return job.job_status == ComputeJobStatus.COMPLETE and execution.status == ExecutionStatus.COMPLETE


def _recalculation_failed(job: Any, execution: Any) -> bool:
    return job.job_status == ComputeJobStatus.FAILED or execution.status == ExecutionStatus.FAILED


def _completed_impact(impact: dict[str, Any], *, execution: Any, tenant_id: str) -> dict[str, Any]:
    original = execution_registry.get_execution_for_tenant(
        UUID(str(impact["original_calculation_id"])),
        tenant_id=tenant_id,
    )
    original_fingerprint = _economic_response_fingerprint(original.response_payload) if original is not None else None
    corrected_fingerprint = _economic_response_fingerprint(execution.response_payload)
    impact.update(
        state="complete",
        failure_code=None,
        original_calculation_hash=original.calculation_hash if original is not None else None,
        corrected_calculation_hash=execution.calculation_hash,
        original_response_fingerprint=original_fingerprint,
        corrected_response_fingerprint=corrected_fingerprint,
        output_changed=_fingerprints_changed(original_fingerprint, corrected_fingerprint),
    )
    return impact


def _fingerprints_changed(original: str | None, corrected: str | None) -> bool | None:
    if original is None or corrected is None:
        return None
    return original != corrected


def _reconciled_state(impacts: list[dict[str, Any]]) -> str:
    states = {str(item["state"]) for item in impacts}
    if states == {"complete"}:
        return "complete"
    if "failed" in states:
        return "partial_failure"
    return "recalculation_pending"


def _response_for_record(record: SourceCorrectionRecord | None, *, replayed: bool) -> SourceCorrectionResponse:
    if record is None:
        raise APINotFoundError("Source correction not found.", error_code="SOURCE_CORRECTION_NOT_FOUND")
    payload = record.request_payload
    impacts = [SourceCorrectionImpact.model_validate(item) for item in record.impacts]
    return SourceCorrectionResponse(
        correction_id=record.correction_id,
        source_product=record.source_product,
        source_revision=record.source_revision,
        target_type=record.target_type,
        target_id=record.target_id,
        effective_start_date=payload["effective_start_date"],
        effective_end_date=payload["effective_end_date"],
        coalesced_effective_start_date=payload.get(
            "coalesced_effective_start_date",
            payload["effective_start_date"],
        ),
        coalesced_effective_end_date=payload.get(
            "coalesced_effective_end_date",
            payload["effective_end_date"],
        ),
        observed_at_utc=record.observed_at_utc,
        state=record.state,
        replayed=replayed,
        affected_calculation_count=len(impacts),
        impacts=impacts,
        current_result_paths=[impact.corrected_result_path for impact in impacts if impact.state == "complete"],
        coverage_limits=list(_COVERAGE_LIMITS),
    )


def _economic_response_fingerprint(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    transient_fields = {
        "calculation_id",
        "correlation_id",
        "request_id",
        "trace_id",
        "generated_at",
        "generated_at_utc",
    }

    def _without_transient(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _without_transient(item) for key, item in value.items() if key not in transient_fields}
        if isinstance(value, list):
            return [_without_transient(item) for item in value]
        return value

    return _payload_fingerprint(_without_transient(payload))
