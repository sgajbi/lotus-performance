"""Real SQLite adapters at registered API and worker startup boundaries."""

import pytest

from tests.durable_schema_startup_helpers import (
    ENTRYPOINTS,
    assert_read_only_restart,
    assert_startup_refusal,
    resolved_runtime_stores,
)


@pytest.fixture
def runtime_stores(tmp_path, monkeypatch):
    with resolved_runtime_stores(f"sqlite:///{tmp_path / 'startup.db'}", monkeypatch) as stores:
        yield stores


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("shape", ["empty", "missing_index"])
def test_startup_refuses_before_serving_polling_or_client_allocation(runtime_stores, monkeypatch, entrypoint, shape):
    assert_startup_refusal(runtime_stores, monkeypatch, entrypoint, shape)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_owner_applied_startup_and_restart_are_read_only(runtime_stores, entrypoint):
    assert_read_only_restart(runtime_stores, entrypoint)
