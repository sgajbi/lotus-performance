from decimal import Decimal
from typing import cast

from app.services import runtime_status_degradation
from app.services.runtime_status_domain import (
    OperatorActionStatus,
    RecoveryDrillStatus,
    RuntimeDegradationDetail,
    RuntimeQueueStatus,
    RuntimeRetentionStatus,
)


def test_runtime_status_missing_history_degradation_helper_respects_threshold():
    assert runtime_status_degradation.missing_history_degradation(
        threshold=0.0,
        reason="runtime_retention_history_unavailable",
    ) == ((), ())

    reasons, details = runtime_status_degradation.missing_history_degradation(
        threshold=300.0,
        reason="runtime_retention_history_unavailable",
    )

    assert reasons == ("runtime_retention_history_unavailable",)
    assert len(details) == 1
    assert details[0].reason == "runtime_retention_history_unavailable"
    assert details[0].observed_value == Decimal("0")
    assert details[0].threshold_value == Decimal("300.0")


def test_lifecycle_status_from_degradation_details_maps_available_and_degraded_states():
    available_status, available_reason, available_reasons = (
        runtime_status_degradation.lifecycle_status_from_degradation_details(())
    )
    degraded_status, degraded_reason, degraded_reasons = (
        runtime_status_degradation.lifecycle_status_from_degradation_details(
            (
                RuntimeDegradationDetail(
                    reason="runtime_retention_latest_not_applied",
                    observed_value=Decimal("0"),
                    threshold_value=Decimal("0"),
                ),
            )
        )
    )

    assert available_status == "available"
    assert available_reason is None
    assert available_reasons == ()
    assert degraded_status == "degraded"
    assert degraded_reason == "runtime_retention_latest_not_applied"
    assert degraded_reasons == ("runtime_retention_latest_not_applied",)


def test_runtime_status_from_component_statuses_preserves_draining_and_durable_states():
    degraded_component = cast(RuntimeQueueStatus, type("Queue", (), {"status": "degraded"})())
    available_queue = cast(RuntimeQueueStatus, type("Queue", (), {"status": "available"})())
    available_recovery = cast(RecoveryDrillStatus, type("Recovery", (), {"status": "available"})())
    available_retention = cast(RuntimeRetentionStatus, type("Retention", (), {"status": "available"})())

    draining_status = runtime_status_degradation.runtime_status_from_component_statuses(
        is_draining=True,
        durable_metadata_status="ready",
        compute_queue=degraded_component,
        lineage_queue=available_queue,
        recovery_drill=available_recovery,
        runtime_retention=available_retention,
    )
    unavailable_status = runtime_status_degradation.runtime_status_from_component_statuses(
        is_draining=False,
        durable_metadata_status="unavailable",
        compute_queue=available_queue,
        lineage_queue=available_queue,
        recovery_drill=available_recovery,
        runtime_retention=available_retention,
    )

    assert draining_status == "draining"
    assert unavailable_status == "unavailable"


def test_runtime_status_from_component_statuses_degrades_ready_runtime_when_component_not_available():
    available_queue = cast(RuntimeQueueStatus, type("Queue", (), {"status": "available"})())
    available_recovery = cast(RecoveryDrillStatus, type("Recovery", (), {"status": "available"})())
    unavailable_retention = cast(RuntimeRetentionStatus, type("Retention", (), {"status": "unavailable"})())

    status = runtime_status_degradation.runtime_status_from_component_statuses(
        is_draining=False,
        durable_metadata_status="ready",
        compute_queue=available_queue,
        lineage_queue=available_queue,
        recovery_drill=available_recovery,
        runtime_retention=unavailable_retention,
    )

    assert status == "degraded"


def test_runtime_status_collect_reasons_covers_runtime_retention_unavailable():
    reasons = runtime_status_degradation.collect_runtime_degradation_reasons(
        compute_queue=cast(
            RuntimeQueueStatus,
            type("Queue", (), {"status": "available", "reason": None, "degradation_reasons": ()})(),
        ),
        lineage_queue=cast(
            RuntimeQueueStatus,
            type("Queue", (), {"status": "available", "reason": None, "degradation_reasons": ()})(),
        ),
        recovery_drill=cast(
            RecoveryDrillStatus,
            type("Recovery", (), {"status": "available", "reason": None, "degradation_reasons": ()})(),
        ),
        runtime_retention=cast(
            RuntimeRetentionStatus,
            type(
                "Retention",
                (),
                {"status": "unavailable", "reason": "runtime_retention_manifest_missing", "degradation_reasons": ()},
            )(),
        ),
    )

    assert reasons == ("runtime_retention:runtime_retention_manifest_missing",)


