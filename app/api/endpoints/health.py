from fastapi import APIRouter, Request, Response, status

from app.services.durability_health_service import check_durable_metadata_store_ready

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Service health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/live", summary="Service liveness")
async def health_live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready", summary="Service readiness")
async def health_ready(request: Request, response: Response) -> dict[str, str]:
    if bool(getattr(request.app.state, "is_draining", False)):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "draining"}
    durability_status = check_durable_metadata_store_ready()
    if not durability_status.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": durability_status.status,
            "reason": durability_status.reason or "durability_check_failed",
        }
    return {"status": durability_status.status}
