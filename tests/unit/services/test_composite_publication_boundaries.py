"""Publication authority and schema refusal contracts without executing database DDL."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import composite_metadata_store as metadata


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "U1D", "ÜSD"])
def test_publication_rejects_noncanonical_reporting_currency(currency):
    with pytest.raises(ValueError, match="canonical"):
        metadata._validate_publication_identity_fields(
            reporting_currency=currency, restatement_sequence=1, source_fingerprint="source"
        )
    metadata._validate_publication_identity_fields(
        reporting_currency="USD", restatement_sequence=1, source_fingerprint="source"
    )


def test_publication_completion_requires_exact_source_declared_universe():
    family = ("member", date(2026, 1, 1), date(2026, 1, 31))
    metadata._require_exact_publication_families(
        actual_families={family}, expected_families={family}, restatement_sequence=1
    )
    for actual, expected in ((set(), {family}), ({family}, set())):
        with pytest.raises(metadata.CompositeMemberReturnFactSelectionError, match="exact source-declared"):
            metadata._require_exact_publication_families(
                actual_families=actual, expected_families=expected, restatement_sequence=1
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_families_json", "[]"),
        ("source_fingerprint", "changed"),
        ("period_start", date(2025, 1, 1)),
        ("period_end", date(2027, 1, 1)),
    ],
)
def test_completed_publication_retry_cannot_change_universe_lineage_or_window(field, value):
    args = dict(
        expected_families_json='["member"]',
        source_fingerprint="source",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    row = SimpleNamespace(**args)
    metadata._accept_idempotent_publication_or_raise_conflict(row, **args, restatement_sequence=1)
    setattr(row, field, value)
    with pytest.raises(metadata.CompositeMemberReturnFactConflictError, match="different"):
        metadata._accept_idempotent_publication_or_raise_conflict(row, **args, restatement_sequence=1)


def test_bootstrap_refuses_to_invent_missing_publication_lineage(monkeypatch):
    connection, inspector = Mock(), Mock()
    monkeypatch.setattr(metadata, "inspect", lambda connection: inspector)
    inspector.get_columns.return_value = []
    with pytest.raises(RuntimeError, match="cannot invent lineage authority"):
        metadata._require_publication_lineage_columns(connection)
    connection.execute.assert_not_called()
    inspector.get_columns.return_value = [{"name": key} for key in metadata.PUBLICATION_REQUIRED_LINEAGE_COLUMNS]
    metadata._require_publication_lineage_columns(connection)


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_additive_fact_and_publication_migration_never_rewrites_existing_columns(monkeypatch, dialect):
    connection, inspector = Mock(), Mock()
    connection.dialect.name = dialect
    monkeypatch.setattr(metadata, "inspect", lambda connection: inspector)
    inspector.get_columns.return_value = []
    metadata._add_missing_publication_columns(connection)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements and all("ADD COLUMN" in value and "DROP" not in value for value in statements)
    if dialect == "postgresql":
        assert all("IF NOT EXISTS" in value for value in statements)
    connection.reset_mock()
    inspector.get_columns.return_value = [{"name": key} for key in metadata.PUBLICATION_SCHEMA_UPGRADE_COLUMNS]
    metadata._add_missing_publication_columns(connection)
    connection.execute.assert_not_called()
    metadata._add_missing_member_return_fact_columns(connection, set())
    assert connection.execute.call_count > 0


def test_postgres_fact_chronology_hardening_preserves_labels_and_positive_default():
    connection = Mock()
    columns = dict(
        restatement_version=dict(type=SimpleNamespace(length=64), nullable=True),
        restatement_sequence=dict(default=None, nullable=True),
        reporting_currency=dict(nullable=False),
    )
    metadata._harden_postgres_member_return_fact_columns(connection, columns)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert len(statements) == 3
    assert sum("SET NOT NULL" in value for value in statements) == 2
    assert any("SET DEFAULT 1" in value for value in statements)
    assert all("UPDATE" not in value and "DELETE" not in value for value in statements)
    connection.reset_mock()
    columns["restatement_version"]["nullable"] = False
    columns["restatement_sequence"].update(default="1", nullable=False)
    metadata._harden_postgres_member_return_fact_columns(connection, columns)
    connection.execute.assert_not_called()


def test_postgres_publication_lineage_nullability_hardening_is_idempotent():
    keys = (
        "restatement_sequence",
        "reporting_currency",
        "period_start",
        "period_end",
        "expected_families_json",
        "source_fingerprint",
    )
    connection = Mock()
    metadata._make_postgres_publication_columns_non_nullable(connection, {key: dict(nullable=True) for key in keys})
    assert connection.execute.call_count == len(keys)
    assert all("SET NOT NULL" in str(call.args[0]) for call in connection.execute.call_args_list)
    connection.reset_mock()
    metadata._make_postgres_publication_columns_non_nullable(connection, {key: dict(nullable=False) for key in keys})
    connection.execute.assert_not_called()


def test_unparseable_constraint_and_wrong_dialect_guards_refuse(monkeypatch):
    def invalid(*args, **kwargs):
        raise ValueError("unrecognized predicate")

    monkeypatch.setattr(metadata, "predicate_identity", invalid)
    assert not metadata._postgres_check_is_current("unknown", "restatement_sequence > 0")
    connection = Mock()
    connection.dialect.name = "postgresql"
    with pytest.raises(RuntimeError, match="SQLite connection"):
        metadata._create_sqlite_composite_fact_validation_guards(connection)
    connection.exec_driver_sql.assert_not_called()
