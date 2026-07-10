from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.application_responses import ApplicationHttpResponse, accepted_application_response
from app.services.execution_registry import execution_registry
from app.services.submission_fencing_service import promote_existing_execution_to_async_submission_or_raise


def finalize_resolved_stateful_execution(
    *,
    calculation_id: UUID,
    analytics_type: str,
    requested_window: dict[str, Any],
    input_fingerprint: str | None,
    calculation_hash: str | None,
    resolved_request_payload: dict[str, Any],
    should_offload: bool,
    offload_reason: str,
    accepted_response_factory: Callable[[UUID], BaseModel],
) -> ApplicationHttpResponse | None:
    if should_offload:
        return promote_existing_execution_to_async_submission_or_raise(
            calculation_id=calculation_id,
            analytics_type=analytics_type,
            requested_window=requested_window,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=resolved_request_payload,
            offload_reason=offload_reason,
            accepted_response_factory=accepted_response_factory,
        )
    execution_registry.update_execution_contract(
        calculation_id,
        requested_window=requested_window,
    )
    execution_registry.update_execution_identity(
        calculation_id,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    return None


def replay_promoted_stateful_async_execution(
    *,
    calculation_id: UUID,
    analytics_type: str,
    source_request_fingerprint: str,
    accepted_response_factory: Callable[[UUID], BaseModel],
) -> ApplicationHttpResponse | None:
    execution = execution_registry.get_execution(calculation_id)
    if execution is None:
        return None
    if execution.analytics_type != analytics_type or execution.execution_mode != "async":
        return None
    if execution.requested_window.get("source_request_fingerprint") != source_request_fingerprint:
        return None
    return accepted_application_response(accepted_response_factory(calculation_id))
