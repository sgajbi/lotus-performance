"""Real populated legacy upgrade and database paired-sidecar guards."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.adapters.composite_result_candidate_records import CompositeResultCandidateModel
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services.async_result_store import AsyncResultModel
from tests.unit.services.composite_arithmetic_capture.test_capture import counts
from tests.unit.services.test_composite_result_candidates import _capture


def legacy_columns(store):
    with store._engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER trg_composite_candidate_capture_pair")
        for name in ("arithmetic_capture_json", "arithmetic_capture_digest"):
            connection.exec_driver_sql(f"ALTER TABLE composite_result_candidates DROP COLUMN {name}")


def test_populated_legacy_upgrade_preserves_exact_original_and_absent_sidecar(precision_inputs):
    store, results, _, _, principal = precision_inputs
    original = _capture(precision_inputs)
    legacy_columns(store)
    store.create_schema()
    store.verify_schema()
    assert (
        store.get_result_candidate(
            candidate_id=original["candidate_id"],
            tenant_id=principal.tenant_id,
            result_store=results,
            principal=principal,
        )
        == original
    )
    assert "arithmetic_capture" not in original
    with store._engine.connect() as connection:
        assert connection.execute(
            text("SELECT arithmetic_capture_json, arithmetic_capture_digest FROM composite_result_candidates")
        ).one() == (None, None)
    store.create_schema()
    assert counts(store) == (1, 1)


def test_half_migrated_schema_refuses_without_inventing_precision(precision_inputs):
    store = precision_inputs[0]
    _capture(precision_inputs)
    legacy_columns(store)
    with store._engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE composite_result_candidates ADD COLUMN arithmetic_capture_json TEXT NULL"
        )
    with pytest.raises(DurableSchemaMigrationRequiredError, match="half_upgrade"):
        store.create_schema()


@pytest.mark.parametrize("raw,digest", [(None, "sha256:" + "a" * 64), ("{}", None), ("{}", "bad")])
def test_database_pair_guard_rolls_back_new_original(precision_inputs, raw, digest):
    store = precision_inputs[0]
    _capture(precision_inputs)
    original_table, candidate_table = AsyncResultModel.__table__, CompositeResultCandidateModel.__table__
    with store._engine.connect() as connection:
        original = dict(connection.execute(select(original_table)).mappings().one())
        candidate = dict(connection.execute(select(candidate_table)).mappings().one())
    calculation_id = str(uuid4())
    original["calculation_id"] = candidate["calculation_id"] = calculation_id
    candidate.update(
        candidate_id=str(uuid4()),
        semantic_request_digest="sha256:" + "b" * 64,
        arithmetic_capture_json=raw,
        arithmetic_capture_digest=digest,
    )
    with pytest.raises(IntegrityError, match="capture pair"):
        with store._engine.begin() as connection:
            connection.execute(original_table.insert().values(**original))
            connection.execute(candidate_table.insert().values(**candidate))
    assert counts(store) == (1, 1)
