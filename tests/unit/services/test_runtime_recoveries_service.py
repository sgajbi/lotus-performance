from datetime import UTC, datetime

import pytest

from app.models.runtime_recoveries import build_runtime_recoveries_response
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.runtime_recoveries_service import (
    RuntimeRecoveriesValidationError,
    RuntimeRecoveriesValidationProblem,
    build_runtime_recoveries_response_for_query,
)
from app.services.runtime_recovery_service import RuntimeRecoveryQueueState, RuntimeRecoverySnapshot


def test_build_runtime_recoveries_response_for_query_propagates_snapshot_build(monkeypatch):
    snapshot = RuntimeRecoverySnapshot(
        generated_at=datetime(2026, 3, 14, 12, 0, tzinfo=UTC),
        queue_filter="both",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
        calculation_id_contains=None,
        compute_analytics_type=None,
        lineage_calculation_type=None,
        durable_metadata_store=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        compute_queue=RuntimeRecoveryQueueState(
            status="available",
            reason=None,
            total_count=1,
            returned_count=1,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
        ),
        lineage_queue=RuntimeRecoveryQueueState(
            status="available",
            reason=None,
            total_count=0,
            returned_count=0,
            next_offset=None,
            next_cursor_recovered_before=None,
            next_cursor_calculation_id_before=None,
        ),
        compute_recoveries=[],
        lineage_recoveries=[],
    )

    called = []

    def fake_build_snapshot(**kwargs):
        called.append(kwargs)
        return snapshot

    monkeypatch.setattr("app.services.runtime_recoveries_service.build_runtime_recovery_snapshot", fake_build_snapshot)

    response = build_runtime_recoveries_response_for_query(
        queue="both",
        limit=5,
        offset=0,
        recovered_after=None,
        recovered_before=None,
        cursor_recovered_before=None,
        cursor_calculation_id_before=None,
        calculation_id_contains=None,
        compute_analytics_type=None,
        lineage_calculation_type=None,
    )

    expected = build_runtime_recoveries_response(snapshot)
    assert response == expected
    assert called == [
        dict(
            queue_filter="both",
            limit=5,
            offset=0,
            recovered_after=None,
            recovered_before=None,
            cursor_recovered_before=None,
            cursor_calculation_id_before=None,
            calculation_id_contains=None,
            compute_analytics_type=None,
            lineage_calculation_type=None,
        )
    ]


def test_build_runtime_recoveries_response_for_query_rejects_inverted_window():
    with pytest.raises(RuntimeRecoveriesValidationError) as error_info:
        build_runtime_recoveries_response_for_query(
            queue="both",
            limit=5,
            offset=0,
            recovered_after=datetime(2026, 3, 14, 12, tzinfo=UTC),
            recovered_before=datetime(2026, 3, 14, 11, tzinfo=UTC),
            cursor_recovered_before=None,
            cursor_calculation_id_before=None,
            calculation_id_contains=None,
            compute_analytics_type=None,
            lineage_calculation_type=None,
        )

    assert error_info.value.detail["code"] == "invalid_recovery_time_window"
    assert error_info.value.status_code == 422
    assert error_info.value.detail["fields"] == ["recovered_after", "recovered_before"]


def test_build_runtime_recoveries_response_for_query_rejects_incomplete_cursor():
    with pytest.raises(RuntimeRecoveriesValidationError) as error_info:
        build_runtime_recoveries_response_for_query(
            queue="both",
            limit=5,
            offset=0,
            recovered_after=None,
            recovered_before=None,
            cursor_recovered_before=None,
            cursor_calculation_id_before="calc-1",
            calculation_id_contains=None,
            compute_analytics_type=None,
            lineage_calculation_type=None,
        )

    assert error_info.value.detail["code"] == "incomplete_recovery_cursor"
    assert error_info.value.status_code == 422
    assert error_info.value.detail["fields"] == ["cursor_recovered_before", "cursor_calculation_id_before"]


def test_runtime_recoveries_validation_problem_serializes_consistent_shape():
    problem = RuntimeRecoveriesValidationProblem(
        code="invalid_recovery_time_window",
        fields=["recovered_after", "recovered_before"],
        message="recovered_after must be less than or equal to recovered_before.",
    )

    assert problem.as_detail() == {
        "code": "invalid_recovery_time_window",
        "fields": ["recovered_after", "recovered_before"],
        "message": "recovered_after must be less than or equal to recovered_before.",
    }
