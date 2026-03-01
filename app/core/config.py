# app/core/config.py

from decimal import getcontext
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Portfolio Performance Analytics API"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "API for calculating portfolio performance metrics."
    LOG_LEVEL: str = "INFO"
    decimal_precision: int = 28
    LINEAGE_STORAGE_PATH: Path = Path("lineage_data")
    CORE_QUERY_BASE_URL: str = "http://localhost:8201"
    CORE_TIMEOUT_SECONDS: float = 10.0
    CORE_MAX_RETRIES: int = 2
    CORE_RETRY_BACKOFF_SECONDS: float = 0.2

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings():
    """
    Caches the settings object for efficient access.
    Initializes Decimal context precision here as it's a global setting for Decimal operations.
    """
    settings = Settings()
    getcontext().prec = settings.decimal_precision
    return settings
