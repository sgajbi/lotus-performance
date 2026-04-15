from __future__ import annotations

import json
import os
from dataclasses import dataclass
from uuid import UUID

from app.core.config import get_settings
from app.models.requests import PerformanceRequest
from app.models.responses import PerformanceResponse
from app.models.twr_requests import TWRAnalyticsRequest, TWRResolvedExecutionRequest
from app.services.async_result_store import async_result_store
from app.services.lineage_metadata_store import lineage_metadata_store


@dataclass(frozen=True)
class ExistingTWRCalculationArtifacts:
    response_model: PerformanceResponse
    request_payload: dict | None


def load_existing_twr_calculation_artifacts(calculation_id: UUID) -> ExistingTWRCalculationArtifacts:
    request_payload = _load_request_payload(calculation_id)
    async_result = async_result_store.get_result(calculation_id)
    if async_result is not None and async_result.response_payload is not None:
        return ExistingTWRCalculationArtifacts(
            response_model=PerformanceResponse.model_validate(async_result.response_payload),
            request_payload=request_payload,
        )

    payload = lineage_metadata_store.get_payload(calculation_id)
    if payload is not None:
        return ExistingTWRCalculationArtifacts(
            response_model=PerformanceResponse.model_validate(json.loads(payload.response_json)),
            request_payload=json.loads(payload.request_json),
        )

    response_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id), "response.json")
    request_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id), "request.json")
    if os.path.exists(response_path):
        with open(response_path, "r", encoding="utf-8") as response_file:
            response_payload = json.load(response_file)
        request_payload = None
        if os.path.exists(request_path):
            with open(request_path, "r", encoding="utf-8") as request_file:
                request_payload = json.load(request_file)
        return ExistingTWRCalculationArtifacts(
            response_model=PerformanceResponse.model_validate(response_payload),
            request_payload=request_payload,
        )

    raise KeyError(f"TWR response artifacts not found for calculation: {calculation_id}")


def extract_performance_request_from_payload(request_payload: dict | None) -> PerformanceRequest | None:
    if request_payload is None:
        return None
    resolved_payload = _resolved_request_payload_from_lineage_payload(request_payload)
    try:
        resolved_request = TWRResolvedExecutionRequest.model_validate(resolved_payload)
        return resolved_request.portfolio
    except Exception:
        pass
    try:
        analytics_request = TWRAnalyticsRequest.model_validate(request_payload)
        if analytics_request.input_mode.value != "stateless":
            return None
        return analytics_request.to_stateless_performance_request()
    except Exception:
        return None


def extract_resolved_execution_request_from_payload(
    request_payload: dict | None,
) -> TWRResolvedExecutionRequest | None:
    if request_payload is None:
        return None
    resolved_payload = _resolved_request_payload_from_lineage_payload(request_payload)
    try:
        return TWRResolvedExecutionRequest.model_validate(resolved_payload)
    except Exception:
        return None


def _resolved_request_payload_from_lineage_payload(request_payload: dict) -> dict:
    resolved_request = request_payload.get("resolved_request")
    return resolved_request if isinstance(resolved_request, dict) else request_payload


def _load_request_payload(calculation_id: UUID) -> dict | None:
    payload = lineage_metadata_store.get_payload(calculation_id)
    if payload is not None:
        return json.loads(payload.request_json)

    request_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id), "request.json")
    if os.path.exists(request_path):
        with open(request_path, "r", encoding="utf-8") as request_file:
            return json.load(request_file)
    return None
