from __future__ import annotations

from core.errors import HTTP_400_BAD_REQUEST, APIError, APIServiceUnavailableError

_PORTFOLIO_REFUSAL_CODE = "QCP_ANALYTICS_INSUFFICIENT_DATA"
_PORTFOLIO_REFUSAL_TYPE = "https://lotus-platform.dev/problems/query-control-plane/qcp_analytics_insufficient_data"


def stateful_control_plane_unavailable_detail(*, source_label: str, upstream_status: int) -> str:
    detail = f"{source_label} unavailable ({upstream_status})."
    if upstream_status == 404:
        detail = (
            f"{detail} CORE_CONTROL_PLANE_BASE_URL must point to lotus-core query-control-plane, "
            "not query-service; likely wrong core control-plane base URL or stale container env."
        )
    return detail


def raise_for_stateful_control_plane_unavailable(
    *,
    source_label: str,
    upstream_status: int,
    upstream_payload: object = None,
    source_product: str | None = None,
) -> None:
    if upstream_status < HTTP_400_BAD_REQUEST:
        return
    if _is_direct_portfolio_source_refusal(upstream_status, upstream_payload, source_product):
        raise APIError(
            status_code=422,
            detail="Required portfolio analytics source data is unavailable for the requested scope.",
            error_code=_PORTFOLIO_REFUSAL_CODE,
            retryable=False,
            remediation_hint="Repair the Core source data, then submit a new calculation request.",
        )
    raise APIServiceUnavailableError(
        detail=stateful_control_plane_unavailable_detail(
            source_label=source_label,
            upstream_status=upstream_status,
        ),
    )


def _is_direct_portfolio_source_refusal(status: int, payload: object, product: str | None) -> bool:
    # Core also uses this code for unfinished export jobs. Recognition therefore
    # requires the direct product call site and the complete matching problem.
    # Never project upstream diagnostic text into a durable/public failure.
    if status != 422 or product != "PortfolioTimeseriesInput" or not isinstance(payload, dict):
        return False
    if type(payload.get("status")) is not int or payload["status"] != status or "retryable" in payload:
        return False
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return (
        payload.get("type"),
        payload.get("error_code"),
        metadata.get("analytics_error_code"),
        metadata.get("source_product", product),
    ) == (_PORTFOLIO_REFUSAL_TYPE, _PORTFOLIO_REFUSAL_CODE, "INSUFFICIENT_DATA", product)


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
