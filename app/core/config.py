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
    LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED: bool = True
    RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES: int = 0
    RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO: float = 0.0
    RECOVERY_DRILL_ARTIFACT_PATH: Path = Path("artifacts/durable-recovery-drill")
    LINEAGE_METADATA_DATABASE_URL: str = "sqlite:///./lineage_metadata.db"
    LINEAGE_WORKER_POLL_SECONDS: float = 1.0
    LINEAGE_WORKER_BATCH_SIZE: int = 20
    LINEAGE_WORKER_MAX_ATTEMPTS: int = 3
    LINEAGE_WORKER_LEASE_SECONDS: int = 60
    LINEAGE_WORKER_ID: str = "lineage-worker-1"
    CORE_QUERY_BASE_URL: str = "http://localhost:8201"
    CORE_TIMEOUT_SECONDS: float = 10.0
    CORE_MAX_RETRIES: int = 2
    CORE_RETRY_BACKOFF_SECONDS: float = 0.2
    STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS: int = 90
    STATEFUL_INPUT_REFERENCE_CHUNK_DAYS: int = 365
    STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS: int = 4
    COMPUTE_EXECUTOR_POLL_SECONDS: float = 1.0
    COMPUTE_EXECUTOR_BATCH_SIZE: int = 10
    COMPUTE_EXECUTOR_MAX_ATTEMPTS: int = 3
    COMPUTE_EXECUTOR_LEASE_SECONDS: int = 60
    COMPUTE_EXECUTOR_WORKER_ID: str = "compute-executor-1"
    RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS: float = 0.0
    RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS: float = 0.0
    RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS: float = 0.0
    RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT: int = 0
    RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT: int = 0
    RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT: int = 0
    RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS: float = 0.0
    RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS: float = 0.0
    RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT: int = 0
    RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT: int = 0
    RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS: float = 0.0
    RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS: float = 0.0
    RUNTIME_STATUS_RECENT_RECOVERY_LIMIT: int = 5
    RUNTIME_RETENTION_DAYS: int = 30
    RUNTIME_RETENTION_ARTIFACT_PATH: Path = Path("artifacts/runtime-retention-cleanup")
    RUNTIME_RETENTION_HISTORY_LIMIT: int = 30
    RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS: int = 90
    RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID: str = "runtime-retention-automation"
    RUNTIME_RETENTION_AUTOMATION_JOB_ID: str = "runtime-retention-scheduled"
    RUNTIME_RETENTION_WORKER_POLL_SECONDS: float = 3600.0
    RUNTIME_RETENTION_WORKER_APPLY: bool = False
    RETURNS_SERIES_EXECUTOR_WINDOW_DAYS: int = 180
    CONTRIBUTION_EXECUTOR_POSITION_COUNT: int = 250
    ATTRIBUTION_EXECUTOR_INPUT_COUNT: int = 250
    RECOVERY_DRILL_RETENTION_LIMIT: int = 30
    RECOVERY_DRILL_RETENTION_MAX_AGE_DAYS: int = 90

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
