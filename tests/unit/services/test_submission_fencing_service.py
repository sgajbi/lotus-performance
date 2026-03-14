from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from app.services.compute_job_store import ComputeJobRegistrationResult, ComputeJobRegistrationStatus
from app.services.execution_registry import ExecutionRegistrationResult, ExecutionRegistrationStatus
from app.services.submission_fencing_service import register_async_submission_or_raise


class _AcceptedResponse(BaseModel):
    calculation_id: str
    poll_path: str


def _accepted_response_factory(calculation_id):
    return _AcceptedResponse(
        calculation_id=str(calculation_id),
        poll_path=f"/performance/executions/{calculation_id}",
    )


def test_register_async_submission_does_not_bootstrap_schema_per_request(mocker):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.submission_fencing_service.execution_registry.create_schema",
        side_effect=AssertionError("execution schema bootstrap should not run in request path"),
    )
    mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.create_schema",
        side_effect=AssertionError("compute schema bootstrap should not run in request path"),
    )
    register_execution = mocker.patch(
        "app.services.submission_fencing_service.execution_registry.register_execution",
        return_value=ExecutionRegistrationResult(status=ExecutionRegistrationStatus.CREATED),
    )
    start_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.start_stage")
    complete_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.complete_stage")
    register_job = mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.register_job",
        return_value=ComputeJobRegistrationResult(status=ComputeJobRegistrationStatus.CREATED),
    )

    response = register_async_submission_or_raise(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        portfolio_id="P1",
        requested_window={"requested_periods": ["ITD"]},
        input_fingerprint="fingerprint",
        calculation_hash="hash",
        request_payload={"calculation_id": str(calculation_id)},
        offload_reason="large_input",
        accepted_response_factory=_accepted_response_factory,
    )

    assert response.status_code == 202
    register_execution.assert_called_once()
    register_job.assert_called_once()
    start_stage.assert_called_once_with(calculation_id, "submission")
    complete_stage.assert_called_once_with(calculation_id, "submission", details={"offload_reason": "large_input"})


def test_register_async_submission_replay_does_not_reopen_submission_stage(mocker):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.submission_fencing_service.execution_registry.register_execution",
        return_value=ExecutionRegistrationResult(
            status=ExecutionRegistrationStatus.REPLAY,
            existing_status=None,
            existing_execution_mode="async",
        ),
    )
    start_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.start_stage")
    complete_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.complete_stage")
    mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.register_job",
        return_value=ComputeJobRegistrationResult(status=ComputeJobRegistrationStatus.REPLAY),
    )

    response = register_async_submission_or_raise(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        portfolio_id="P1",
        requested_window={"requested_periods": ["ITD"]},
        input_fingerprint="fingerprint",
        calculation_hash="hash",
        request_payload={"calculation_id": str(calculation_id)},
        offload_reason="large_input",
        accepted_response_factory=_accepted_response_factory,
    )

    assert response.status_code == 202
    start_stage.assert_not_called()
    complete_stage.assert_not_called()


def test_register_async_submission_conflict_on_job_payload_drift_raises_409(mocker):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.submission_fencing_service.execution_registry.register_execution",
        return_value=ExecutionRegistrationResult(status=ExecutionRegistrationStatus.REPLAY),
    )
    mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.register_job",
        return_value=ComputeJobRegistrationResult(status=ComputeJobRegistrationStatus.CONFLICT),
    )

    with pytest.raises(HTTPException) as exc_info:
        register_async_submission_or_raise(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            portfolio_id="P1",
            requested_window={"requested_periods": ["ITD"]},
            input_fingerprint="fingerprint",
            calculation_hash="hash",
            request_payload={"calculation_id": str(calculation_id)},
            offload_reason="large_input",
            accepted_response_factory=_accepted_response_factory,
        )

    assert exc_info.value.status_code == 409
    assert "A different async compute job already exists" in str(exc_info.value.detail)
