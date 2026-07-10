# main.py
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi

from app.api.endpoints import (
    benchmark,
    benchmark_exposure_context,
    composites,
    contribution,
    executions,
    health,
    inspections,
    integration_capabilities,
    lineage,
    mandate_health_context,
    performance,
    recovery_drill_history,
    returns_series,
    runtime_recoveries,
    runtime_retention_history,
    runtime_status,
    runtime_work_items,
)
from app.core.config import get_settings
from app.core.exceptions import PerformanceCalculatorError
from app.core.handlers import (
    core_api_error_exception_handler,
    http_exception_handler,
    performance_calculator_exception_handler,
    request_validation_exception_handler,
)
from app.enterprise_readiness import build_enterprise_audit_middleware, validate_enterprise_runtime_config
from app.http_security import configure_http_security
from app.models.platform_surfaces import BuildMetadataResponse, RootResponse
from app.observability import setup_observability
from app.openapi_enrichment import enrich_openapi_schema
from app.services.async_result_store import async_result_store
from app.services.build_metadata_service import build_runtime_metadata
from app.services.compute_job_store import compute_job_store
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.execution_registry import execution_registry
from app.services.http_resilience import close_upstream_http_client_pool, configure_upstream_http_client_pool
from app.services.lineage_metadata_store import lineage_metadata_store
from core.errors import APIError

settings = get_settings()


@asynccontextmanager
async def _app_lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.is_draining = False
    configure_upstream_http_client_pool(
        max_connections=settings.UPSTREAM_HTTP_MAX_CONNECTIONS,
        max_keepalive_connections=settings.UPSTREAM_HTTP_MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry_seconds=settings.UPSTREAM_HTTP_KEEPALIVE_EXPIRY_SECONDS,
    )
    bootstrap_durable_metadata_stores(
        execution_store=execution_registry,
        compute_store=compute_job_store,
        async_result_store_=async_result_store,
        lineage_store=lineage_metadata_store,
    )
    try:
        yield
    finally:
        application.state.is_draining = True
        await close_upstream_http_client_pool()


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    openapi_tags=[
        {
            "name": "Performance",
            "description": "lotus-performance-owned performance analytics APIs.",
        },
        {
            "name": "Integration",
            "description": "Capabilities and cross-service integration metadata.",
        },
    ],
    lifespan=_app_lifespan,
)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    app.openapi_schema = enrich_openapi_schema(schema)
    return app.openapi_schema


app.openapi = custom_openapi

setup_observability(app, log_level=settings.LOG_LEVEL)
configure_http_security(app, settings=settings)
validate_enterprise_runtime_config()
app.middleware("http")(build_enterprise_audit_middleware())

app.add_exception_handler(PerformanceCalculatorError, performance_calculator_exception_handler)
app.add_exception_handler(APIError, core_api_error_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

# Add a prefix to group performance-related endpoints
app.include_router(performance.router, prefix="/performance")
app.include_router(benchmark.router, prefix="/performance")
app.include_router(composites.router, prefix="/performance")
app.include_router(contribution.router, prefix="/performance")
app.include_router(executions.router, prefix="/performance")
app.include_router(inspections.router, prefix="/performance")
app.include_router(lineage.router, prefix="/performance")
app.include_router(mandate_health_context.router, prefix="/performance")
app.include_router(integration_capabilities.router, prefix="/integration")
app.include_router(returns_series.router, prefix="/integration")
app.include_router(benchmark_exposure_context.router, prefix="/integration")
app.include_router(runtime_status.router, prefix="/integration")
app.include_router(runtime_work_items.router, prefix="/integration")
app.include_router(runtime_recoveries.router, prefix="/integration")
app.include_router(recovery_drill_history.router, prefix="/integration")
app.include_router(runtime_retention_history.router, prefix="/integration")
app.include_router(health.router)


@app.get(
    "/",
    response_model=RootResponse,
    summary="Service entry",
    description=(
        "Returns the lotus-performance service entry message, support-safe build identity, and points callers to "
        "`/docs` for the governed API contract."
    ),
)
async def root() -> RootResponse:
    return RootResponse(
        message="Welcome to the Portfolio Performance Analytics API. Access /docs for API documentation.",
        build=build_runtime_metadata(settings),
    )


@app.get(
    "/version",
    response_model=BuildMetadataResponse,
    summary="Runtime build identity",
    description=(
        "Returns support-safe build metadata for correlating the running service to Git commit, OCI image labels, "
        "SBOM, vulnerability, and provenance evidence."
    ),
)
async def version() -> BuildMetadataResponse:
    return build_runtime_metadata(settings)
