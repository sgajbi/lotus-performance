from __future__ import annotations


def stateful_control_plane_unavailable_detail(*, source_label: str, upstream_status: int) -> str:
    detail = f"{source_label} unavailable ({upstream_status})."
    if upstream_status == 404:
        detail = (
            f"{detail} CORE_CONTROL_PLANE_BASE_URL must point to lotus-core query-control-plane, "
            "not query-service; likely wrong core control-plane base URL or stale container env."
        )
    return detail
