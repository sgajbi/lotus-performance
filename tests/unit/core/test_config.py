import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("CORE_TIMEOUT_SECONDS", 0),
        ("CORE_MAX_RETRIES", -1),
        ("CORE_RETRY_BACKOFF_SECONDS", -0.1),
        ("UPSTREAM_HTTP_MAX_CONNECTIONS", 0),
        ("UPSTREAM_HTTP_MAX_KEEPALIVE_CONNECTIONS", -1),
        ("UPSTREAM_HTTP_KEEPALIVE_EXPIRY_SECONDS", 0),
        ("LOTUS_AI_TIMEOUT_SECONDS", 0),
        ("LOTUS_AI_MAX_RETRIES", -1),
        ("LOTUS_AI_RETRY_BACKOFF_SECONDS", -0.1),
    ],
)
def test_settings_reject_invalid_upstream_resilience_controls(field_name, invalid_value):
    with pytest.raises(ValidationError) as error_info:
        Settings(**{field_name: invalid_value})

    assert field_name in str(error_info.value)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("CORE_TIMEOUT_SECONDS", "0"),
        ("CORE_MAX_RETRIES", "-1"),
        ("UPSTREAM_HTTP_MAX_CONNECTIONS", "0"),
        ("LOTUS_AI_TIMEOUT_SECONDS", "0"),
    ],
)
def test_settings_reject_invalid_upstream_resilience_env_values(monkeypatch, field_name, invalid_value):
    monkeypatch.setenv(field_name, invalid_value)

    with pytest.raises(ValidationError) as error_info:
        Settings()

    assert field_name in str(error_info.value)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("LINEAGE_WORKER_POLL_SECONDS", 0),
        ("LINEAGE_WORKER_BATCH_SIZE", 0),
        ("LINEAGE_WORKER_MAX_ATTEMPTS", 0),
        ("LINEAGE_WORKER_LEASE_SECONDS", -1),
        ("COMPUTE_EXECUTOR_POLL_SECONDS", 0),
        ("COMPUTE_EXECUTOR_BATCH_SIZE", 0),
        ("COMPUTE_EXECUTOR_MAX_ATTEMPTS", 0),
        ("COMPUTE_EXECUTOR_LEASE_SECONDS", -5),
        ("RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS", -1),
        ("RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", -1),
        ("RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", -0.1),
        ("RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 1.1),
        ("RUNTIME_STATUS_RECENT_RECOVERY_LIMIT", 0),
        ("RUNTIME_RETENTION_DAYS", 0),
        ("RUNTIME_RETENTION_HISTORY_LIMIT", -2),
        ("RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS", 0),
        ("RUNTIME_RETENTION_WORKER_POLL_SECONDS", 0),
        ("RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS", 0),
        ("RUNTIME_RETENTION_APPLY_PREVIEW_MAX_AGE_SECONDS", -1),
        ("RUNTIME_RETENTION_ACTION_LEASE_STALE_SECONDS", 0),
        ("RECOVERY_DRILL_RETENTION_LIMIT", -3),
        ("RECOVERY_DRILL_RETENTION_MAX_AGE_DAYS", 0),
        ("RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS", 0),
        ("RECOVERY_DRILL_ACTION_LEASE_STALE_SECONDS", -1),
        ("STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS", 0),
        ("STATEFUL_INPUT_REFERENCE_CHUNK_DAYS", 0),
        ("STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS", 0),
        ("STATEFUL_INPUT_MAX_PAGES_PER_CHUNK", 0),
        ("RETURNS_SERIES_EXECUTOR_WINDOW_DAYS", 0),
        ("RETURNS_SERIES_EXECUTOR_INPUT_COUNT", -10),
        ("TWR_EXECUTOR_WINDOW_DAYS", 0),
        ("TWR_EXECUTOR_INPUT_COUNT", 0),
        ("WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS", 0),
        ("WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT", 0),
        ("BENCHMARK_EXECUTOR_WINDOW_DAYS", 0),
        ("BENCHMARK_EXECUTOR_INPUT_COUNT", 0),
        ("CONTRIBUTION_EXECUTOR_WINDOW_DAYS", 0),
        ("CONTRIBUTION_EXECUTOR_POSITION_COUNT", 0),
        ("ATTRIBUTION_EXECUTOR_WINDOW_DAYS", 0),
        ("ATTRIBUTION_EXECUTOR_INPUT_COUNT", 0),
    ],
)
def test_settings_reject_invalid_runtime_numeric_controls(field_name, invalid_value):
    with pytest.raises(ValidationError) as error_info:
        Settings(**{field_name: invalid_value})

    assert field_name in str(error_info.value)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("LINEAGE_WORKER_BATCH_SIZE", "0"),
        ("COMPUTE_EXECUTOR_LEASE_SECONDS", "-5"),
        ("RUNTIME_RETENTION_HISTORY_LIMIT", "-2"),
        ("RECOVERY_DRILL_RETENTION_LIMIT", "-3"),
        ("STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS", "0"),
        ("RETURNS_SERIES_EXECUTOR_INPUT_COUNT", "-10"),
    ],
)
def test_settings_reject_invalid_runtime_numeric_env_values(monkeypatch, field_name, invalid_value):
    monkeypatch.setenv(field_name, invalid_value)

    with pytest.raises(ValidationError) as error_info:
        Settings()

    assert field_name in str(error_info.value)


def test_settings_preserve_valid_resilience_defaults():
    settings = Settings()

    assert settings.CORE_TIMEOUT_SECONDS == 10.0
    assert settings.CORE_MAX_RETRIES == 2
    assert settings.CORE_RETRY_BACKOFF_SECONDS == 0.2
    assert settings.UPSTREAM_HTTP_MAX_CONNECTIONS == 100
    assert settings.UPSTREAM_HTTP_MAX_KEEPALIVE_CONNECTIONS == 20
    assert settings.UPSTREAM_HTTP_KEEPALIVE_EXPIRY_SECONDS == 30.0
    assert settings.LOTUS_AI_TIMEOUT_SECONDS == 10.0
    assert settings.LOTUS_AI_MAX_RETRIES == 2
    assert settings.LOTUS_AI_RETRY_BACKOFF_SECONDS == 0.2
