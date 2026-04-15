from __future__ import annotations

import json
import os
from dataclasses import dataclass
from uuid import UUID

from app.core.config import get_settings
from app.models.responses import PerformanceResponse
from app.services.async_result_store import async_result_store
from app.services.lineage_metadata_store import lineage_metadata_store


@dataclass(frozen=True)
class ExistingTWRCalculationArtifacts:
    response_model: PerformanceResponse
    request_payload: dict | None


def load_existing_twr_calculation_artifacts(calculation_id: UUID) -> ExistingTWRCalculationArtifacts:
    async_result = async_result_store.get_result(calculation_id)
    if async_result is not None and async_result.response_payload is not None:
        return ExistingTWRCalculationArtifacts(
            response_model=PerformanceResponse.model_validate(async_result.response_payload),
            request_payload=None,
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
