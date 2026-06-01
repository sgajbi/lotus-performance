from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import get_settings
from app.services.durability_health_service import (
    check_durable_metadata_store_ready,
)
from app.services.runtime_status_degradation import (
    collect_runtime_degradation_details,
    collect_runtime_degradation_reasons,
    runtime_status_from_component_statuses,
)
from app.services.runtime_status_domain import RuntimeStatusSnapshot
from app.services.runtime_status_lifecycle import (
    build_recovery_drill_status,
    build_runtime_retention_status,
)
from app.services.runtime_status_policy import (
    build_compute_queue_policy,
    build_lineage_queue_policy,
    build_recovery_drill_policy,
    build_runtime_retention_policy,
)
from app.services.runtime_status_queue import build_compute_queue_status, build_lineage_queue_status


def build_runtime_status_snapshot(*, is_draining: bool) -> RuntimeStatusSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()
    settings = get_settings()
    compute_queue_policy = build_compute_queue_policy(settings=settings)
    lineage_queue_policy = build_lineage_queue_policy(settings=settings)
    recovery_drill_policy = build_recovery_drill_policy(settings=settings)
    runtime_retention_policy = build_runtime_retention_policy(settings=settings)

    compute_queue = build_compute_queue_status(durability_status, settings=settings)
    lineage_queue = build_lineage_queue_status(durability_status, settings=settings)
    recovery_drill = build_recovery_drill_status(settings=settings, policy=recovery_drill_policy)
    runtime_retention = build_runtime_retention_status(settings=settings, policy=runtime_retention_policy)
    runtime_status = runtime_status_from_component_statuses(
        is_draining=is_draining,
        durable_metadata_status=durability_status.status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        recovery_drill=recovery_drill,
        runtime_retention=runtime_retention,
    )
    runtime_degradation_reasons = collect_runtime_degradation_reasons(
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        recovery_drill=recovery_drill,
        runtime_retention=runtime_retention,
    )
    runtime_degradation_details = collect_runtime_degradation_details(
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        recovery_drill=recovery_drill,
        runtime_retention=runtime_retention,
    )

    return RuntimeStatusSnapshot(
        generated_at=generated_at,
        runtime_status=runtime_status,
        runtime_degradation_reasons=runtime_degradation_reasons,
        runtime_degradation_details=runtime_degradation_details,
        draining=is_draining,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        recovery_drill=recovery_drill,
        runtime_retention=runtime_retention,
        compute_queue_policy=compute_queue_policy,
        lineage_queue_policy=lineage_queue_policy,
        recovery_drill_policy=recovery_drill_policy,
        runtime_retention_policy=runtime_retention_policy,
    )
