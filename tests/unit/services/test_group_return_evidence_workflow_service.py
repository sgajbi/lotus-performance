from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.group_return_evidence import GroupReturnEvidenceRequest
from app.services import group_return_evidence_workflow_service as workflow_service
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_GROUP_RETURN_EVIDENCE
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from core.errors import APIError


class _MappableUpstreamFailure(Exception):
    status_code = 503
    detail = "admitted source is unavailable"

    def __init__(self) -> None:
        super().__init__(self.detail)


def _request() -> GroupReturnEvidenceRequest:
    return GroupReturnEvidenceRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "benchmark_id": "BMK_PB_GLOBAL_BALANCED",
            "as_of_date": "2026-04-10",
            "window": {"start_date": "2026-04-01", "end_date": "2026-04-10"},
            "grouping_dimension": "SECTOR",
            "reporting_currency": "USD",
        }
    )


def _required_snapshots(request: GroupReturnEvidenceRequest) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            upstream_endpoint=endpoint,
            source_identifier=(
                request.portfolio_id
                if endpoint in {"portfolio_timeseries", "position_timeseries"}
                else request.benchmark_id
                if endpoint == "benchmark_composition_window"
                else "source"
            ),
            as_of_date=(
                request.window.end_date.isoformat()
                if endpoint == "benchmark_composition_window"
                else request.as_of_date.isoformat()
            ),
            request_fingerprint=f"{endpoint}-request",
            response_fingerprint=f"{endpoint}-response",
            retrieval_status="200",
        )
        for endpoint in sorted(workflow_service._REQUIRED_SOURCE_SNAPSHOT_ENDPOINTS)
    ]


@pytest.mark.asyncio
async def test_group_return_evidence_workflow_registers_tenant_bound_execution_and_completes(mocker) -> None:
    request = _request()
    expected_response = SimpleNamespace(
        rows=[object(), object()],
        source_lineage=SimpleNamespace(source_cut_id="sha256:source-cut"),
    )
    source_input = SimpleNamespace(
        portfolio_input=object(),
        position_rows=[],
        position_source_rows_complete=True,
        benchmark_id=request.benchmark_id,
        benchmark_currency="USD",
        benchmark_component_observations=[],
        index_records=[],
    )

    mocker.patch("app.services.group_return_evidence_workflow_service.get_settings", return_value=object())
    stateful_input_service = object()
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.build_stateful_input_service",
        return_value=stateful_input_service,
    )
    register_sync = mocker.patch("app.services.group_return_evidence_workflow_service.register_sync_execution_or_raise")
    mocker.patch.object(workflow_service.execution_registry, "mark_running")
    start_stage = mocker.patch.object(workflow_service.execution_registry, "start_stage")
    complete_stage = mocker.patch.object(workflow_service.execution_registry, "complete_stage")
    mark_complete = mocker.patch.object(workflow_service.execution_registry, "mark_complete")
    mocker.patch.object(
        workflow_service.execution_registry,
        "list_upstream_snapshots",
        return_value=_required_snapshots(request),
    )
    retrieval = mocker.patch(
        "app.services.group_return_evidence_workflow_service.retrieve_stateful_attribution_source_input",
        return_value=source_input,
    )
    builder = mocker.patch(
        "app.services.group_return_evidence_workflow_service.build_group_return_evidence_response",
        return_value=expected_response,
    )

    response = await workflow_service.calculate_group_return_evidence_response(request)

    assert response is expected_response
    register_sync.assert_called_once_with(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_GROUP_RETURN_EVIDENCE,
        portfolio_id=request.portfolio_id,
        requested_window={
            "as_of_date": "2026-04-10",
            "window_start_date": "2026-04-01",
            "window_end_date": "2026-04-10",
            "grouping_dimension": "SECTOR",
            "benchmark_id": "BMK_PB_GLOBAL_BALANCED",
            "reporting_currency": "USD",
            "contract_version": "v1",
        },
        input_fingerprint=None,
        calculation_hash=None,
        request_payload=request.model_dump(mode="json"),
    )
    retrieval.assert_awaited_once_with(
        settings=mocker.ANY,
        stateful_input_service=stateful_input_service,
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        as_of_date=request.as_of_date,
        report_start_date=request.window.start_date,
        report_end_date=request.window.end_date,
        reporting_currency="USD",
        consumer_system="lotus-risk",
        group_by=["sector"],
        dimensions=[],
        include_cash_flows=True,
        filters={},
        benchmark_id_override=request.benchmark_id,
    )
    builder.assert_called_once()
    start_stage.assert_called_once_with(request.calculation_id, EXECUTION_STAGE_EXECUTION)
    complete_stage.assert_called_once_with(
        request.calculation_id,
        EXECUTION_STAGE_EXECUTION,
        details={"row_count": 2, "source_cut_id": "sha256:source-cut"},
    )
    mark_complete.assert_called_once_with(request.calculation_id)


