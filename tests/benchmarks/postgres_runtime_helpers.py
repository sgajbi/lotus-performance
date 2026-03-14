import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

POSTGRES_RUNTIME_DATABASE_URL = os.getenv(
    "LOTUS_POSTGRES_PLAN_DATABASE_URL",
    "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance",
)


def get_postgres_database_url() -> str:
    engine = create_engine(POSTGRES_RUNTIME_DATABASE_URL, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(f"PostgreSQL runtime proof database unavailable at {POSTGRES_RUNTIME_DATABASE_URL}")
    finally:
        engine.dispose()
    return POSTGRES_RUNTIME_DATABASE_URL
