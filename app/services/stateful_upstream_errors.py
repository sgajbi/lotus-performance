from __future__ import annotations

from core.errors import HTTP_400_BAD_REQUEST, APIServiceUnavailableError


def stateful_control_plane_unavailable_detail(*, source_label: str, upstream_status: int) -> str:
    detail = f"{source_label} unavailable ({upstream_status})."
    if upstream_status == 404:
        detail = (
            f"{detail} CORE_CONTROL_PLANE_BASE_URL must point to lotus-core query-control-plane, "
            "not query-service; likely wrong core control-plane base URL or stale container env."
        )
    return detail


def raise_for_stateful_control_plane_unavailable(*, source_label: str, upstream_status: int) -> None:
    if upstream_status < HTTP_400_BAD_REQUEST:
        return
    raise APIServiceUnavailableError(
        detail=stateful_control_plane_unavailable_detail(
            source_label=source_label,
            upstream_status=upstream_status,
        ),
    )


def raise_for_stateful_source_unavailable(
    *,
    source_label: str,
    upstream_status: int,
    context: str | None = None,
) -> None:
    if upstream_status < HTTP_400_BAD_REQUEST:
        return
    context_detail = f" {context}" if context else ""
    raise APIServiceUnavailableError(
        detail=f"{source_label} source unavailable{context_detail} ({upstream_status}).",
    )
