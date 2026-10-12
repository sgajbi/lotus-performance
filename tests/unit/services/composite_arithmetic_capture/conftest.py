"""Owned durable input fixture shared by capture and migration controls."""

import pytest

from tests.unit.services.test_composite_result_candidates import build_candidate_inputs


@pytest.fixture
def precision_inputs(tmp_path, monkeypatch):
    inputs = build_candidate_inputs(f"sqlite:///{tmp_path / 'precision.db'}", monkeypatch)
    yield inputs
    inputs[0].close()
    inputs[1]._engine.dispose()
