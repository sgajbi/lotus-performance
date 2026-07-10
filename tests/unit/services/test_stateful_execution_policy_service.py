from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.core.application_responses import accepted_application_response
from app.services.execution_registry import (
    ExecutionRecord,
    ExecutionStatus,
)
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from core.errors import APIConflictError


class _AcceptedResponse(BaseModel):
    calculation_id: str
    poll_path: str
    recommended_poll_after_seconds: int = 1


def _accepted_response_factory(calculation_id):
    return _AcceptedResponse(
        calculation_id=str(calculation_id),
        poll_path=f"/performance/executions/{calculation_id}",
    )


def _execution_record(
    *,
    calculation_id,
    analytics_type: str,
    execution_mode: str,
    status: ExecutionStatus,
    source_request_fingerprint: str,
) -> ExecutionRecord:
    return ExecutionRecord(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        portfolio_id="P1",
        execution_mode=execution_mode,
        status=status,
        requested_window={"source_request_fingerprint": source_request_fingerprint},
        input_fingerprint="resolved-fp",
        calculation_hash="resolved-hash",
        error_message=None,
        created_at_utc="2026-03-15T00:00:00Z",
        started_at_utc=None,
        completed_at_utc=None,
        stages=[],
        upstream_snapshots=[],
    )


def test_finalize_resolved_stateful_execution_updates_execution_without_offload(mocker):
    calculation_id = uuid4()
    update_contract = mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.update_execution_contract"
    )
    update_identity = mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.update_execution_identity"
    )
    promote = mocker.patch(
        "app.services.stateful_execution_policy_service.promote_existing_execution_to_async_submission_or_raise"
    )

    response = finalize_resolved_stateful_execution(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        requested_window={"position_count": 4},
        input_fingerprint="resolved-fingerprint",
        calculation_hash="resolved-hash",
        resolved_request_payload={"portfolio_id": "P1"},
        should_offload=False,
        offload_reason="large_resolved_stateful_contribution",
        accepted_response_factory=_accepted_response_factory,
    )

    assert response is None
    update_contract.assert_called_once_with(
        calculation_id,
        requested_window={"position_count": 4},
    )
    update_identity.assert_called_once_with(
        calculation_id,
        input_fingerprint="resolved-fingerprint",
        calculation_hash="resolved-hash",
    )
    promote.assert_not_called()


def test_finalize_resolved_stateful_execution_promotes_async_when_requested(mocker):
    calculation_id = uuid4()
    update_contract = mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.update_execution_contract"
    )
    update_identity = mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.update_execution_identity"
    )
    accepted_response = accepted_application_response(_accepted_response_factory(calculation_id))
    promote = mocker.patch(
        "app.services.stateful_execution_policy_service.promote_existing_execution_to_async_submission_or_raise",
        return_value=accepted_response,
    )

    response = finalize_resolved_stateful_execution(
        calculation_id=calculation_id,
        analytics_type="Attribution",
        requested_window={"input_count": 18},
        input_fingerprint="resolved-fingerprint",
        calculation_hash="resolved-hash",
        resolved_request_payload={"portfolio_id": "P1"},
        should_offload=True,
        offload_reason="large_resolved_stateful_attribution",
        accepted_response_factory=_accepted_response_factory,
    )

    assert response is accepted_response
    update_contract.assert_not_called()
    update_identity.assert_not_called()
    promote.assert_called_once_with(
        calculation_id=calculation_id,
        analytics_type="Attribution",
        requested_window={"input_count": 18},
        input_fingerprint="resolved-fingerprint",
        calculation_hash="resolved-hash",
        request_payload={"portfolio_id": "P1"},
        offload_reason="large_resolved_stateful_attribution",
        accepted_response_factory=_accepted_response_factory,
    )


def test_finalize_resolved_stateful_execution_leaves_execution_unchanged_when_async_promotion_conflicts(mocker):
    calculation_id = uuid4()
    update_contract = mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.update_execution_contract"
    )
    update_identity = mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.update_execution_identity"
    )
    promote = mocker.patch(
        "app.services.stateful_execution_policy_service.promote_existing_execution_to_async_submission_or_raise",
        side_effect=APIConflictError(
            "A different async compute job already exists for this calculation_id. "
            "Reuse the original request exactly or submit with a new calculation_id."
        ),
    )

    with pytest.raises(APIConflictError):
        finalize_resolved_stateful_execution(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            requested_window={"requested_periods": ["SI"], "source_request_fingerprint": "new-source-fp"},
            input_fingerprint="new-resolved-fingerprint",
            calculation_hash="new-resolved-hash",
            resolved_request_payload={"portfolio_id": "P1", "requested_periods": ["SI"]},
            should_offload=True,
            offload_reason="large_resolved_stateful_returns_series",
            accepted_response_factory=_accepted_response_factory,
        )

    update_contract.assert_not_called()
    update_identity.assert_not_called()
    promote.assert_called_once()


def test_replay_promoted_stateful_async_execution_returns_none_for_non_matching_execution(mocker):
    calculation_id = uuid4()
    get_execution = mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.get_execution",
        side_effect=[
            None,
            _execution_record(
                calculation_id=calculation_id,
                analytics_type="MWR",
                execution_mode="async",
                status=ExecutionStatus.PENDING,
                source_request_fingerprint="fp",
            ),
            _execution_record(
                calculation_id=calculation_id,
                analytics_type="Contribution",
                execution_mode="sync",
                status=ExecutionStatus.COMPLETE,
                source_request_fingerprint="fp",
            ),
            _execution_record(
                calculation_id=calculation_id,
                analytics_type="Contribution",
                execution_mode="async",
                status=ExecutionStatus.PENDING,
                source_request_fingerprint="other-fp",
            ),
        ],
    )

    assert (
        replay_promoted_stateful_async_execution(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            source_request_fingerprint="fp",
            accepted_response_factory=_accepted_response_factory,
        )
        is None
    )
    assert (
        replay_promoted_stateful_async_execution(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            source_request_fingerprint="fp",
            accepted_response_factory=_accepted_response_factory,
        )
        is None
    )
    assert (
        replay_promoted_stateful_async_execution(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            source_request_fingerprint="fp",
            accepted_response_factory=_accepted_response_factory,
        )
        is None
    )
    assert (
        replay_promoted_stateful_async_execution(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            source_request_fingerprint="fp",
            accepted_response_factory=_accepted_response_factory,
        )
        is None
    )
    assert get_execution.call_count == 4


def test_replay_promoted_stateful_async_execution_returns_accepted_response_for_matching_execution(mocker):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.stateful_execution_policy_service.execution_registry.get_execution",
        return_value=_execution_record(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            execution_mode="async",
            status=ExecutionStatus.PENDING,
            source_request_fingerprint="fp",
        ),
    )

    response = replay_promoted_stateful_async_execution(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        source_request_fingerprint="fp",
        accepted_response_factory=_accepted_response_factory,
    )

    assert response is not None
    assert response.status_code == 202
    assert response.headers == {"Retry-After": "1"}
    assert response.content
