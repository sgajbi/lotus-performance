"""Registered configuration parity on the existing isolated PostgreSQL schema owner."""

import pytest

from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
from tests.integration import test_composite_attribution_deployment as contracts
from tests.integration.test_composite_attribution_api import attribution_runtime

__all__ = ["attribution_runtime"]


@pytest.fixture
def attribution_database_url():
    return get_postgres_database_url()


def test_postgres_registered_deployment_effects_and_replay(attribution_runtime, tmp_path, monkeypatch):
    contracts.test_registered_configuration_bootstrap_executes_all_or17_cells_and_retained_replay(
        attribution_runtime, tmp_path, monkeypatch
    )


def test_postgres_registered_deployment_source_refusal(attribution_runtime, tmp_path, monkeypatch):
    contracts.test_registered_configuration_refuses_scope_before_job_registration(
        attribution_runtime, tmp_path, monkeypatch
    )