def test_runtime_status_degradation_detail_helper_uses_governed_threshold_semantics():
    details: list[RuntimeDegradationDetail] = []

    runtime_status_degradation.append_degradation_detail_if_breached(
        details,
        reason="disabled_threshold",
        observed_value=100,
        threshold_value=0,
    )
    runtime_status_degradation.append_degradation_detail_if_breached(
        details,
        reason="below_threshold",
        observed_value=9,
        threshold_value=10,
    )
    runtime_status_degradation.append_degradation_detail_if_breached(
        details,
        reason="at_threshold",
        observed_value=10,
        threshold_value=10,
    )

    assert len(details) == 1
    assert details[0].reason == "at_threshold"
    assert details[0].observed_value == runtime_status_degradation.decimal_number(10)
    assert details[0].threshold_value == runtime_status_degradation.decimal_number(10)


def test_runtime_status_operator_action_degradation_helper_reuses_threshold_semantics():
    details: list[RuntimeDegradationDetail] = []
    active_run_status = OperatorActionStatus(
        status="active",
        reason=None,
        active_run_count=1,
        oldest_active_run_operator_id="ops-user",
        oldest_active_run_tenant_id=None,
        oldest_active_run_governed_target="runtime-retention",
        oldest_active_run_acquired_at_utc="2026-03-15T00:00:00Z",
        oldest_active_run_age_seconds=120.0,
        latest_reclaimed_run_operator_id="ops-user",
        latest_reclaimed_run_tenant_id=None,
        latest_reclaimed_run_governed_target="runtime-retention",
        latest_reclaimed_run_acquired_at_utc="2026-03-15T00:00:00Z",
        latest_reclaimed_run_reclaimed_at_utc="2026-03-15T00:10:00Z",
        latest_reclaimed_run_age_seconds=60.0,
        reclaimed_run_count=3,
        recent_reclaimed_runs=(),
    )

    runtime_status_degradation.append_operator_action_degradation_details(
        details,
        active_run_status=active_run_status,
        active_run_age_threshold=60.0,
        active_run_reason="runtime_retention_active_run_age_exceeded",
        reclaim_threshold=3,
        reclaim_reason="runtime_retention_reclaim_pressure_exceeded",
    )

    assert tuple(detail.reason for detail in details) == (
        "runtime_retention_active_run_age_exceeded",
        "runtime_retention_reclaim_pressure_exceeded",
    )
    assert details[0].observed_value == runtime_status_degradation.decimal_number(120.0)
    assert details[0].threshold_value == runtime_status_degradation.decimal_number(60.0)
    assert details[1].observed_value == runtime_status_degradation.decimal_number(3)
    assert details[1].threshold_value == runtime_status_degradation.decimal_number(3)


def test_runtime_status_latest_history_age_degradation_helper_uses_governed_threshold_semantics():
    details: list[RuntimeDegradationDetail] = []

    runtime_status_degradation.append_latest_history_age_degradation_detail(
        details,
        reason="runtime_retention_age_exceeded",
        latest_age_seconds=59.9,
        threshold=60.0,
    )
    runtime_status_degradation.append_latest_history_age_degradation_detail(
        details,
        reason="runtime_retention_age_exceeded",
        latest_age_seconds=60.0,
        threshold=60.0,
    )

    assert len(details) == 1
    assert details[0].reason == "runtime_retention_age_exceeded"
    assert details[0].observed_value == runtime_status_degradation.decimal_number(60.0)
    assert details[0].threshold_value == runtime_status_degradation.decimal_number(60.0)


def test_runtime_status_lifecycle_state_degradation_helper_uses_zero_threshold_detail():
    details: list[RuntimeDegradationDetail] = []

    runtime_status_degradation.append_lifecycle_state_degradation_detail(
        details,
        is_healthy=True,
        reason="runtime_retention_latest_not_applied",
    )
    runtime_status_degradation.append_lifecycle_state_degradation_detail(
        details,
        is_healthy=False,
        reason="runtime_retention_latest_not_applied",
    )

    assert len(details) == 1
    assert details[0].reason == "runtime_retention_latest_not_applied"
    assert details[0].observed_value == runtime_status_degradation.decimal_number(0)
    assert details[0].threshold_value == runtime_status_degradation.decimal_number(0)
