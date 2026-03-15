import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

POSTGRES_RUNTIME_DATABASE_URL = os.getenv(
    "LOTUS_POSTGRES_PLAN_DATABASE_URL",
    "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance",
)
POSTGRES_RUNTIME_CONNECT_TIMEOUT_SECONDS = 3


def get_postgres_database_url() -> str:
    isolated_schema_name = f"lotus_perf_bench_{uuid4().hex}"
    engine = create_engine(
        POSTGRES_RUNTIME_DATABASE_URL,
        future=True,
        connect_args={"connect_timeout": POSTGRES_RUNTIME_CONNECT_TIMEOUT_SECONDS},
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT 1"))
            connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{isolated_schema_name}"')
    except OperationalError:
        pytest.skip(f"PostgreSQL runtime proof database unavailable at {POSTGRES_RUNTIME_DATABASE_URL}")
    finally:
        engine.dispose()
    database_url = make_url(POSTGRES_RUNTIME_DATABASE_URL)
    existing_options = database_url.query.get("options")
    search_path_option = f"-csearch_path={isolated_schema_name}"
    combined_options = f"{existing_options} {search_path_option}".strip() if existing_options else search_path_option
    return database_url.update_query_dict({"options": combined_options}).render_as_string(hide_password=False)
