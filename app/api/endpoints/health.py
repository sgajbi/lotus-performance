from fastapi import APIRouter, Request, Response, status

from app.models.platform_surfaces import HealthStatusResponse
from app.services.durability_health_service import DurabilityHealthStatus, check_durable_metadata_store_ready
from app.services.remediation_hint_service import get_remediation_hint

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="Service health",
    response_model=HealthStatusResponse,
    description="Returns basic process health for lotus-performance. Use this as a lightweight reachability probe, not as a durable readiness contract.",
)
async def health() -> HealthStatusResponse:
    """Return lightweight process reachability for load balancers and smoke probes."""
    return HealthStatusResponse(status="ok")


@router.get(
    "/health/live",
    summary="Service liveness",
    response_model=HealthStatusResponse,
    description="Returns liveness for lotus-performance. This route answers whether the process is running, without checking durable metadata or lineage storage dependencies.",
)
async def health_live() -> HealthStatusResponse:
    """Return liveness without checking durable runtime dependencies."""
    return HealthStatusResponse(status="live")


def _readiness_failure_response(durability_status: DurabilityHealthStatus) -> HealthStatusResponse:
    """Build the readiness failure payload from durable dependency status."""
    payload = {
        "status": durability_status.status,
        "reason": durability_status.reason or "durability_check_failed",
    }
    remediation_hint = get_remediation_hint(durability_status.reason)
    if remediation_hint is not None:
        payload["remediation_hint"] = remediation_hint
    return HealthStatusResponse(**payload)


@router.get(
    "/health/ready",
    summary="Service readiness",
    response_model=HealthStatusResponse,
    description=(
        "Returns readiness only when lotus-performance is not draining and its durable metadata and lineage storage dependencies are usable. "
        "Readiness failures return `503` with a concrete reason and, where available, a remediation hint."
    ),
)
async def health_ready(request: Request, response: Response) -> HealthStatusResponse:
    """Return readiness after draining and durable metadata dependency checks."""
    if bool(getattr(request.app.state, "is_draining", False)):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatusResponse(status="draining")
    durability_status = check_durable_metadata_store_ready()
    if not durability_status.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _readiness_failure_response(durability_status)
    return HealthStatusResponse(status=durability_status.status)
