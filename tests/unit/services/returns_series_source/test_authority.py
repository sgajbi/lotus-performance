"""Custody admission refuses claims that cannot share one durable authority."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from app.services.returns_series_source.custody import SourceCustodyClaim, SourceCustodyConflict
from app.services.returns_series_source.workflow import (
    _require_shared_database,
    _resolution_binding,
    active_compute_source_claim,
    enqueue_source_response,
)


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": ""},
        {"tenant_id": " tenant"},
        {"attempt_id": ""},
        {"attempt_id": "worker "},
        {"attempt_number": -1},
        {"attempt_number": True},
    ],
)
def test_claim_rejects_ambiguous_tenant_or_attempt(change):
    claim = SourceCustodyClaim(uuid4(), "tenant", "worker", 1)
    claim.validate()
    with pytest.raises(SourceCustodyConflict):
        replace(claim, **change).validate()


def test_atomic_custody_requires_shared_database_not_equal_memory_urls(tmp_path):
    first = create_engine(f"sqlite:///{tmp_path / 'first.db'}")
    same = create_engine(first.url)
    other = create_engine(f"sqlite:///{tmp_path / 'other.db'}")
    memory = create_engine("sqlite:///:memory:")
    separate_memory = create_engine("sqlite:///:memory:")
    try:
        _require_shared_database((first, same, first))
        _require_shared_database((memory, memory, memory))
        with pytest.raises(SourceCustodyConflict, match="one durable"):
            _require_shared_database((first, other, first))
        with pytest.raises(SourceCustodyConflict, match="Separate in-memory"):
            _require_shared_database((memory, separate_memory, memory))
    finally:
        for engine in (first, same, other, memory, separate_memory):
            engine.dispose()


def test_resolution_and_enqueue_refuse_cross_calculation_claim_before_using_store():
    claim = SourceCustodyClaim(uuid4(), "tenant", "worker", 1)
    token = active_compute_source_claim.set((None, claim))
    try:
        with pytest.raises(SourceCustodyConflict, match="execution claim"):
            _resolution_binding(uuid4())
        with pytest.raises(SourceCustodyConflict, match="enqueue claim"):
            enqueue_source_response(calculation_id=uuid4(), response_json="{}", inline_claim=None, stateful=True)
    finally:
        active_compute_source_claim.reset(token)
