from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.core.config import get_settings
from app.models.requests import PerformanceRequest
from app.models.responses import PerformanceResponse
from app.models.twr_requests import TWRAnalyticsRequest, TWRResolvedExecutionRequest
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.durable_store_json import load_json_object_or_none, read_json_file
from app.services.lineage_metadata_store import lineage_metadata_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExistingTWRCalculationArtifacts:
    response_model: PerformanceResponse
    request_payload: dict | None


_REQUEST_PAYLOAD_WAIT_SECONDS = 10.0
_REQUEST_PAYLOAD_POLL_INTERVAL_SECONDS = 0.5


def load_existing_twr_calculation_artifacts(calculation_id: UUID) -> ExistingTWRCalculationArtifacts:
    lineage_artifacts = _existing_artifacts_from_lineage_payload(
        calculation_id=calculation_id,
        payload=lineage_metadata_store.get_payload(calculation_id),
    )
    if lineage_artifacts is not None:
        return lineage_artifacts

    async_result = async_result_store.get_result(calculation_id)
    if async_result is not None and async_result.response_payload is not None:
        return ExistingTWRCalculationArtifacts(
            response_model=PerformanceResponse.model_validate(async_result.response_payload),
            request_payload=_load_request_payload(
                calculation_id,
                wait_seconds=_REQUEST_PAYLOAD_WAIT_SECONDS,
            ),
        )

    lineage_directory = Path(get_settings().LINEAGE_STORAGE_PATH) / str(calculation_id)
    response_path = lineage_directory / "response.json"
    request_path = lineage_directory / "request.json"
    if response_path.exists():
        response_payload = read_json_file(response_path)
        request_payload = None
        if request_path.exists():
            request_payload = read_json_file(request_path)
        return ExistingTWRCalculationArtifacts(
            response_model=PerformanceResponse.model_validate(response_payload),
            request_payload=request_payload,
        )

    raise KeyError(f"TWR response artifacts not found for calculation: {calculation_id}")


def _existing_artifacts_from_lineage_payload(
    *,
    calculation_id: UUID,
    payload: Any | None,
) -> ExistingTWRCalculationArtifacts | None:
    if payload is None:
        return None
    response_payload = _load_json_object(
        payload.response_json,
        calculation_id=calculation_id,
        payload_name="lineage response",
    )
    if response_payload is None:
        return None
    return ExistingTWRCalculationArtifacts(
        response_model=PerformanceResponse.model_validate(response_payload),
        request_payload=_load_request_payload(calculation_id),
    )


def extract_performance_request_from_payload(request_payload: dict | None) -> PerformanceRequest | None:
    if request_payload is None:
        return None
    resolved_payload = _resolved_request_payload_from_lineage_payload(request_payload)
    try:
        resolved_request = TWRResolvedExecutionRequest.model_validate(resolved_payload)
        return resolved_request.portfolio
    except ValidationError:
        pass
    try:
        analytics_request = TWRAnalyticsRequest.model_validate(request_payload)
        if analytics_request.input_mode.value != "stateless":
            return None
        return analytics_request.to_stateless_performance_request()
    except (ValidationError, ValueError):
        return None


def extract_resolved_execution_request_from_payload(
    request_payload: dict | None,
) -> TWRResolvedExecutionRequest | None:
    if request_payload is None:
        return None
    resolved_payload = _resolved_request_payload_from_lineage_payload(request_payload)
    try:
        return TWRResolvedExecutionRequest.model_validate(resolved_payload)
    except ValidationError:
        return None


def _resolved_request_payload_from_lineage_payload(request_payload: dict) -> dict:
    resolved_request = request_payload.get("resolved_request")
    return resolved_request if isinstance(resolved_request, dict) else request_payload


def _load_request_payload(calculation_id: UUID, *, wait_seconds: float = 0.0) -> dict | None:
    deadline = time.monotonic() + wait_seconds
    while True:
        payload = lineage_metadata_store.get_payload(calculation_id)
        if payload is not None:
            request_payload = _load_json_object(
                payload.request_json,
                calculation_id=calculation_id,
                payload_name="lineage request",
            )
            if request_payload is not None:
                return request_payload

        request_path = Path(get_settings().LINEAGE_STORAGE_PATH) / str(calculation_id) / "request.json"
        if request_path.exists():
            return read_json_file(request_path)
        compute_job = compute_job_store.get_job(calculation_id)
        if compute_job is not None:
            return compute_job.request_payload
        if time.monotonic() >= deadline:
            break
        time.sleep(_REQUEST_PAYLOAD_POLL_INTERVAL_SECONDS)
    return None


def _load_json_object(raw_payload: str, *, calculation_id: UUID, payload_name: str) -> dict[str, Any] | None:
    return load_json_object_or_none(
        raw_payload,
        logger=logger,
        payload_name=f"TWR inspection subject {payload_name} payload",
        identity_name="calculation_id",
        identity_value=str(calculation_id),
        empty_is_absent=False,
    )
