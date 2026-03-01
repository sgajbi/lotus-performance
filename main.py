# main.py
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import orjson
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from app.api.endpoints import (
    contribution,
    health,
    integration_capabilities,
    lineage,
    performance,
    returns_series,
)
from app.core.config import get_settings
from app.core.exceptions import PerformanceCalculatorError
from app.core.handlers import performance_calculator_exception_handler
from app.enterprise_readiness import build_enterprise_audit_middleware, validate_enterprise_runtime_config
from app.observability import setup_observability
from app.openapi_enrichment import enrich_openapi_schema


# --- FIX START: Create a robust custom JSON response class ---
def _clean_none_from_dict(d: dict) -> dict:
    """Recursively removes keys with None values from a dictionary."""
    out = {}
    for k, v in d.items():
        if v is not None:
            if isinstance(v, dict):
                out[k] = _clean_none_from_dict(v)
            elif isinstance(v, list):
                out[k] = _clean_none_from_list(v)
            else:
                out[k] = v
    return out


def _clean_none_from_list(items: list) -> list:
    """Recursively removes None values from lists and dicts within lists."""
    out = []
    for v in items:
        if v is not None:
            if isinstance(v, dict):
                out.append(_clean_none_from_dict(v))
            elif isinstance(v, list):
                out.append(_clean_none_from_list(v))
            else:
                out.append(v)
    return out


class ORJSONResponseExcludeNull(JSONResponse):
    def render(self, content: Any) -> bytes:
        """
        Serializes content to JSON using orjson, after removing null values.
        """
        # jsonable_encoder handles Pydantic models, datetimes, etc.
        encoded_content = jsonable_encoder(content)

        # Recursively remove None values
        if isinstance(encoded_content, dict):
            cleaned_content = _clean_none_from_dict(encoded_content)
        elif isinstance(encoded_content, list):
            cleaned_content = _clean_none_from_list(encoded_content)
        else:
            cleaned_content = encoded_content

        return orjson.dumps(cleaned_content)


# --- FIX END ---


settings = get_settings()


@asynccontextmanager
async def _app_lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.is_draining = False
    yield
    application.state.is_draining = True


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
    default_response_class=ORJSONResponseExcludeNull,  # Set as the default for the app
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
validate_enterprise_runtime_config()
app.middleware("http")(build_enterprise_audit_middleware())

# Create lineage directory if it doesn't exist
if not os.path.exists(settings.LINEAGE_STORAGE_PATH):
    os.makedirs(settings.LINEAGE_STORAGE_PATH)

app.mount("/lineage", StaticFiles(directory=settings.LINEAGE_STORAGE_PATH), name="lineage_files")

app.add_exception_handler(PerformanceCalculatorError, performance_calculator_exception_handler)

# Add a prefix to group performance-related endpoints
app.include_router(performance.router, prefix="/performance")
app.include_router(contribution.router, prefix="/performance")
app.include_router(lineage.router, prefix="/performance")
app.include_router(integration_capabilities.router, prefix="/integration")
app.include_router(returns_series.router, prefix="/integration")
app.include_router(health.router)


@app.get("/")
async def root():
    """Provides a welcome message and a link to the API documentation."""
    return {"message": "Welcome to the Portfolio Performance Analytics API. Access /docs for API documentation."}
