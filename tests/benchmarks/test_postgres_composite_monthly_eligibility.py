"""Owned PostgreSQL registered monthly custody/reopen controls; no capacity claim."""

import re

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url, owned_postgres_runtime_stores
from tests.integration.test_composite_monthly_eligibility_materialization_api import (
    exercise_registered_monthly_retention,
)


@pytest.mark.parametrize("source_available", [False, True])
def test_postgres_registered_monthly_custody_and_reopen(monkeypatch, source_available):
    url = get_postgres_database_url()
    schema = re.fullmatch(r"-csearch_path=(lotus_perf_bench_[0-9a-f]{32})", make_url(url).query["options"])
    assert schema is not None, "Cleanup requires exact owned schema provenance"
    engine = create_engine(url)
    try:
        monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
        assert apply_durable_schema(database_url=url).status == "passed"
        with owned_postgres_runtime_stores(url, monkeypatch):
            exercise_registered_monthly_retention(monkeypatch, url, source_available=source_available)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema.group(1)}" CASCADE')
            assert not inspect(connection).has_schema(schema.group(1))
        engine.dispose()
