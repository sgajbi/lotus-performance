import logging
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from app.services.compute_job_store import ComputeJobRegistrationResult, ComputeJobRegistrationStatus
from app.services.execution_registry import ExecutionRegistrationResult, ExecutionRegistrationStatus
from app.services.execution_stage_names import EXECUTION_STAGE_SUBMISSION
from app.services.submission_fencing_service import (
    promote_existing_execution_to_async_submission_or_raise,
    register_async_submission_or_raise,
)


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
    start_stage.assert_called_once_with(calculation_id, EXECUTION_STAGE_SUBMISSION)
    complete_stage.assert_called_once_with(
        calculation_id, EXECUTION_STAGE_SUBMISSION, details={"offload_reason": "large_input"}
    )


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


def test_register_async_submission_replay_self_heals_missing_job(mocker):
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
    start_stage.assert_called_once_with(calculation_id, EXECUTION_STAGE_SUBMISSION)
    complete_stage.assert_called_once_with(
        calculation_id, EXECUTION_STAGE_SUBMISSION, details={"offload_reason": "large_input"}
    )


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


def test_register_async_submission_cleans_up_new_execution_on_job_conflict(mocker):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.submission_fencing_service.execution_registry.register_execution",
        return_value=ExecutionRegistrationResult(status=ExecutionRegistrationStatus.CREATED),
    )
    start_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.start_stage")
    delete_execution = mocker.patch("app.services.submission_fencing_service.execution_registry.delete_execution")
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
    start_stage.assert_called_once_with(calculation_id, EXECUTION_STAGE_SUBMISSION)
    delete_execution.assert_called_once_with(calculation_id)


def test_register_async_submission_cleans_up_new_execution_when_job_registration_raises(mocker, caplog):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.submission_fencing_service.execution_registry.register_execution",
        return_value=ExecutionRegistrationResult(status=ExecutionRegistrationStatus.CREATED),
    )
    mocker.patch("app.services.submission_fencing_service.execution_registry.start_stage")
    delete_execution = mocker.patch("app.services.submission_fencing_service.execution_registry.delete_execution")
    mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.register_job",
        side_effect=RuntimeError("queue unavailable"),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.submission_fencing_service"):
        with pytest.raises(RuntimeError, match="queue unavailable"):
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

    delete_execution.assert_called_once_with(calculation_id)
    assert f"Async compute job registration failed for calculation_id={calculation_id}" in caplog.text
    assert "analytics_type=Contribution" in caplog.text
    assert "RuntimeError: queue unavailable" in caplog.text


def test_register_async_submission_preserves_job_error_when_cleanup_fails(mocker, caplog):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.submission_fencing_service.execution_registry.register_execution",
        return_value=ExecutionRegistrationResult(status=ExecutionRegistrationStatus.CREATED),
    )
    mocker.patch("app.services.submission_fencing_service.execution_registry.start_stage")
    mocker.patch(
        "app.services.submission_fencing_service.execution_registry.delete_execution",
        side_effect=RuntimeError("cleanup unavailable"),
    )
    mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.register_job",
        side_effect=RuntimeError("queue unavailable"),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.submission_fencing_service"):
        with pytest.raises(RuntimeError, match="queue unavailable"):
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

    assert f"Async compute job registration failed for calculation_id={calculation_id}" in caplog.text
    assert f"Async execution registration cleanup failed for calculation_id={calculation_id}" in caplog.text
    assert "RuntimeError: queue unavailable" in caplog.text
    assert "RuntimeError: cleanup unavailable" in caplog.text


def test_promote_existing_execution_defers_execution_mutation_until_job_registration_succeeds(mocker):
    calculation_id = uuid4()
    register_job = mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.register_job",
        return_value=ComputeJobRegistrationResult(status=ComputeJobRegistrationStatus.CREATED),
    )
    update_contract = mocker.patch(
        "app.services.submission_fencing_service.execution_registry.update_execution_contract"
    )
    update_identity = mocker.patch(
        "app.services.submission_fencing_service.execution_registry.update_execution_identity"
    )
    start_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.start_stage")
    complete_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.complete_stage")

    response = promote_existing_execution_to_async_submission_or_raise(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        requested_window={"requested_periods": ["ITD"]},
        input_fingerprint="fingerprint",
        calculation_hash="hash",
        request_payload={"calculation_id": str(calculation_id)},
        offload_reason="large_resolved_stateful_contribution",
        accepted_response_factory=_accepted_response_factory,
    )

    assert response.status_code == 202
    register_job.assert_called_once()
    update_contract.assert_called_once()
    update_identity.assert_called_once()
    start_stage.assert_called_once_with(calculation_id, EXECUTION_STAGE_SUBMISSION)
    complete_stage.assert_called_once_with(
        calculation_id,
        EXECUTION_STAGE_SUBMISSION,
        details={"offload_reason": "large_resolved_stateful_contribution"},
    )


def test_promote_existing_execution_leaves_execution_unchanged_on_job_conflict(mocker):
    calculation_id = uuid4()
    mocker.patch(
        "app.services.submission_fencing_service.compute_job_store.register_job",
        return_value=ComputeJobRegistrationResult(status=ComputeJobRegistrationStatus.CONFLICT),
    )
    update_contract = mocker.patch(
        "app.services.submission_fencing_service.execution_registry.update_execution_contract"
    )
    update_identity = mocker.patch(
        "app.services.submission_fencing_service.execution_registry.update_execution_identity"
    )
    start_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.start_stage")
    complete_stage = mocker.patch("app.services.submission_fencing_service.execution_registry.complete_stage")

    with pytest.raises(HTTPException) as exc_info:
        promote_existing_execution_to_async_submission_or_raise(
            calculation_id=calculation_id,
            analytics_type="Contribution",
            requested_window={"requested_periods": ["ITD"]},
            input_fingerprint="fingerprint",
            calculation_hash="hash",
            request_payload={"calculation_id": str(calculation_id)},
            offload_reason="large_resolved_stateful_contribution",
            accepted_response_factory=_accepted_response_factory,
        )

    assert exc_info.value.status_code == 409
    update_contract.assert_not_called()
    update_identity.assert_not_called()
    start_stage.assert_not_called()
    complete_stage.assert_not_called()
