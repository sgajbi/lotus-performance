from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from app.services.operator_action_lease_service import OperatorActionLeaseSnapshot, build_operator_action_lease_snapshot
from app.services.runtime_status_domain import OperatorActionStatus, RecentOperatorActionReclaim
from app.services.runtime_status_time import age_seconds_since


class OperatorActionStatusFields(TypedDict):
    active_run_status: str
    active_run_reason: str | None
    active_run_count: int
    oldest_active_run_operator_id: str | None
    oldest_active_run_tenant_id: str | None
    oldest_active_run_governed_target: str | None
    oldest_active_run_acquired_at_utc: str | None
    oldest_active_run_age_seconds: float | None
    latest_reclaimed_run_operator_id: str | None
    latest_reclaimed_run_tenant_id: str | None
    latest_reclaimed_run_governed_target: str | None
    latest_reclaimed_run_acquired_at_utc: str | None
    latest_reclaimed_run_reclaimed_at_utc: str | None
    latest_reclaimed_run_age_seconds: float | None
    reclaimed_run_count: int
    recent_reclaimed_runs: tuple[RecentOperatorActionReclaim, ...]


def operator_action_status_fields(active_run_status: OperatorActionStatus) -> OperatorActionStatusFields:
    return {
        "active_run_status": active_run_status.status,
        "active_run_reason": active_run_status.reason,
        "active_run_count": active_run_status.active_run_count,
        "oldest_active_run_operator_id": active_run_status.oldest_active_run_operator_id,
        "oldest_active_run_tenant_id": active_run_status.oldest_active_run_tenant_id,
        "oldest_active_run_governed_target": active_run_status.oldest_active_run_governed_target,
        "oldest_active_run_acquired_at_utc": active_run_status.oldest_active_run_acquired_at_utc,
        "oldest_active_run_age_seconds": active_run_status.oldest_active_run_age_seconds,
        "latest_reclaimed_run_operator_id": active_run_status.latest_reclaimed_run_operator_id,
        "latest_reclaimed_run_tenant_id": active_run_status.latest_reclaimed_run_tenant_id,
        "latest_reclaimed_run_governed_target": active_run_status.latest_reclaimed_run_governed_target,
        "latest_reclaimed_run_acquired_at_utc": active_run_status.latest_reclaimed_run_acquired_at_utc,
        "latest_reclaimed_run_reclaimed_at_utc": active_run_status.latest_reclaimed_run_reclaimed_at_utc,
        "latest_reclaimed_run_age_seconds": active_run_status.latest_reclaimed_run_age_seconds,
        "reclaimed_run_count": active_run_status.reclaimed_run_count,
        "recent_reclaimed_runs": active_run_status.recent_reclaimed_runs,
    }


def build_operator_action_status(*, artifact_directory: Path, action_name: str) -> OperatorActionStatus:
    try:
        snapshot = build_operator_action_lease_snapshot(
            artifact_directory=artifact_directory,
            action_name=action_name,
        )
    except Exception as exc:
        return OperatorActionStatus(
            status="unavailable",
            reason=type(exc).__name__,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=None,
            latest_reclaimed_run_tenant_id=None,
            latest_reclaimed_run_governed_target=None,
            latest_reclaimed_run_acquired_at_utc=None,
            latest_reclaimed_run_reclaimed_at_utc=None,
            latest_reclaimed_run_age_seconds=None,
            reclaimed_run_count=0,
            recent_reclaimed_runs=(),
        )
    if snapshot.status != "available":
        return OperatorActionStatus(
            status="unavailable",
            reason=snapshot.reason,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=None,
            latest_reclaimed_run_tenant_id=None,
            latest_reclaimed_run_governed_target=None,
            latest_reclaimed_run_acquired_at_utc=None,
            latest_reclaimed_run_reclaimed_at_utc=None,
            latest_reclaimed_run_age_seconds=None,
            reclaimed_run_count=0,
            recent_reclaimed_runs=(),
        )
    latest_reclaimed_run = snapshot.latest_reclaimed_lease
    recent_reclaimed_runs = build_recent_operator_action_reclaims(snapshot=snapshot)
    latest_reclaimed_run_age_seconds = None
    if latest_reclaimed_run is not None:
        latest_reclaimed_run_age_seconds = age_seconds_since(latest_reclaimed_run.reclaimed_at_utc)
    if not snapshot.active_leases:
        return OperatorActionStatus(
            status="available",
            reason=None,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.operator_id
            ),
            latest_reclaimed_run_tenant_id=None if latest_reclaimed_run is None else latest_reclaimed_run.tenant_id,
            latest_reclaimed_run_governed_target=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.governed_target
            ),
            latest_reclaimed_run_acquired_at_utc=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.acquired_at_utc
            ),
            latest_reclaimed_run_reclaimed_at_utc=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.reclaimed_at_utc
            ),
            latest_reclaimed_run_age_seconds=latest_reclaimed_run_age_seconds,
            reclaimed_run_count=0 if latest_reclaimed_run is None else latest_reclaimed_run.reclaim_count,
            recent_reclaimed_runs=recent_reclaimed_runs,
        )
    oldest = snapshot.active_leases[0]
    return OperatorActionStatus(
        status="active",
        reason=None,
        active_run_count=len(snapshot.active_leases),
        oldest_active_run_operator_id=oldest.operator_id,
        oldest_active_run_tenant_id=oldest.tenant_id,
        oldest_active_run_governed_target=oldest.governed_target,
        oldest_active_run_acquired_at_utc=oldest.acquired_at_utc,
        oldest_active_run_age_seconds=age_seconds_since(oldest.acquired_at_utc),
        latest_reclaimed_run_operator_id=None if latest_reclaimed_run is None else latest_reclaimed_run.operator_id,
        latest_reclaimed_run_tenant_id=None if latest_reclaimed_run is None else latest_reclaimed_run.tenant_id,
        latest_reclaimed_run_governed_target=(
            None if latest_reclaimed_run is None else latest_reclaimed_run.governed_target
        ),
        latest_reclaimed_run_acquired_at_utc=(
            None if latest_reclaimed_run is None else latest_reclaimed_run.acquired_at_utc
        ),
        latest_reclaimed_run_reclaimed_at_utc=(
            None if latest_reclaimed_run is None else latest_reclaimed_run.reclaimed_at_utc
        ),
        latest_reclaimed_run_age_seconds=latest_reclaimed_run_age_seconds,
        reclaimed_run_count=0 if latest_reclaimed_run is None else latest_reclaimed_run.reclaim_count,
        recent_reclaimed_runs=recent_reclaimed_runs,
    )


def build_recent_operator_action_reclaims(
    *,
    snapshot: OperatorActionLeaseSnapshot,
) -> tuple[RecentOperatorActionReclaim, ...]:
    events = tuple(getattr(snapshot, "recent_reclaimed_leases", ()))
    return tuple(
        RecentOperatorActionReclaim(
            operator_id=event.operator_id,
            tenant_id=event.tenant_id,
            governed_target=event.governed_target,
            acquired_at_utc=event.acquired_at_utc,
            reclaimed_at_utc=event.reclaimed_at_utc,
            reclaimed_age_seconds=age_seconds_since(event.reclaimed_at_utc),
            reclaim_count=event.reclaim_count,
        )
        for event in events[:5]
    )
