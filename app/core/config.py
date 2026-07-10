# app/core/config.py

from decimal import getcontext
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Portfolio Performance Analytics API"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "API for calculating portfolio performance metrics."
    APP_GIT_COMMIT_SHA: str = "local"
    APP_GIT_BRANCH: str = "local"
    APP_BUILD_TIMESTAMP: str = "local"
    APP_REPOSITORY_URL: str = "https://github.com/sgajbi/lotus-performance"
    APP_IMAGE_DIGEST: str = "unavailable-before-push"
    APP_CI_PIPELINE_RUN_ID: str = "local"
    LOG_LEVEL: str = "INFO"
    decimal_precision: int = 28
    HTTP_ALLOWED_HOSTS: str = "testserver,localhost,127.0.0.1,host.docker.internal,*.dev.lotus"
    CORS_ALLOWED_ORIGINS: str = (
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"
    )
    HTTP_SECURITY_HSTS_ENABLED: bool = False
    HTTP_SECURITY_HSTS_MAX_AGE_SECONDS: int = 31536000
    LINEAGE_STORAGE_PATH: Path = Path("lineage_data")
    LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED: bool = True
    DURABLE_READINESS_TIMEOUT_SECONDS: float = 2.0
    RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES: int = 0
    RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO: float = 0.0
    RECOVERY_DRILL_ARTIFACT_PATH: Path = Path("artifacts/durable-recovery-drill")
    LINEAGE_METADATA_DATABASE_URL: str = "sqlite:///./lineage_metadata.db"
    DURABLE_DB_CONNECT_TIMEOUT_SECONDS: int = Field(default=5, ge=1)
    DURABLE_DB_POOL_PRE_PING: bool = True
    DURABLE_DB_POOL_SIZE: int = Field(default=5, ge=1)
    DURABLE_DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    DURABLE_DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=0)
    DURABLE_DB_STATEMENT_TIMEOUT_MS: int = Field(default=30000, ge=0)
    DURABLE_DB_LOCK_TIMEOUT_MS: int = Field(default=5000, ge=0)
    DURABLE_DB_SQLITE_BUSY_TIMEOUT_MS: int = Field(default=5000, ge=0)
    LINEAGE_WORKER_POLL_SECONDS: float = 1.0
    LINEAGE_WORKER_BATCH_SIZE: int = 20
    LINEAGE_WORKER_MAX_ATTEMPTS: int = 3
    LINEAGE_WORKER_LEASE_SECONDS: int = 60
    LINEAGE_WORKER_ID: str = "lineage-worker-1"
    CORE_CONTROL_PLANE_BASE_URL: str | None = "http://core-control.dev.lotus"
    CORE_QUERY_BASE_URL: str | None = None
    CORE_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0.0)
    CORE_MAX_RETRIES: int = Field(default=2, ge=0)
    CORE_RETRY_BACKOFF_SECONDS: float = Field(default=0.2, ge=0.0)
    UPSTREAM_HTTP_MAX_CONNECTIONS: int = Field(default=100, gt=0)
    UPSTREAM_HTTP_MAX_KEEPALIVE_CONNECTIONS: int = Field(default=20, ge=0)
    UPSTREAM_HTTP_KEEPALIVE_EXPIRY_SECONDS: float = Field(default=30.0, gt=0.0)
    LOTUS_AI_BASE_URL: str | None = None
    LOTUS_AI_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0.0)
    LOTUS_AI_MAX_RETRIES: int = Field(default=2, ge=0)
    LOTUS_AI_RETRY_BACKOFF_SECONDS: float = Field(default=0.2, ge=0.0)
    LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT: str = "DEVELOPMENT"
    STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS: int = 90
    STATEFUL_INPUT_REFERENCE_CHUNK_DAYS: int = 365
    STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS: int = 4
    STATEFUL_INPUT_MAX_PAGES_PER_CHUNK: int = 25
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
    RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS: float = 0.0
    RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT: int = 0
    RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS: float = 0.0
    RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS: float = 0.0
    RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT: int = 0
    RUNTIME_STATUS_RECENT_RECOVERY_LIMIT: int = 5
    RUNTIME_RETENTION_DAYS: int = 30
    RUNTIME_RETENTION_ARTIFACT_PATH: Path = Path("artifacts/runtime-retention-cleanup")
    RUNTIME_RETENTION_LEGAL_HOLD_PATH: Path = Path("artifacts/runtime-retention-holds/legal-holds.json")
    RUNTIME_RETENTION_HISTORY_LIMIT: int = 30
    RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS: int = 90
    RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID: str = "runtime-retention-automation"
    RUNTIME_RETENTION_AUTOMATION_JOB_ID: str = "runtime-retention-scheduled"
    RUNTIME_RETENTION_WORKER_POLL_SECONDS: float = 3600.0
    RUNTIME_RETENTION_WORKER_APPLY: bool = False
    RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS: float = 300.0
    RUNTIME_RETENTION_APPLY_PREVIEW_MAX_AGE_SECONDS: float = 3600.0
    RUNTIME_RETENTION_ACTION_LEASE_STALE_SECONDS: float = 3600.0
    RETURNS_SERIES_EXECUTOR_WINDOW_DAYS: int = 180
    RETURNS_SERIES_EXECUTOR_INPUT_COUNT: int = 250
    TWR_EXECUTOR_WINDOW_DAYS: int = 180
    TWR_EXECUTOR_INPUT_COUNT: int = 250
    WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS: int = 180
    WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT: int = 250
    BENCHMARK_EXECUTOR_WINDOW_DAYS: int = 180
    BENCHMARK_EXECUTOR_INPUT_COUNT: int = 250
    CONTRIBUTION_EXECUTOR_WINDOW_DAYS: int = 180
    CONTRIBUTION_EXECUTOR_POSITION_COUNT: int = 250
    CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE: str = "OFF"
    ATTRIBUTION_EXECUTOR_WINDOW_DAYS: int = 180
    ATTRIBUTION_EXECUTOR_INPUT_COUNT: int = 250
    RECOVERY_DRILL_RETENTION_LIMIT: int = 30
    RECOVERY_DRILL_RETENTION_MAX_AGE_DAYS: int = 90
    RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS: float = 300.0
    RECOVERY_DRILL_ACTION_LEASE_STALE_SECONDS: float = 3600.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def resolved_core_control_plane_base_url(self) -> str:
        return self.CORE_CONTROL_PLANE_BASE_URL or self.CORE_QUERY_BASE_URL or "http://core-control.dev.lotus"


@lru_cache()
def get_settings():
    """
    Caches the settings object for efficient access.
    Initializes Decimal context precision here as it's a global setting for Decimal operations.
    """
    settings = Settings()
    getcontext().prec = settings.decimal_precision
    return settings
