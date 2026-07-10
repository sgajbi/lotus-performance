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
