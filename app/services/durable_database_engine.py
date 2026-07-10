from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class DurableDatabaseEnginePolicy:
    connect_timeout_seconds: int
    pool_pre_ping: bool
    pool_size: int
    max_overflow: int
    pool_recycle_seconds: int
    statement_timeout_ms: int
    lock_timeout_ms: int
    sqlite_busy_timeout_ms: int


def durable_database_engine_policy_from_settings(settings: Settings | None = None) -> DurableDatabaseEnginePolicy:
    active_settings = settings or get_settings()
    return DurableDatabaseEnginePolicy(
        connect_timeout_seconds=active_settings.DURABLE_DB_CONNECT_TIMEOUT_SECONDS,
        pool_pre_ping=active_settings.DURABLE_DB_POOL_PRE_PING,
        pool_size=active_settings.DURABLE_DB_POOL_SIZE,
        max_overflow=active_settings.DURABLE_DB_MAX_OVERFLOW,
        pool_recycle_seconds=active_settings.DURABLE_DB_POOL_RECYCLE_SECONDS,
        statement_timeout_ms=active_settings.DURABLE_DB_STATEMENT_TIMEOUT_MS,
        lock_timeout_ms=active_settings.DURABLE_DB_LOCK_TIMEOUT_MS,
        sqlite_busy_timeout_ms=active_settings.DURABLE_DB_SQLITE_BUSY_TIMEOUT_MS,
    )


def durable_database_engine_kwargs(
    database_url: str,
    *,
    policy: DurableDatabaseEnginePolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or durable_database_engine_policy_from_settings()
    backend_name = make_url(database_url).get_backend_name()
    if backend_name == "sqlite":
        return {
            "connect_args": {
                "check_same_thread": False,
                "timeout": active_policy.sqlite_busy_timeout_ms / 1000,
            }
        }
    if backend_name == "postgresql":
        connect_args: dict[str, Any] = {
            "connect_timeout": active_policy.connect_timeout_seconds,
        }
        connection_options = _postgres_connection_options(database_url, active_policy)
        if connection_options:
            connect_args["options"] = connection_options
        return {
            "connect_args": connect_args,
            "pool_pre_ping": active_policy.pool_pre_ping,
            "pool_size": active_policy.pool_size,
            "max_overflow": active_policy.max_overflow,
            "pool_recycle": active_policy.pool_recycle_seconds,
        }
    return {}


def create_durable_database_engine(
    database_url: str,
    *,
    policy: DurableDatabaseEnginePolicy | None = None,
) -> Engine:
    return create_engine(
        database_url,
        future=True,
        **durable_database_engine_kwargs(database_url, policy=policy),
    )


def _postgres_statement_options(policy: DurableDatabaseEnginePolicy) -> str:
    options: list[str] = []
    if policy.statement_timeout_ms > 0:
        options.append(f"-c statement_timeout={policy.statement_timeout_ms}")
    if policy.lock_timeout_ms > 0:
        options.append(f"-c lock_timeout={policy.lock_timeout_ms}")
    return " ".join(options)


def _postgres_connection_options(database_url: str, policy: DurableDatabaseEnginePolicy) -> str:
    url_options = make_url(database_url).query.get("options")
    option_parts: list[str] = []
    if isinstance(url_options, tuple):
        option_parts.extend(str(option) for option in url_options if str(option).strip())
    elif url_options:
        option_parts.append(str(url_options))

    statement_options = _postgres_statement_options(policy)
    if statement_options:
        option_parts.append(statement_options)
    return " ".join(option_parts)