@pytest.mark.asyncio
async def test_group_return_evidence_workflow_refuses_missing_durable_source_lineage(mocker) -> None:
    request = _request()
    mocker.patch("app.services.group_return_evidence_workflow_service.get_settings", return_value=object())
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.build_stateful_input_service", return_value=object()
    )
    mocker.patch("app.services.group_return_evidence_workflow_service.register_sync_execution_or_raise")
    mocker.patch.object(workflow_service.execution_registry, "mark_running")
    mocker.patch.object(workflow_service.execution_registry, "start_stage")
    mocker.patch.object(workflow_service.execution_registry, "list_upstream_snapshots", return_value=[])
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.retrieve_stateful_attribution_source_input",
        return_value=SimpleNamespace(),
    )
    record_failure = mocker.patch("app.services.group_return_evidence_workflow_service.record_execution_failure")

    with pytest.raises(APIError) as exc_info:
        await workflow_service.calculate_group_return_evidence_response(request)

    assert exc_info.value.status_code == 422
    assert "source lineage is incomplete" in str(exc_info.value.detail)
    record_failure.assert_called_once_with(
        calculation_id=request.calculation_id,
        message=(
            "group return evidence source lineage is incomplete; missing snapshots for: "
            "benchmark_composition_window, index_catalog, index_price_series, portfolio_timeseries, position_timeseries"
        ),
        execution_stage_started=True,
    )


@pytest.mark.asyncio
async def test_group_return_evidence_workflow_refuses_stale_or_foreign_snapshot_scope(mocker) -> None:
    request = _request()
    source_input = SimpleNamespace(benchmark_id=request.benchmark_id)
    snapshots = _required_snapshots(request)
    snapshots[0].as_of_date = "2026-04-09"

    mocker.patch("app.services.group_return_evidence_workflow_service.get_settings", return_value=object())
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.build_stateful_input_service", return_value=object()
    )
    mocker.patch("app.services.group_return_evidence_workflow_service.register_sync_execution_or_raise")
    mocker.patch.object(workflow_service.execution_registry, "mark_running")
    mocker.patch.object(workflow_service.execution_registry, "start_stage")
    mocker.patch.object(workflow_service.execution_registry, "list_upstream_snapshots", return_value=snapshots)
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.retrieve_stateful_attribution_source_input",
        return_value=source_input,
    )
    record_failure = mocker.patch("app.services.group_return_evidence_workflow_service.record_execution_failure")

    with pytest.raises(APIError) as exc_info:
        await workflow_service.calculate_group_return_evidence_response(request)

    assert exc_info.value.status_code == 422
    assert "stale or inconsistent" in str(exc_info.value.detail)
    assert "benchmark_composition_window" in str(exc_info.value.detail)
    record_failure.assert_called_once()

    foreign_snapshots = _required_snapshots(request)
    foreign_snapshots[3].source_identifier = "PB_SG_FOREIGN_001"
    with pytest.raises(ValueError, match="foreign or conflicting source identifier"):
        workflow_service._validate_snapshot_scope(
            snapshots=foreign_snapshots,
            request=request,
            benchmark_id=request.benchmark_id,
        )


@pytest.mark.asyncio
async def test_group_return_evidence_workflow_records_a_mappable_upstream_failure(mocker) -> None:
    request = _request()
    mocker.patch("app.services.group_return_evidence_workflow_service.get_settings", return_value=object())
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.build_stateful_input_service", return_value=object()
    )
    mocker.patch("app.services.group_return_evidence_workflow_service.register_sync_execution_or_raise")
    mocker.patch.object(workflow_service.execution_registry, "mark_running")
    mocker.patch.object(workflow_service.execution_registry, "start_stage")
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.retrieve_stateful_attribution_source_input",
        side_effect=_MappableUpstreamFailure(),
    )
    record_failure = mocker.patch("app.services.group_return_evidence_workflow_service.record_execution_failure")

    with pytest.raises(_MappableUpstreamFailure, match="admitted source is unavailable") as exc_info:
        await workflow_service.calculate_group_return_evidence_response(request)

    assert exc_info.value.status_code == 503
    record_failure.assert_called_once_with(
        calculation_id=request.calculation_id,
        message="admitted source is unavailable",
        execution_stage_started=True,
    )


@pytest.mark.asyncio
async def test_group_return_evidence_workflow_records_an_unexpected_failure_without_leaking_it(mocker) -> None:
    request = _request()
    mocker.patch("app.services.group_return_evidence_workflow_service.get_settings", return_value=object())
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.build_stateful_input_service", return_value=object()
    )
    mocker.patch("app.services.group_return_evidence_workflow_service.register_sync_execution_or_raise")
    mocker.patch.object(workflow_service.execution_registry, "mark_running")
    mocker.patch.object(workflow_service.execution_registry, "start_stage")
    mocker.patch(
        "app.services.group_return_evidence_workflow_service.retrieve_stateful_attribution_source_input",
        side_effect=RuntimeError("source secret must not be exposed"),
    )
    record_failure = mocker.patch("app.services.group_return_evidence_workflow_service.record_execution_failure")

    with pytest.raises(APIError) as exc_info:
        await workflow_service.calculate_group_return_evidence_response(request)

    assert exc_info.value.status_code == 500
    assert "source secret" not in str(exc_info.value.detail)
    record_failure.assert_called_once_with(
        calculation_id=request.calculation_id,
        message="Group return evidence failed unexpectedly. Use the correlation_id for support.",
        execution_stage_started=True,
    )
