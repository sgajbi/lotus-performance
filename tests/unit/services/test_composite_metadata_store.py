from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import String, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.models.composites import (
    CompositeDefinition,
    CompositeMemberReturnFact,
    CompositeMembership,
    CompositeReturnView,
)
from app.observability import tenant_id_var
from app.services import composite_metadata_store as composite_metadata_store_module
from app.services.composite_metadata_store import (
    INVALID_COMPOSITE_REASON_CODES_PAYLOAD,
    MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER,
    MEMBER_RETURN_FACT_IMMUTABLE_UPDATE_TRIGGER,
    MEMBER_RETURN_FACT_SCHEMA_UPGRADE_COLUMNS,
    PUBLICATION_IMMUTABLE_UPDATE_TRIGGER,
    CompositeDefinitionModel,
    CompositeMemberReturnFactConflictError,
    CompositeMemberReturnFactModel,
    CompositeMemberReturnFactSelectionError,
    CompositeMembershipModel,
    CompositeMetadataStore,
    CompositeTenantMigrationRequiredError,
    _definition_key,
    _fact_key,
    _member_return_fact_model,
    _missing_member_return_fact_schema_upgrade_columns,
    _publication_key,
)


@pytest.fixture(autouse=True)
def _admitted_composite_tenant():
    token = tenant_id_var.set("test-tenant")
    try:
        yield
    finally:
        tenant_id_var.reset(token)


def _store(tmp_path) -> CompositeMetadataStore:
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'composite_metadata.db'}")
    store.create_schema()
    store.upsert_definition(_definition())
    return store


def _drop_sqlite_guard_for_restore_fixture(
    store: CompositeMetadataStore,
    trigger_name: str,
) -> None:
    """Permit an impossible restored-state fixture while production writes remain fenced."""

    with store._engine.begin() as connection:
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger_name}")


def test_postgres_mapped_fact_schema_declares_source_owned_version_check():
    ddl = str(CreateTable(CompositeMemberReturnFactModel.__table__).compile(dialect=postgresql.dialect()))
    assert composite_metadata_store_module.MEMBER_RETURN_FACT_VERSION_CHECK in ddl
    assert composite_metadata_store_module.POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL in ddl


@pytest.mark.parametrize(
    "installed, expected",
    [
        ("a AND (b OR c)", "(a AND b) OR c"),
        ("reporting_currency = 'usd'", "reporting_currency = 'USD'"),
    ],
)
def test_postgres_owner_does_not_accept_changed_grouping_or_literal(installed, expected):
    assert not composite_metadata_store_module._postgres_check_is_current(installed, expected)


def test_postgres_upgrade_replaces_all_legacy_same_named_publication_constraints(monkeypatch):
    inspector = Mock()
    inspector.get_columns.return_value = [
        {"name": column_name, "nullable": False}
        for column_name in (
            "reporting_currency",
            "restatement_sequence",
            "period_start",
            "period_end",
            "expected_families_json",
            "source_fingerprint",
        )
    ]
    inspector.get_check_constraints.return_value = [
        {
            "name": composite_metadata_store_module.PUBLICATION_CURRENCY_CHECK,
            "sqltext": "length(reporting_currency) = 3",
        },
        {
            "name": composite_metadata_store_module.PUBLICATION_SEQUENCE_CHECK,
            "sqltext": "restatement_sequence >= 0",
        },
        {
            "name": composite_metadata_store_module.PUBLICATION_PERIOD_CHECK,
            "sqltext": "period_end >= period_start",
        },
    ]
    monkeypatch.setattr(composite_metadata_store_module, "inspect", lambda _connection: inspector)
    connection = Mock()

    composite_metadata_store_module._upgrade_postgres_publication_constraints(connection)

    executed_sql = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert executed_sql == [
        "ALTER TABLE composite_member_return_fact_publications "
        "DROP CONSTRAINT ck_composite_fact_publications_reporting_currency_canonical",
        "ALTER TABLE composite_member_return_fact_publications "
        "DROP CONSTRAINT ck_composite_fact_publications_restatement_sequence_positive",
        "ALTER TABLE composite_member_return_fact_publications "
        "DROP CONSTRAINT ck_composite_fact_publications_period_valid",
        "ALTER TABLE composite_member_return_fact_publications "
        "ADD CONSTRAINT ck_composite_fact_publications_reporting_currency_canonical CHECK ("
        "length(reporting_currency) = 3 AND reporting_currency = upper(reporting_currency) "
        "AND substr(reporting_currency, 1, 1) BETWEEN 'A' AND 'Z' "
        "AND substr(reporting_currency, 2, 1) BETWEEN 'A' AND 'Z' "
        "AND substr(reporting_currency, 3, 1) BETWEEN 'A' AND 'Z')",
        "ALTER TABLE composite_member_return_fact_publications "
        "ADD CONSTRAINT ck_composite_fact_publications_restatement_sequence_positive CHECK ("
        "restatement_sequence >= 1)",
        "ALTER TABLE composite_member_return_fact_publications "
        "ADD CONSTRAINT ck_composite_fact_publications_period_valid CHECK ("
        "period_start >= '0001-01-01' AND period_end <= '9999-12-31' "
        "AND period_end >= period_start)",
    ]


def test_postgres_upgrade_preserves_canonical_publication_constraints(monkeypatch):
    inspector = Mock()
    inspector.get_columns.return_value = [
        {"name": column_name, "nullable": False}
        for column_name in (
            "reporting_currency",
            "restatement_sequence",
            "period_start",
            "period_end",
            "expected_families_json",
            "source_fingerprint",
        )
    ]
    inspector.get_check_constraints.return_value = [
        {
            "name": composite_metadata_store_module.PUBLICATION_CURRENCY_CHECK,
            "sqltext": (
                "length(reporting_currency::text) = 3 "
                "AND reporting_currency::text = upper(reporting_currency::text) "
                "AND substr(reporting_currency::text, 1, 1) >= 'A'::text "
                "AND substr(reporting_currency::text, 1, 1) <= 'Z'::text "
                "AND substr(reporting_currency::text, 2, 1) >= 'A'::text "
                "AND substr(reporting_currency::text, 2, 1) <= 'Z'::text "
                "AND substr(reporting_currency::text, 3, 1) >= 'A'::text "
                "AND substr(reporting_currency::text, 3, 1) <= 'Z'::text"
            ),
        },
        {
            "name": composite_metadata_store_module.PUBLICATION_SEQUENCE_CHECK,
            "sqltext": "(restatement_sequence >= 1)",
        },
        {
            "name": composite_metadata_store_module.PUBLICATION_PERIOD_CHECK,
            "sqltext": (
                "period_start >= '0001-01-01'::date AND period_end <= '9999-12-31'::date AND period_end >= period_start"
            ),
        },
    ]
    monkeypatch.setattr(composite_metadata_store_module, "inspect", lambda _connection: inspector)
    connection = Mock()

    composite_metadata_store_module._upgrade_postgres_publication_constraints(connection)

    connection.execute.assert_not_called()


def _postgres_fact_columns(*, reporting_currency_nullable: bool) -> list[dict[str, object]]:
    return [
        {"name": "restatement_version", "type": String(64), "nullable": False},
        {"name": "restatement_sequence", "default": "1", "nullable": False},
        {"name": "reporting_currency", "nullable": reporting_currency_nullable},
    ]


def test_postgres_fact_upgrade_replaces_stale_named_checks_and_hardens_currency(monkeypatch):
    inspector = Mock()
    inspector.get_columns.return_value = _postgres_fact_columns(reporting_currency_nullable=True)
    inspector.get_check_constraints.return_value = [
        {
            "name": composite_metadata_store_module.MEMBER_RETURN_FACT_CURRENCY_CHECK,
            "sqltext": "length(reporting_currency) = 3",
        },
        {
            "name": composite_metadata_store_module.MEMBER_RETURN_FACT_SEQUENCE_CHECK,
            "sqltext": "restatement_sequence >= 0",
        },
        {
            "name": composite_metadata_store_module.MEMBER_RETURN_FACT_VERSION_CHECK,
            "sqltext": composite_metadata_store_module.POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL,
        },
    ]
    monkeypatch.setattr(composite_metadata_store_module, "inspect", lambda _connection: inspector)
    connection = Mock()

    composite_metadata_store_module._upgrade_postgres_member_return_fact_constraints(connection)

    executed_sql = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert executed_sql == [
        "ALTER TABLE composite_member_return_facts ALTER COLUMN reporting_currency SET NOT NULL",
        "ALTER TABLE composite_member_return_facts "
        "DROP CONSTRAINT ck_composite_member_return_facts_reporting_currency_canonical",
        "ALTER TABLE composite_member_return_facts "
        "DROP CONSTRAINT ck_composite_member_return_facts_restatement_sequence_positive",
        "ALTER TABLE composite_member_return_facts "
        "ADD CONSTRAINT ck_composite_member_return_facts_reporting_currency_canonical CHECK ("
        "length(reporting_currency) = 3 AND reporting_currency = upper(reporting_currency) "
        "AND substr(reporting_currency, 1, 1) BETWEEN 'A' AND 'Z' "
        "AND substr(reporting_currency, 2, 1) BETWEEN 'A' AND 'Z' "
        "AND substr(reporting_currency, 3, 1) BETWEEN 'A' AND 'Z')",
        "ALTER TABLE composite_member_return_facts "
        "ADD CONSTRAINT ck_composite_member_return_facts_restatement_sequence_positive CHECK ("
        "restatement_sequence >= 1)",
    ]


def test_postgres_fact_upgrade_preserves_canonical_constraints_and_columns(monkeypatch):
    inspector = Mock()
    inspector.get_columns.return_value = _postgres_fact_columns(reporting_currency_nullable=False)
    inspector.get_check_constraints.return_value = [
        {
            "name": composite_metadata_store_module.MEMBER_RETURN_FACT_CURRENCY_CHECK,
            "sqltext": composite_metadata_store_module.POSTGRES_CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
        },
        {
            "name": composite_metadata_store_module.MEMBER_RETURN_FACT_SEQUENCE_CHECK,
            "sqltext": "restatement_sequence >= 1",
        },
        {
            "name": composite_metadata_store_module.MEMBER_RETURN_FACT_VERSION_CHECK,
            "sqltext": composite_metadata_store_module.POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL,
        },
    ]
    monkeypatch.setattr(composite_metadata_store_module, "inspect", lambda _connection: inspector)
    connection = Mock()

    composite_metadata_store_module._upgrade_postgres_member_return_fact_constraints(connection)

    connection.execute.assert_not_called()


def test_postgres_definition_upgrade_replaces_stale_named_currency_check(monkeypatch):
    inspector = Mock()
    inspector.get_columns.return_value = [{"name": "reporting_currency", "nullable": False}]
    inspector.get_check_constraints.return_value = [
        {
            "name": composite_metadata_store_module.COMPOSITE_DEFINITION_CURRENCY_CHECK,
            "sqltext": "length(reporting_currency) = 3",
        }
    ]
    monkeypatch.setattr(composite_metadata_store_module, "inspect", lambda _connection: inspector)
    connection = Mock()
    connection.dialect.name = "postgresql"

    composite_metadata_store_module._upgrade_postgres_definition_currency_constraint(connection)

    executed_sql = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert executed_sql == [
        "ALTER TABLE composite_definitions DROP CONSTRAINT ck_composite_definitions_reporting_currency_canonical",
        "ALTER TABLE composite_definitions "
        "ADD CONSTRAINT ck_composite_definitions_reporting_currency_canonical CHECK ("
        "length(reporting_currency) = 3 AND reporting_currency = upper(reporting_currency) "
        "AND substr(reporting_currency, 1, 1) BETWEEN 'A' AND 'Z' "
        "AND substr(reporting_currency, 2, 1) BETWEEN 'A' AND 'Z' "
        "AND substr(reporting_currency, 3, 1) BETWEEN 'A' AND 'Z')",
    ]


def test_postgres_definition_upgrade_preserves_canonical_currency_check(monkeypatch):
    inspector = Mock()
    inspector.get_columns.return_value = [{"name": "reporting_currency", "nullable": False}]
    inspector.get_check_constraints.return_value = [
        {
            "name": composite_metadata_store_module.COMPOSITE_DEFINITION_CURRENCY_CHECK,
            "sqltext": composite_metadata_store_module.POSTGRES_CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
        }
    ]
    monkeypatch.setattr(composite_metadata_store_module, "inspect", lambda _connection: inspector)
    connection = Mock()
    connection.dialect.name = "postgresql"

    composite_metadata_store_module._upgrade_postgres_definition_currency_constraint(connection)

    connection.execute.assert_not_called()


def test_sqlite_direct_publication_requires_exact_durable_families_and_fences_late_inserts(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition("DIRECT_SQL_PUBLICATION_FENCE"))
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "DIRECT_SQL_PUBLICATION_FENCE",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "direct-sql-fence-p1",
            "source_snapshot_id": "direct-sql-fence-p1",
            "source_fingerprint": "sha256:direct-sql-fence-p1",
        }
    )
    publication_insert = text(
        """
        INSERT INTO composite_member_return_fact_publications (
            publication_key, tenant_id, composite_id, return_view, reporting_currency,
            restatement_sequence, period_start, period_end, expected_families_json,
            source_fingerprint
        ) VALUES (
            :publication_key, 'test-tenant', :composite_id, :return_view, :reporting_currency,
            :restatement_sequence, :period_start, :period_end, :expected_families_json,
            'sha256:direct-publication'
        )
        """
    )
    direct_fact_insert = text(
        """
        INSERT INTO composite_member_return_facts (
            fact_key, tenant_id, composite_id, portfolio_id, period_start, period_end,
            return_value, return_view, beginning_market_value, ending_market_value,
            reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
            restatement_version, restatement_sequence, status, reason_codes_json
        ) VALUES (
            'direct-sql-fence-p2', 'test-tenant', :composite_id, 'P2', :period_start, :period_end,
            '0.02', :return_view, '100.00', '102.00', :reporting_currency,
            'direct-sql-fence-p2', 'direct-sql-fence-p2', 'sha256:direct-sql-fence-p2',
            'v1', :restatement_sequence, 'READY', '[]'
        )
        """
    )
    publication_values = {
        "publication_key": _publication_key(
            composite_id=fact.composite_id,
            return_view=fact.return_view,
            reporting_currency=fact.reporting_currency,
            restatement_sequence=fact.restatement_sequence,
        ),
        "composite_id": fact.composite_id,
        "return_view": fact.return_view.value,
        "reporting_currency": fact.reporting_currency,
        "restatement_sequence": fact.restatement_sequence,
        "period_start": fact.period_start,
        "period_end": fact.period_end,
    }
    try:
        store.upsert_member_return_fact(fact)
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(publication_insert, publication_values | {"expected_families_json": "[]"})

        with store._engine.begin() as connection:
            connection.execute(
                publication_insert,
                publication_values
                | {
                    "expected_families_json": (
                        '[{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"P1"}]'
                    )
                },
            )

        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(direct_fact_insert, publication_values)

        with store._engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT "
                "(SELECT count(*) FROM composite_member_return_facts "
                "WHERE composite_id = 'DIRECT_SQL_PUBLICATION_FENCE'), "
                "(SELECT count(*) FROM composite_member_return_fact_publications "
                "WHERE composite_id = 'DIRECT_SQL_PUBLICATION_FENCE')"
            ).one() == (1, 1)
    finally:
        store.close()


def test_sqlite_fresh_schema_rejects_invalid_direct_restatement_versions(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition("DIRECT_SQL"))
    invalid_versions = (
        ("direct-tab-only-version", "\t"),
        ("direct-newline-only-version", "\n"),
        ("direct-record-separator-only-version", "\x1e"),
        ("direct-nonbreaking-space-only-version", "\u00a0"),
        ("direct-em-space-only-version", "\u2003"),
        ("direct-overlong-version", "v" * 65),
    )
    try:
        direct_insert = text(
            """
            INSERT INTO composite_member_return_facts (
                fact_key, tenant_id, composite_id, portfolio_id, period_start, period_end,
                return_value, return_view, beginning_market_value, ending_market_value,
                reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
                restatement_version, restatement_sequence, status, reason_codes_json
            ) VALUES (
                :fact_key, 'test-tenant', 'DIRECT_SQL', 'P2', '2026-01-01', '2026-01-31',
                '0.01', 'NET_ACTUAL', '100.00', '101.00', 'USD', :fact_key,
                :fact_key, 'sha256:direct-invalid-version', :restatement_version,
                1, 'READY', '[]'
            )
            """
        )
        for fact_key, invalid_version in invalid_versions:
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        direct_insert,
                        {
                            "fact_key": fact_key,
                            "restatement_version": invalid_version,
                        },
                    )
        with store._engine.begin() as connection:
            connection.execute(
                direct_insert,
                {
                    "fact_key": "direct-valid-version",
                    "restatement_version": "v1",
                },
            )
        for _, invalid_version in invalid_versions:
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE composite_member_return_facts SET restatement_version = :restatement_version "
                            "WHERE fact_key = 'direct-valid-version'"
                        ),
                        {"restatement_version": invalid_version},
                    )
    finally:
        store.close()


def test_sqlite_fresh_schema_rejects_non_integer_direct_restatement_sequences(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition("DIRECT_SQL"))
    fact_insert = text(
        """
        INSERT INTO composite_member_return_facts (
            fact_key, tenant_id, composite_id, portfolio_id, period_start, period_end,
            return_value, return_view, beginning_market_value, ending_market_value,
            reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
            restatement_version, restatement_sequence, status, reason_codes_json
        ) VALUES (
            :fact_key, 'test-tenant', 'DIRECT_SQL', 'P2', '2026-01-01', '2026-01-31',
            '0.01', 'NET_ACTUAL', '100.00', '101.00', 'USD', :fact_key,
            :fact_key, 'sha256:direct-sequence', 'v1', :restatement_sequence,
            'READY', '[]'
        )
        """
    )
    publication_insert = text(
        """
        INSERT INTO composite_member_return_fact_publications (
            publication_key, tenant_id, composite_id, return_view, reporting_currency,
            restatement_sequence, period_start, period_end, expected_families_json,
            source_fingerprint
        ) VALUES (
            :publication_key, 'test-tenant', 'DIRECT_SQL', 'NET_ACTUAL', 'USD',
            :restatement_sequence, '2026-01-01', '2026-01-31', '[]',
            'sha256:direct-sequence'
        )
        """
    )
    try:
        for suffix, invalid_sequence in (("fractional", 1.5), ("text", "abc")):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        fact_insert,
                        {
                            "fact_key": f"direct-fact-{suffix}",
                            "restatement_sequence": invalid_sequence,
                        },
                    )
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        publication_insert,
                        {
                            "publication_key": f"direct-publication-{suffix}",
                            "restatement_sequence": invalid_sequence,
                        },
                    )

        with store._engine.begin() as connection:
            connection.execute(
                fact_insert,
                {"fact_key": "direct-valid-fact", "restatement_sequence": 1},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO composite_member_return_fact_publications (
                        publication_key, tenant_id, composite_id, return_view, reporting_currency,
                        restatement_sequence, period_start, period_end, expected_families_json,
                        source_fingerprint
                    ) VALUES (
                        'direct-valid-publication', 'test-tenant', 'DIRECT_SQL', 'NET_ACTUAL', 'USD', 1,
                        '2026-01-01', '2026-01-31',
                        '[{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"P2"}]',
                        'sha256:direct-sequence'
                    )
                    """
                )
            )
        for invalid_sequence in (1.5, "abc"):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE composite_member_return_facts "
                            "SET restatement_sequence = :restatement_sequence "
                            "WHERE fact_key = 'direct-valid-fact'"
                        ),
                        {"restatement_sequence": invalid_sequence},
                    )
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE composite_member_return_fact_publications "
                            "SET restatement_sequence = :restatement_sequence "
                            "WHERE publication_key = 'direct-valid-publication'"
                        ),
                        {"restatement_sequence": invalid_sequence},
                    )
    finally:
        store.close()


def test_sqlite_fresh_schema_rejects_invalid_direct_publication_dates(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition("DIRECT_SQL"))
    direct_insert = text(
        """
        INSERT INTO composite_member_return_fact_publications (
            publication_key, tenant_id, composite_id, return_view, reporting_currency,
            restatement_sequence, period_start, period_end, expected_families_json,
            source_fingerprint
        ) VALUES (
            :publication_key, 'test-tenant', 'DIRECT_SQL', 'NET_ACTUAL', 'USD', 1,
            :period_start, :period_end, '[]', 'sha256:direct-period'
        )
        """
    )
    invalid_periods = (
        ("invalid-bounds", "0000-00-00", "9999-99-99"),
        ("invalid-calendar-day", "2026-02-30", "2026-03-01"),
        ("invalid-year-zero", "0000-01-01", "2026-01-31"),
    )
    try:
        for publication_key, period_start, period_end in invalid_periods:
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        direct_insert,
                        {
                            "publication_key": publication_key,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )

        with store._engine.begin() as connection:
            connection.execute(
                direct_insert,
                {
                    "publication_key": "direct-valid-period",
                    "period_start": "2026-01-01",
                    "period_end": "2026-01-31",
                },
            )
        for _, period_start, period_end in invalid_periods:
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE composite_member_return_fact_publications "
                            "SET period_start = :period_start, period_end = :period_end "
                            "WHERE publication_key = 'direct-valid-period'"
                        ),
                        {"period_start": period_start, "period_end": period_end},
                    )
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE composite_member_return_fact_publications "
                        "SET period_start = '0001-01-01', period_end = '9999-12-31' "
                        "WHERE publication_key = 'direct-valid-period'"
                    )
                )
        with store._engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT period_start, period_end "
                "FROM composite_member_return_fact_publications "
                "WHERE publication_key = 'direct-valid-period'"
            ).one() == ("2026-01-01", "2026-01-31")
    finally:
        store.close()


def test_sqlite_upgraded_tables_reject_invalid_direct_identity_and_period_writes(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'upgraded_direct_guards.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_facts ("
            "fact_key VARCHAR(360) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "return_value TEXT NOT NULL, return_view VARCHAR(32) NOT NULL, "
            "beginning_market_value TEXT NOT NULL, ending_market_value TEXT NOT NULL, "
            "reporting_currency VARCHAR(3) NOT NULL, calculation_id VARCHAR(64) NOT NULL, "
            "source_snapshot_id VARCHAR(256) NOT NULL, source_fingerprint VARCHAR(256) NOT NULL, "
            "restatement_version VARCHAR(64) NOT NULL, restatement_sequence INTEGER NOT NULL, "
            "status VARCHAR(64) NOT NULL, reason_codes_json TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_fact_publications ("
            "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "restatement_sequence INTEGER NOT NULL, period_start DATE NOT NULL, "
            "period_end DATE NOT NULL, expected_families_json TEXT NOT NULL, "
            "source_fingerprint VARCHAR(256) NOT NULL)"
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    store.create_schema()
    store.upsert_definition(_definition("UPGRADED_DIRECT"))
    fact_insert = text(
        """
        INSERT INTO composite_member_return_facts (
            fact_key, tenant_id, composite_id, portfolio_id, period_start, period_end,
            return_value, return_view, beginning_market_value, ending_market_value,
            reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
            restatement_version, restatement_sequence, status, reason_codes_json
        ) VALUES (
            :fact_key, 'test-tenant', 'UPGRADED_DIRECT', 'P1', '2026-01-01', '2026-01-31',
            '0.01', 'NET_ACTUAL', '100.00', '101.00', :reporting_currency, :fact_key,
            :fact_key, 'sha256:upgraded-direct', :restatement_version, :restatement_sequence,
            'READY', '[]'
        )
        """
    )
    publication_insert = text(
        """
        INSERT INTO composite_member_return_fact_publications (
            publication_key, tenant_id, composite_id, return_view, reporting_currency,
            restatement_sequence, period_start, period_end, expected_families_json,
            source_fingerprint
        ) VALUES (
            :publication_key, 'test-tenant', 'UPGRADED_DIRECT', 'NET_ACTUAL', :reporting_currency,
            :restatement_sequence, :period_start, :period_end, '[]',
            'sha256:upgraded-direct'
        )
        """
    )
    valid_fact_fields = {"reporting_currency": "USD", "restatement_version": "v1"}
    valid_publication_fields = {"reporting_currency": "USD"}
    try:
        for suffix, invalid_sequence in (("fractional", 1.5), ("text", "abc")):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        fact_insert,
                        valid_fact_fields
                        | {
                            "fact_key": f"upgraded-fact-{suffix}",
                            "restatement_sequence": invalid_sequence,
                        },
                    )
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        publication_insert,
                        valid_publication_fields
                        | {
                            "publication_key": f"upgraded-publication-{suffix}",
                            "restatement_sequence": invalid_sequence,
                            "period_start": "2026-01-01",
                            "period_end": "2026-01-31",
                        },
                    )
        for suffix, period_start, period_end in (
            ("invalid-calendar-day", "2026-02-30", "2026-03-01"),
            ("invalid-year-zero", "0000-01-01", "2026-01-31"),
        ):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        publication_insert,
                        valid_publication_fields
                        | {
                            "publication_key": f"upgraded-publication-{suffix}",
                            "restatement_sequence": 1,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )

        for suffix, invalid_version in (
            ("blank-version", ""),
            ("tab-version", "\t"),
            ("unicode-space-version", "\u2003"),
            ("overlong-version", "v" * 65),
        ):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        fact_insert,
                        valid_fact_fields
                        | {
                            "fact_key": f"upgraded-fact-{suffix}",
                            "restatement_version": invalid_version,
                            "restatement_sequence": 1,
                        },
                    )
        for invalid_currency in ("usd", "US1"):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        fact_insert,
                        valid_fact_fields
                        | {
                            "fact_key": f"upgraded-fact-currency-{invalid_currency}",
                            "reporting_currency": invalid_currency,
                            "restatement_sequence": 1,
                        },
                    )
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        publication_insert,
                        valid_publication_fields
                        | {
                            "publication_key": f"upgraded-publication-currency-{invalid_currency}",
                            "reporting_currency": invalid_currency,
                            "restatement_sequence": 1,
                            "period_start": "2026-01-01",
                            "period_end": "2026-01-31",
                        },
                    )

        for suffix, expected_families_json, source_fingerprint in (
            ("malformed-json", "not-json", "sha256:upgraded-direct"),
            ("non-list-manifest", "{}", "sha256:upgraded-direct"),
            ("scalar-entry", '["not-an-object"]', "sha256:upgraded-direct"),
            (
                "missing-portfolio-id",
                '[{"extra":"P1","period_end":"2026-01-31","period_start":"2026-01-01"}]',
                "sha256:upgraded-direct",
            ),
            ("blob-manifest", b"[]", "sha256:upgraded-direct"),
            (
                "duplicate-family",
                '[{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"P1"},'
                '{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"P1"}]',
                "sha256:upgraded-direct",
            ),
            (
                "out-of-window",
                '[{"period_end":"2026-02-28","period_start":"2026-02-01","portfolio_id":"P1"}]',
                "sha256:upgraded-direct",
            ),
            ("blank-fingerprint", "[]", " \t"),
        ):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO composite_member_return_fact_publications ("
                            "publication_key, tenant_id, composite_id, return_view, reporting_currency, "
                            "restatement_sequence, period_start, period_end, expected_families_json, "
                            "source_fingerprint) VALUES ("
                            ":publication_key, 'test-tenant', 'UPGRADED_DIRECT', 'NET_ACTUAL', 'USD', 1, "
                            "'2026-01-01', '2026-01-31', :expected_families_json, :source_fingerprint)"
                        ),
                        {
                            "publication_key": f"upgraded-publication-lineage-{suffix}",
                            "expected_families_json": expected_families_json,
                            "source_fingerprint": source_fingerprint,
                        },
                    )

        with store._engine.begin() as connection:
            connection.execute(
                fact_insert,
                valid_fact_fields | {"fact_key": "upgraded-valid-fact", "restatement_sequence": 1},
            )
            connection.execute(
                text(
                    """
                        INSERT INTO composite_member_return_fact_publications (
                            publication_key, tenant_id, composite_id, return_view, reporting_currency,
                        restatement_sequence, period_start, period_end, expected_families_json,
                        source_fingerprint
                    ) VALUES (
                            'upgraded-valid-publication', 'test-tenant', 'UPGRADED_DIRECT', 'NET_ACTUAL', 'USD', 1,
                        '2026-01-01', '2026-01-31',
                        '[{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"P1"}]',
                        'sha256:upgraded-direct'
                    )
                    """
                )
            )
        for invalid_update in (
            "UPDATE composite_member_return_fact_publications SET restatement_sequence = 1.5 "
            "WHERE publication_key = 'upgraded-valid-publication'",
            "UPDATE composite_member_return_fact_publications SET period_start = '2026-02-30' "
            "WHERE publication_key = 'upgraded-valid-publication'",
            "UPDATE composite_member_return_fact_publications SET period_start = '0000-01-01' "
            "WHERE publication_key = 'upgraded-valid-publication'",
            "UPDATE composite_member_return_fact_publications "
            "SET period_start = '2026-02-01', period_end = '2026-01-31' "
            "WHERE publication_key = 'upgraded-valid-publication'",
            "UPDATE composite_member_return_fact_publications SET reporting_currency = 'usd' "
            "WHERE publication_key = 'upgraded-valid-publication'",
        ):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.exec_driver_sql(invalid_update)
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE composite_member_return_fact_publications "
                    "SET period_start = '2026-01-02' "
                    "WHERE publication_key = 'upgraded-valid-publication'"
                )
    finally:
        store.close()


def _complete_publication(
    store: CompositeMetadataStore,
    *facts: CompositeMemberReturnFact,
    source_fingerprint: str = "sha256:test-publication",
) -> None:
    assert facts
    first = facts[0]
    assert all(
        (fact.composite_id, fact.return_view, fact.reporting_currency, fact.restatement_sequence)
        == (first.composite_id, first.return_view, first.reporting_currency, first.restatement_sequence)
        for fact in facts
    )
    store.complete_member_return_fact_publication(
        composite_id=first.composite_id,
        return_view=first.return_view,
        reporting_currency=first.reporting_currency,
        restatement_sequence=first.restatement_sequence,
        period_start=min(fact.period_start for fact in facts),
        period_end=max(fact.period_end for fact in facts),
        expected_families={(fact.portfolio_id, fact.period_start, fact.period_end) for fact in facts},
        source_fingerprint=source_fingerprint,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"restatement_sequence": 0},
        {"source_fingerprint": " "},
        {"reporting_currency": "usd"},
        {"reporting_currency": "UŚD"},
        {"reporting_currency": "US"},
        {"period_start": date(2026, 2, 1)},
        {"expected_families": {("P1", date(2026, 1, 31), date(2026, 1, 1))}},
        {"expected_families": {("P1", date(2025, 12, 31), date(2026, 1, 31))}},
        {"expected_families": {("P1", date(2026, 1, 1), date(2026, 2, 1))}},
    ],
)
def test_publication_command_refuses_invalid_scope_without_changing_durable_records(tmp_path, changes):
    store = _store(tmp_path)
    request = {
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "return_view": CompositeReturnView.NET_ACTUAL,
        "reporting_currency": "USD",
        "restatement_sequence": 1,
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        "expected_families": set(),
        "source_fingerprint": "sha256:publication-control",
    }
    try:
        before = store.count_records()
        with pytest.raises(ValueError):
            store.complete_member_return_fact_publication(**(request | changes))
        assert store.count_records() == before
    finally:
        store.close()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "{}",
        "not JSON",
        "[null]",
        '[{"portfolio_id":"P1"}]',
        '[{"portfolio_id":" ","period_start":"2026-01-01","period_end":"2026-01-31"}]',
        '[{"portfolio_id":"P1","period_start":20260101,"period_end":"2026-01-31"}]',
        '[{"portfolio_id":"P1","period_start":"20260101","period_end":"2026-01-31"}]',
        '[{"portfolio_id":"P1","period_start":"2026-01-31","period_end":"2026-01-01"}]',
        '[{"portfolio_id":"P1","period_start":"2026-01-01","period_end":"2026-01-31"},'
        '{"portfolio_id":"P1","period_start":"2026-01-01","period_end":"2026-01-31"}]',
    ],
)
def test_restored_publication_family_manifest_refuses_ambiguous_or_malformed_evidence(payload):
    with pytest.raises(CompositeMemberReturnFactSelectionError):
        composite_metadata_store_module._deserialize_fact_families(payload)
    assert composite_metadata_store_module._deserialize_fact_families(
        '[{"portfolio_id":"P1","period_start":"2026-01-01","period_end":"2026-01-31"}]'
    ) == {("P1", date(2026, 1, 1), date(2026, 1, 31))}


def _definition(composite_id: str = "PB_GLOBAL_BALANCED_USD") -> CompositeDefinition:
    return CompositeDefinition.model_validate(
        {
            "composite_id": composite_id,
            "display_name": "Private Banking Global Balanced USD Composite",
            "strategy_code": "GLOBAL_BALANCED",
            "reporting_currency": "USD",
            "inception_date": "2026-01-01",
            "source_authority": {
                "definition_owner": "lotus-manage",
                "membership_owner": "lotus-manage",
                "member_return_owner": "lotus-performance",
                "asset_owner": "lotus-core",
                "benchmark_owner": "lotus-core",
                "policy_version": "composite-source-authority.v1",
            },
        }
    )


def test_completed_sqlite_fact_payload_is_immutable_to_direct_writers(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition("IMMUTABLE_COMPLETED_FACT"))
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "IMMUTABLE_COMPLETED_FACT",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "immutable-completed-fact",
            "source_snapshot_id": "immutable-completed-fact",
            "source_fingerprint": "sha256:immutable-completed-fact",
        }
    )
    try:
        store.upsert_member_return_fact(fact)
        _complete_publication(store, fact)

        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE composite_member_return_facts "
                        "SET return_value = '0.9900', ending_market_value = '199.00', "
                        "source_fingerprint = 'sha256:mutated' "
                        "WHERE calculation_id = 'immutable-completed-fact'"
                    )
                )
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE composite_member_return_fact_publications "
                        "SET period_start = '2025-12-01', expected_families_json = '[]', "
                        "source_fingerprint = 'sha256:mutated-publication' "
                        "WHERE composite_id = 'IMMUTABLE_COMPLETED_FACT'"
                    )
                )
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text(
                        "DELETE FROM composite_member_return_fact_publications "
                        "WHERE composite_id = 'IMMUTABLE_COMPLETED_FACT'"
                    )
                )
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM composite_member_return_facts WHERE calculation_id = 'immutable-completed-fact'")
                )

        assert store.list_member_return_facts(
            composite_id=fact.composite_id,
            period_start=fact.period_start,
            period_end=fact.period_end,
            return_view=fact.return_view,
            reporting_currency=fact.reporting_currency,
            restatement_sequence=fact.restatement_sequence,
        ) == [fact]
        store.clear_records_for_composites({fact.composite_id})
        assert store.count_records().member_return_facts == 0
    finally:
        store.close()


def test_missing_member_return_fact_schema_upgrade_columns_selects_only_absent_columns():
    missing_columns = _missing_member_return_fact_schema_upgrade_columns(
        {"fact_key", "composite_id", "portfolio_id", "return_view"}
    )

    assert missing_columns == {
        column_name: column_definition
        for column_name, column_definition in MEMBER_RETURN_FACT_SCHEMA_UPGRADE_COLUMNS.items()
        if column_name != "return_view"
    }


def test_publication_schema_upgrade_refuses_ownerless_rows_without_partial_changes(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'early_publication_schema.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_fact_publications ("
            "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "restatement_sequence INTEGER NOT NULL, expected_families_json TEXT NOT NULL, "
            "source_fingerprint VARCHAR(256) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_fact_publications VALUES "
            "('early', 'PB_GLOBAL_BALANCED_USD', 'NET_ACTUAL', 'USD', 1, '[]', 'sha256:early')"
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(
            CompositeTenantMigrationRequiredError,
            match="cannot be assigned automatically",
        ):
            store.create_schema()
        columns = {
            column["name"] for column in inspect(store._engine).get_columns("composite_member_return_fact_publications")
        }
        with store._engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT publication_key, source_fingerprint "
                "FROM composite_member_return_fact_publications WHERE publication_key = 'early'"
            ).one()
    finally:
        store.close()

    assert "tenant_id" not in columns
    assert "period_start" not in columns
    assert "period_end" not in columns
    assert row == ("early", "sha256:early")


def test_publication_schema_upgrade_refuses_missing_lineage_authority(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'publication_without_lineage.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_fact_publications ("
            "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "restatement_sequence INTEGER NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL)"
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        store.create_schema()
        columns = {
            column["name"] for column in inspect(store._engine).get_columns("composite_member_return_fact_publications")
        }
        assert {"tenant_id", "expected_families_json", "source_fingerprint"} <= columns
    finally:
        store.close()


@pytest.mark.parametrize(
    ("expected_families_json", "source_fingerprint"),
    [
        (None, "sha256:retained"),
        ("not-json", "sha256:retained"),
        ('{"portfolio_id":"P1"}', "sha256:retained"),
        (
            '[{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"P1"},'
            '{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"P1"}]',
            "sha256:retained",
        ),
        ("[]", None),
        ("[]", " \t"),
    ],
    ids=[
        "null-manifest",
        "malformed-json",
        "non-list-manifest",
        "duplicate-family",
        "null-fingerprint",
        "blank-fingerprint",
    ],
)
def test_publication_schema_upgrade_refuses_invalid_retained_lineage(
    tmp_path,
    expected_families_json,
    source_fingerprint,
):
    database_url = f"sqlite:///{tmp_path / 'invalid_retained_lineage.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_fact_publications ("
            "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "restatement_sequence INTEGER NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "expected_families_json TEXT, source_fingerprint VARCHAR(256))"
        )
        connection.execute(
            text(
                "INSERT INTO composite_member_return_fact_publications VALUES ("
                "'invalid-lineage', 'INVALID_LINEAGE', 'NET_ACTUAL', 'USD', 1, "
                "'2026-01-01', '2026-01-31', :expected_families_json, :source_fingerprint)"
            ),
            {
                "expected_families_json": expected_families_json,
                "source_fingerprint": source_fingerprint,
            },
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
            store.create_schema()
    finally:
        store.close()


def test_sqlite_bootstrap_preserves_ownerless_rows_and_guards_when_tenant_mapping_is_missing(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'stale_validation_trigger.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_facts ("
            "fact_key VARCHAR(360) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "return_value TEXT NOT NULL, return_view VARCHAR(32) NOT NULL, "
            "beginning_market_value TEXT NOT NULL, ending_market_value TEXT NOT NULL, "
            "reporting_currency VARCHAR(3) NOT NULL, calculation_id VARCHAR(64) NOT NULL, "
            "source_snapshot_id VARCHAR(256) NOT NULL, source_fingerprint VARCHAR(256) NOT NULL, "
            "restatement_version VARCHAR(64) NOT NULL, restatement_sequence INTEGER NOT NULL, "
            "status VARCHAR(64) NOT NULL, reason_codes_json TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER trg_composite_member_return_facts_validate_insert "
            "BEFORE INSERT ON composite_member_return_facts "
            "WHEN NEW.restatement_sequence < 1 "
            "BEGIN SELECT RAISE(ABORT, 'legacy sequence-only validation'); END"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER trg_composite_member_return_facts_immutable_update "
            "BEFORE UPDATE ON composite_member_return_facts "
            "BEGIN SELECT RAISE(ABORT, 'legacy immutable update'); END"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_facts VALUES ("
            "'legacy-lowercase', 'DIRECT_SQL', 'P0', '2026-01-01', '2026-01-31', "
            "'0.01', 'NET_ACTUAL', '100.00', '101.00', 'usd', 'calc-legacy-lowercase', "
            "'snapshot-legacy-lowercase', 'sha256:legacy-lowercase', 'v1', 1, 'READY', '[]')"
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(
            CompositeTenantMigrationRequiredError,
            match="cannot be assigned automatically",
        ):
            store.create_schema()
        with store._engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT reporting_currency FROM composite_member_return_facts WHERE fact_key = 'legacy-lowercase'"
                ).scalar_one()
                == "usd"
            )
            columns = {column["name"] for column in inspect(store._engine).get_columns("composite_member_return_facts")}
        assert "tenant_id" not in columns
        with pytest.raises(IntegrityError, match="legacy sequence-only validation"):
            with store._engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO composite_member_return_facts VALUES ("
                    "'stale-trigger-proof', 'DIRECT_SQL', 'P1', '2026-01-01', '2026-01-31', "
                    "'0.01', 'NET_ACTUAL', '100.00', '101.00', 'USD', 'calc-stale-trigger', "
                    "'snapshot-stale-trigger', 'sha256:stale-trigger', 'v1', 0, 'READY', '[]')"
                )
    finally:
        store.close()


def test_sqlite_failed_bootstrap_restores_legacy_data_and_guards(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'failed_bootstrap_rollback.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_facts ("
            "fact_key VARCHAR(360) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "return_value TEXT NOT NULL, return_view VARCHAR(32) NOT NULL, "
            "beginning_market_value TEXT NOT NULL, ending_market_value TEXT NOT NULL, "
            "reporting_currency VARCHAR(3) NOT NULL, calculation_id VARCHAR(64) NOT NULL, "
            "source_snapshot_id VARCHAR(256) NOT NULL, source_fingerprint VARCHAR(256) NOT NULL, "
            "restatement_version VARCHAR(64) NOT NULL, restatement_sequence INTEGER NOT NULL, "
            "status VARCHAR(64) NOT NULL, reason_codes_json TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_fact_publications ("
            "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "restatement_sequence INTEGER NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "expected_families_json TEXT, source_fingerprint VARCHAR(256))"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER trg_composite_member_return_facts_validate_insert "
            "BEFORE INSERT ON composite_member_return_facts "
            "WHEN NEW.restatement_sequence < 1 "
            "BEGIN SELECT RAISE(ABORT, 'legacy sequence-only validation'); END"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER trg_composite_member_return_facts_immutable_update "
            "BEFORE UPDATE ON composite_member_return_facts "
            "BEGIN SELECT RAISE(ABORT, 'legacy immutable update'); END"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_facts VALUES ("
            "'legacy-lowercase', 'DIRECT_SQL', 'P0', '2026-01-01', '2026-01-31', "
            "'0.01', 'NET_ACTUAL', '100.00', '101.00', 'usd', 'calc-legacy-lowercase', "
            "'snapshot-legacy-lowercase', 'sha256:legacy-lowercase', 'v1', 1, 'READY', '[]')"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_fact_publications VALUES ("
            "'invalid-lineage', 'DIRECT_SQL', 'NET_ACTUAL', 'USD', 1, "
            "'2026-01-01', '2026-01-31', 'not-json', '')"
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
            store.create_schema()
        with store._engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT reporting_currency FROM composite_member_return_facts WHERE fact_key = 'legacy-lowercase'"
                ).scalar_one()
                == "usd"
            )
            trigger_rows = dict(
                connection.exec_driver_sql(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN ("
                    "'trg_composite_member_return_facts_validate_insert', "
                    "'trg_composite_member_return_facts_immutable_update')"
                ).all()
            )
        assert "legacy sequence-only validation" in trigger_rows["trg_composite_member_return_facts_validate_insert"]
        assert "legacy immutable update" in trigger_rows["trg_composite_member_return_facts_immutable_update"]
    finally:
        store.close()


def test_sqlite_failed_maintenance_restores_records_and_guards(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.upsert_definition(_definition("ROLLBACK_MAINTENANCE"))
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "ROLLBACK_MAINTENANCE",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "rollback-maintenance",
            "source_snapshot_id": "rollback-maintenance",
            "source_fingerprint": "sha256:rollback-maintenance",
        }
    )
    try:
        store.upsert_member_return_fact(fact)
        _complete_publication(store, fact)

        def _fail_guard_recreation(_connection):
            raise RuntimeError("injected guard recreation failure")

        monkeypatch.setattr(
            composite_metadata_store_module,
            "_create_composite_fact_database_guards",
            _fail_guard_recreation,
        )
        with pytest.raises(RuntimeError, match="injected guard recreation failure"):
            store.clear_records_for_composites({fact.composite_id})

        counts = store.count_records()
        assert counts.member_return_facts == 1
        with store._engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM composite_member_return_fact_publications "
                    "WHERE composite_id = 'ROLLBACK_MAINTENANCE'"
                ).scalar_one()
                == 1
            )
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text(
                        "DELETE FROM composite_member_return_fact_publications "
                        "WHERE composite_id = 'ROLLBACK_MAINTENANCE'"
                    )
                )
    finally:
        store.close()


def test_sqlite_schema_upgrade_refuses_ownerless_currency_rows_without_partial_changes(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy_currency.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_definitions ("
            "composite_id VARCHAR(128) PRIMARY KEY, display_name VARCHAR(256) NOT NULL, "
            "strategy_code VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "inception_date DATE NOT NULL, termination_date DATE, "
            "calculation_method VARCHAR(64) NOT NULL, source_authority_json TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_definitions VALUES ("
            "'PB_GLOBAL_BALANCED_USD', 'Global Balanced', 'GLOBAL_BALANCED', 'usd', "
            "'2026-01-01', NULL, 'ASSET_WEIGHTED', "
            '\'{"definition_owner":"lotus-manage","membership_owner":"lotus-manage",'
            '"member_return_owner":"lotus-performance","asset_owner":"lotus-core",'
            '"benchmark_owner":"lotus-core","policy_version":"test.v1"}\')'
        )
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_facts ("
            "fact_key VARCHAR(640) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "return_value VARCHAR(128) NOT NULL, beginning_market_value VARCHAR(128) NOT NULL, "
            "ending_market_value VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "calculation_id VARCHAR(64) NOT NULL, source_snapshot_id VARCHAR(256) NOT NULL, "
            "status VARCHAR(64) NOT NULL, reason_codes_json TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_facts VALUES ("
            "'legacy-fact', 'PB_GLOBAL_BALANCED_USD', 'P1', '2026-01-01', '2026-01-31', "
            "'0.01', '100.00', '101.00', 'usd', 'legacy-calc', 'legacy-snapshot', "
            "'READY', '[]')"
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(
            CompositeTenantMigrationRequiredError,
            match="cannot be assigned automatically",
        ):
            store.create_schema()
        definition_columns = {column["name"] for column in inspect(store._engine).get_columns("composite_definitions")}
        fact_columns = {
            column["name"] for column in inspect(store._engine).get_columns("composite_member_return_facts")
        }
        with store._engine.connect() as connection:
            definition_currency = connection.exec_driver_sql(
                "SELECT reporting_currency FROM composite_definitions WHERE composite_id = 'PB_GLOBAL_BALANCED_USD'"
            ).scalar_one()
            fact_currency = connection.exec_driver_sql(
                "SELECT reporting_currency FROM composite_member_return_facts WHERE fact_key = 'legacy-fact'"
            ).scalar_one()
    finally:
        store.close()

    assert "tenant_id" not in definition_columns
    assert "tenant_id" not in fact_columns
    assert definition_currency == "usd"
    assert fact_currency == "usd"


def test_sqlite_definition_currency_guards_reject_direct_writes_on_fresh_and_upgraded_schema(tmp_path):
    for schema_kind in ("fresh", "upgraded"):
        database_url = f"sqlite:///{tmp_path / f'{schema_kind}_definition_currency.db'}"
        engine = create_engine(database_url, future=True)
        if schema_kind == "upgraded":
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE composite_definitions ("
                    "composite_id VARCHAR(128) PRIMARY KEY, display_name VARCHAR(256) NOT NULL, "
                    "strategy_code VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
                    "inception_date DATE NOT NULL, termination_date DATE, "
                    "calculation_method VARCHAR(64) NOT NULL, source_authority_json TEXT NOT NULL)"
                )
        engine.dispose()

        store = CompositeMetadataStore(database_url)
        store.create_schema()
        with store._engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO composite_definitions ("
                "definition_key, tenant_id, composite_id, display_name, strategy_code, reporting_currency, "
                "inception_date, termination_date, calculation_method, source_authority_json) VALUES ("
                "'valid-key', 'test-tenant', 'VALID', 'Valid composite', 'BALANCED', 'USD', "
                "'2026-01-01', NULL, 'ASSET_WEIGHTED', '{}')"
            )
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE composite_definitions SET reporting_currency = 'US1' WHERE composite_id = 'VALID'"
                )
        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO composite_definitions ("
                    "definition_key, tenant_id, composite_id, display_name, strategy_code, reporting_currency, "
                    "inception_date, termination_date, calculation_method, source_authority_json) VALUES ("
                    "'invalid-key', 'test-tenant', 'INVALID', 'Invalid composite', 'BALANCED', 'uſd', "
                    "'2026-01-01', NULL, 'ASSET_WEIGHTED', '{}')"
                )
        with store._engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT reporting_currency FROM composite_definitions WHERE composite_id = 'VALID'"
                ).scalar_one()
                == "USD"
            )
        store.close()


@pytest.mark.parametrize(
    ("legacy_table", "invalid_currency"),
    [
        ("composite_definitions", "US1"),
        ("composite_member_return_facts", " US"),
        ("composite_member_return_fact_publications", "U$D"),
    ],
    ids=["definition-nonalphabetic", "fact-whitespace", "publication-symbol"],
)
def test_sqlite_schema_upgrade_rejects_invalid_legacy_currency(
    tmp_path,
    legacy_table,
    invalid_currency,
):
    database_url = f"sqlite:///{tmp_path / f'invalid_{legacy_table}_currency.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        if legacy_table == "composite_definitions":
            connection.exec_driver_sql(
                "CREATE TABLE composite_definitions ("
                "composite_id VARCHAR(128) PRIMARY KEY, display_name VARCHAR(256) NOT NULL, "
                "strategy_code VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
                "inception_date DATE NOT NULL, termination_date DATE, "
                "calculation_method VARCHAR(64) NOT NULL, source_authority_json TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO composite_definitions VALUES ("
                "'PB_GLOBAL_BALANCED_USD', 'Global Balanced', 'GLOBAL_BALANCED', ?, "
                "'2026-01-01', NULL, 'ASSET_WEIGHTED', '{}')",
                (invalid_currency,),
            )
        elif legacy_table == "composite_member_return_facts":
            connection.exec_driver_sql(
                "CREATE TABLE composite_member_return_facts ("
                "fact_key VARCHAR(640) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
                "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
                "return_value VARCHAR(128) NOT NULL, beginning_market_value VARCHAR(128) NOT NULL, "
                "ending_market_value VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
                "calculation_id VARCHAR(64) NOT NULL, source_snapshot_id VARCHAR(256) NOT NULL, "
                "status VARCHAR(64) NOT NULL, reason_codes_json TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO composite_member_return_facts VALUES ("
                "'legacy-invalid-currency', 'PB_GLOBAL_BALANCED_USD', 'P1', "
                "'2026-01-01', '2026-01-31', '0.01', '100.00', '101.00', ?, "
                "'legacy-calc', 'legacy-snapshot', 'READY', '[]')",
                (invalid_currency,),
            )
        else:
            connection.exec_driver_sql(
                "CREATE TABLE composite_member_return_fact_publications ("
                "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
                "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
                "restatement_sequence INTEGER NOT NULL, period_start DATE NOT NULL, "
                "period_end DATE NOT NULL, expected_families_json TEXT NOT NULL, "
                "source_fingerprint VARCHAR(256) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO composite_member_return_fact_publications VALUES ("
                "'legacy-invalid-currency', 'PB_GLOBAL_BALANCED_USD', 'NET_ACTUAL', ?, 1, "
                "'2026-01-01', '2026-01-31', '[]', 'sha256:legacy')",
                (invalid_currency,),
            )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
        store.create_schema()
    store.close()


@pytest.mark.parametrize(
    "legacy_version",
    ["", "\t", "\n", "v" * 65],
    ids=["blank", "tab-only", "newline-only", "overlong"],
)
def test_sqlite_schema_upgrade_rejects_invalid_legacy_restatement_version(
    tmp_path,
    legacy_version,
):
    database_url = f"sqlite:///{tmp_path / 'invalid_legacy_version.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_facts ("
            "fact_key VARCHAR(640) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "return_value VARCHAR(128) NOT NULL, return_view VARCHAR(32) NOT NULL, "
            "beginning_market_value VARCHAR(128) NOT NULL, ending_market_value VARCHAR(128) NOT NULL, "
            "reporting_currency VARCHAR(3) NOT NULL, calculation_id VARCHAR(64) NOT NULL, "
            "source_snapshot_id VARCHAR(256) NOT NULL, source_fingerprint VARCHAR(256) NOT NULL, "
            "restatement_version VARCHAR(64) NOT NULL, restatement_sequence INTEGER NOT NULL, "
            "status VARCHAR(64) NOT NULL, reason_codes_json TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_facts VALUES ("
            "'legacy-invalid-version', 'PB_GLOBAL_BALANCED_USD', 'P1', "
            "'2026-01-01', '2026-01-31', '0.01', 'NET_ACTUAL', '100.00', '101.00', "
            "'USD', 'legacy-calc', 'legacy-snapshot', 'sha256:legacy', ?, 1, 'READY', '[]')",
            (legacy_version,),
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
        store.create_schema()
    store.close()


@pytest.mark.parametrize(
    "legacy_sequence",
    [None, 0, -1, 1.5, "abc"],
    ids=["null", "zero", "negative", "fractional", "text"],
)
def test_sqlite_schema_upgrade_rejects_invalid_legacy_restatement_sequence(
    tmp_path,
    legacy_sequence,
):
    database_url = f"sqlite:///{tmp_path / 'invalid_legacy_sequence.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_facts ("
            "fact_key VARCHAR(640) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "return_value VARCHAR(128) NOT NULL, return_view VARCHAR(32) NOT NULL, "
            "beginning_market_value VARCHAR(128) NOT NULL, ending_market_value VARCHAR(128) NOT NULL, "
            "reporting_currency VARCHAR(3) NOT NULL, calculation_id VARCHAR(64) NOT NULL, "
            "source_snapshot_id VARCHAR(256) NOT NULL, source_fingerprint VARCHAR(256) NOT NULL, "
            "restatement_version VARCHAR(64) NOT NULL, restatement_sequence INTEGER, "
            "status VARCHAR(64) NOT NULL, reason_codes_json TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_facts VALUES ("
            "'legacy-invalid-sequence', 'PB_GLOBAL_BALANCED_USD', 'P1', "
            "'2026-01-01', '2026-01-31', '0.01', 'NET_ACTUAL', '100.00', '101.00', "
            "'USD', 'legacy-calc', 'legacy-snapshot', 'sha256:legacy', 'published', ?, "
            "'READY', '[]')",
            (legacy_sequence,),
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
        store.create_schema()
    store.close()


@pytest.mark.parametrize(
    "legacy_sequence",
    [None, 0, -1, 1.5, "abc"],
    ids=["null", "zero", "negative", "fractional", "text"],
)
def test_sqlite_schema_upgrade_rejects_invalid_legacy_publication_sequence(
    tmp_path,
    legacy_sequence,
):
    database_url = f"sqlite:///{tmp_path / 'invalid_legacy_publication_sequence.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_fact_publications ("
            "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "restatement_sequence INTEGER, period_start DATE NOT NULL, period_end DATE NOT NULL, "
            "expected_families_json TEXT NOT NULL, source_fingerprint VARCHAR(256) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_fact_publications VALUES ("
            "'legacy-invalid-publication-sequence', 'PB_GLOBAL_BALANCED_USD', 'NET_ACTUAL', "
            "'USD', ?, '2026-01-01', '2026-01-31', '[]', 'sha256:legacy')",
            (legacy_sequence,),
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
        store.create_schema()
    store.close()


@pytest.mark.parametrize(
    ("period_start", "period_end"),
    [
        (None, "2026-01-31"),
        ("2026-01-01", None),
        ("not-a-date", "not-a-date"),
        (20260101, 20260131),
        (b"2026-01-01", b"2026-01-31"),
    ],
    ids=["null-start", "null-end", "invalid-date-text", "compact-integer-dates", "blob-dates"],
)
def test_sqlite_schema_upgrade_rejects_invalid_legacy_publication_period(
    tmp_path,
    period_start,
    period_end,
):
    database_url = f"sqlite:///{tmp_path / 'invalid_legacy_publication_period.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_member_return_fact_publications ("
            "publication_key VARCHAR(80) PRIMARY KEY, composite_id VARCHAR(128) NOT NULL, "
            "return_view VARCHAR(32) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "restatement_sequence INTEGER NOT NULL, period_start DATE, period_end DATE, "
            "expected_families_json TEXT NOT NULL, source_fingerprint VARCHAR(256) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO composite_member_return_fact_publications VALUES ("
            "'legacy-null-publication-period', 'PB_GLOBAL_BALANCED_USD', 'NET_ACTUAL', "
            "'USD', 1, ?, ?, '[]', 'sha256:legacy')",
            (period_start, period_end),
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
        store.create_schema()
    store.close()


def test_publication_rejects_non_alphabetic_reporting_currency_before_persistence(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="canonical three-letter code"):
        store.complete_member_return_fact_publication(
            composite_id="PB_GLOBAL_BALANCED_USD",
            return_view=CompositeReturnView.NET_ACTUAL,
            reporting_currency="US1",
            restatement_sequence=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            expected_families=set(),
            source_fingerprint="sha256:invalid-currency",
        )

    store.close()


def test_unpinned_selection_requires_a_completed_publication_manifest(tmp_path):
    store = _store(tmp_path)
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.01",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "in-progress-calc",
            "source_snapshot_id": "in-progress-snapshot",
            "source_fingerprint": "sha256:in-progress",
        }
    )
    store.upsert_member_return_fact(fact)

    with pytest.raises(CompositeMemberReturnFactSelectionError, match="completed publication"):
        store.list_member_return_facts(
            composite_id=fact.composite_id,
            period_start=fact.period_start,
            period_end=fact.period_end,
            return_view=fact.return_view,
            reporting_currency=fact.reporting_currency,
        )


def test_composite_metadata_store_round_trips_definition_membership_and_fact(tmp_path):
    store = _store(tmp_path)
    definition = _definition()
    membership = CompositeMembership.model_validate(
        {
            "composite_id": definition.composite_id,
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "effective_from": "2026-01-01",
            "source_snapshot_id": "lotus-manage-membership-snapshot-1",
        }
    )
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": definition.composite_id,
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0125",
            "beginning_market_value": "1000000.00",
            "ending_market_value": "1012500.00",
            "reporting_currency": "USD",
            "calculation_id": "7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce",
            "source_snapshot_id": "portfolio-twr-snapshot-1",
            "source_fingerprint": "sha256:portfolio-twr-snapshot-1",
        }
    )

    store.upsert_definition(definition)
    store.upsert_membership(membership)
    store.upsert_member_return_fact(fact)
    _complete_publication(store, fact)

    stored_definition = store.get_definition(definition.composite_id)
    memberships = store.list_memberships(definition.composite_id)
    facts = store.list_member_return_facts(
        composite_id=definition.composite_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
    )
    counts = store.count_records()

    assert stored_definition == definition
    assert memberships == [membership]
    assert facts == [fact]
    assert counts.definitions == 1
    assert counts.memberships == 1
    assert counts.member_return_facts == 1


def test_composite_metadata_store_retains_immutable_versions_and_selects_latest_sequence(tmp_path):
    store = _store(tmp_path)
    first_fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "1000000.00",
            "ending_market_value": "1010000.00",
            "reporting_currency": "USD",
            "calculation_id": "initial-calculation",
            "source_snapshot_id": "initial-snapshot",
            "source_fingerprint": "sha256:initial-snapshot",
        }
    )
    restated_fact = CompositeMemberReturnFact.model_validate(
        first_fact.model_dump(mode="json")
        | {
            "return_value": "0.0125",
            "ending_market_value": "1012500.00",
            "calculation_id": "restated-calculation",
            "source_snapshot_id": "restated-snapshot",
            "source_fingerprint": "sha256:restated-snapshot",
            "restatement_version": "correction-final",
            "restatement_sequence": 2,
        }
    )

    store.upsert_member_return_fact(first_fact)
    store.upsert_member_return_fact(restated_fact)
    _complete_publication(store, restated_fact, source_fingerprint="sha256:restated-publication")

    latest_facts = store.list_member_return_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
    )
    first_version_facts = store.list_member_return_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=1,
    )

    assert latest_facts == [restated_fact]
    assert first_version_facts == [first_fact]
    assert store.count_records().member_return_facts == 2


def test_completed_publication_can_remove_a_prior_fact_family(tmp_path):
    store = _store(tmp_path)
    first_a = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "v1-p1",
            "source_snapshot_id": "v1-p1",
            "source_fingerprint": "sha256:v1-p1",
        }
    )
    first_b = CompositeMemberReturnFact.model_validate(
        first_a.model_dump(mode="json")
        | {
            "portfolio_id": "P2",
            "calculation_id": "v1-p2",
            "source_snapshot_id": "v1-p2",
            "source_fingerprint": "sha256:v1-p2",
        }
    )
    second_a = CompositeMemberReturnFact.model_validate(
        first_a.model_dump(mode="json")
        | {
            "return_value": "0.0200",
            "ending_market_value": "102.00",
            "calculation_id": "v2-p1",
            "source_snapshot_id": "v2-p1",
            "source_fingerprint": "sha256:v2-p1",
            "restatement_version": "membership-correction",
            "restatement_sequence": 2,
        }
    )
    for fact in (first_a, first_b, second_a):
        store.upsert_member_return_fact(fact)

    with pytest.raises(CompositeMemberReturnFactSelectionError):
        store.list_member_return_facts(
            composite_id=first_a.composite_id,
            period_start=first_a.period_start,
            period_end=first_a.period_end,
            return_view=first_a.return_view,
            reporting_currency=first_a.reporting_currency,
        )

    store.complete_member_return_fact_publication(
        composite_id=second_a.composite_id,
        return_view=second_a.return_view,
        reporting_currency=second_a.reporting_currency,
        restatement_sequence=second_a.restatement_sequence,
        period_start=second_a.period_start,
        period_end=second_a.period_end,
        expected_families={(second_a.portfolio_id, second_a.period_start, second_a.period_end)},
        source_fingerprint="sha256:membership-publication-v2",
    )

    assert store.list_member_return_facts(
        composite_id=second_a.composite_id,
        period_start=second_a.period_start,
        period_end=second_a.period_end,
        return_view=second_a.return_view,
        reporting_currency=second_a.reporting_currency,
    ) == [second_a]
    late_family = CompositeMemberReturnFact.model_validate(
        second_a.model_dump(mode="json")
        | {
            "portfolio_id": "P3",
            "calculation_id": "v2-p3-late",
            "source_snapshot_id": "v2-p3-late",
            "source_fingerprint": "sha256:v2-p3-late",
        }
    )
    with pytest.raises(CompositeMemberReturnFactConflictError):
        store.upsert_member_return_fact(late_family)


def test_upgraded_publication_currency_retains_late_writer_fence(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy_publication_currency.db'}"
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    store.upsert_definition(_definition())
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "legacy-publication-p1",
            "source_snapshot_id": "legacy-publication-p1",
            "source_fingerprint": "sha256:legacy-publication-p1",
        }
    )
    store.upsert_member_return_fact(fact)
    _complete_publication(store, fact)
    _drop_sqlite_guard_for_restore_fixture(
        store,
        PUBLICATION_IMMUTABLE_UPDATE_TRIGGER,
    )
    store.close()

    legacy_publication_key = _publication_key(
        composite_id=fact.composite_id,
        return_view=fact.return_view,
        reporting_currency="usd",
        restatement_sequence=fact.restatement_sequence,
    )
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
        connection.exec_driver_sql(
            "UPDATE composite_member_return_fact_publications SET publication_key = ?, reporting_currency = 'usd'",
            (legacy_publication_key,),
        )
    engine.dispose()

    restarted_store = CompositeMetadataStore(database_url)
    restarted_store.create_schema()
    late_family = CompositeMemberReturnFact.model_validate(
        fact.model_dump(mode="json")
        | {
            "portfolio_id": "P2",
            "calculation_id": "legacy-publication-p2-late",
            "source_snapshot_id": "legacy-publication-p2-late",
            "source_fingerprint": "sha256:legacy-publication-p2-late",
        }
    )

    with pytest.raises(CompositeMemberReturnFactConflictError):
        restarted_store.upsert_member_return_fact(late_family)
    restarted_store.close()


@pytest.mark.parametrize("drift", ["missing", "extra"])
def test_pinned_completed_publication_rejects_durable_family_drift(tmp_path, drift):
    store = _store(tmp_path)
    first = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "pinned-p1",
            "source_snapshot_id": "pinned-p1",
            "source_fingerprint": "sha256:pinned-p1",
        }
    )
    second = CompositeMemberReturnFact.model_validate(
        first.model_dump(mode="json")
        | {
            "portfolio_id": "P2",
            "calculation_id": "pinned-p2",
            "source_snapshot_id": "pinned-p2",
            "source_fingerprint": "sha256:pinned-p2",
        }
    )
    for fact in (first, second):
        store.upsert_member_return_fact(fact)
    _complete_publication(store, first, second)

    if drift == "missing":
        _drop_sqlite_guard_for_restore_fixture(
            store,
            MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER,
        )
    else:
        _drop_sqlite_guard_for_restore_fixture(
            store,
            composite_metadata_store_module.MEMBER_RETURN_FACT_COMPLETED_INSERT_TRIGGER,
        )
    with store._session() as session:
        if drift == "missing":
            session.query(CompositeMemberReturnFactModel).filter_by(fact_key=_fact_key(second)).delete()
        else:
            extra = CompositeMemberReturnFact.model_validate(
                first.model_dump(mode="json")
                | {
                    "portfolio_id": "P3",
                    "calculation_id": "pinned-p3",
                    "source_snapshot_id": "pinned-p3",
                    "source_fingerprint": "sha256:pinned-p3",
                }
            )
            session.add(_member_return_fact_model(extra))

    with pytest.raises(
        CompositeMemberReturnFactSelectionError,
        match="completed member-return fact universe",
    ):
        store.list_member_return_facts(
            composite_id=first.composite_id,
            period_start=first.period_start,
            period_end=first.period_end,
            return_view=first.return_view,
            reporting_currency=first.reporting_currency,
            restatement_sequence=1,
        )
    store.close()


def test_pinned_completed_publication_rejects_request_outside_manifest_period(tmp_path):
    store = _store(tmp_path)
    first = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "pinned-wide-p1",
            "source_snapshot_id": "pinned-wide-p1",
            "source_fingerprint": "sha256:pinned-wide-p1",
        }
    )
    second = CompositeMemberReturnFact.model_validate(
        first.model_dump(mode="json")
        | {
            "portfolio_id": "P2",
            "calculation_id": "pinned-wide-p2",
            "source_snapshot_id": "pinned-wide-p2",
            "source_fingerprint": "sha256:pinned-wide-p2",
        }
    )
    for fact in (first, second):
        store.upsert_member_return_fact(fact)
    _complete_publication(store, first, second)
    _drop_sqlite_guard_for_restore_fixture(
        store,
        MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER,
    )
    with store._session() as session:
        session.query(CompositeMemberReturnFactModel).filter_by(fact_key=_fact_key(second)).delete()

    with pytest.raises(
        CompositeMemberReturnFactSelectionError,
        match="does not cover the requested window",
    ):
        store.list_member_return_facts(
            composite_id=first.composite_id,
            period_start=date(2025, 12, 1),
            period_end=first.period_end,
            return_view=first.return_view,
            reporting_currency=first.reporting_currency,
            restatement_sequence=1,
        )
    store.close()


def test_completed_publication_only_supersedes_the_window_it_covers(tmp_path):
    store = _store(tmp_path)
    january = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "january-v1",
            "source_snapshot_id": "january-v1",
            "source_fingerprint": "sha256:january-v1",
        }
    )
    february = CompositeMemberReturnFact.model_validate(
        january.model_dump(mode="json")
        | {
            "period_start": "2026-02-01",
            "period_end": "2026-02-28",
            "return_value": "0.0200",
            "ending_market_value": "102.00",
            "calculation_id": "february-v2",
            "source_snapshot_id": "february-v2",
            "source_fingerprint": "sha256:february-v2",
            "restatement_version": "february-publication",
            "restatement_sequence": 2,
        }
    )
    store.upsert_member_return_fact(january)
    store.upsert_member_return_fact(february)
    _complete_publication(store, january, source_fingerprint="sha256:january-publication-v1")
    store.complete_member_return_fact_publication(
        composite_id=february.composite_id,
        return_view=february.return_view,
        reporting_currency=february.reporting_currency,
        restatement_sequence=february.restatement_sequence,
        period_start=february.period_start,
        period_end=february.period_end,
        expected_families={(february.portfolio_id, february.period_start, february.period_end)},
        source_fingerprint="sha256:february-publication-v2",
    )

    assert store.list_member_return_facts(
        composite_id=january.composite_id,
        period_start=january.period_start,
        period_end=january.period_end,
        return_view=january.return_view,
        reporting_currency=january.reporting_currency,
    ) == [january]
    assert store.list_member_return_facts(
        composite_id=february.composite_id,
        period_start=february.period_start,
        period_end=february.period_end,
        return_view=february.return_view,
        reporting_currency=february.reporting_currency,
    ) == [february]
    with pytest.raises(CompositeMemberReturnFactSelectionError):
        store.list_member_return_facts(
            composite_id=january.composite_id,
            period_start=january.period_start,
            period_end=february.period_end,
            return_view=january.return_view,
            reporting_currency=january.reporting_currency,
        )

    store.complete_member_return_fact_publication(
        composite_id=january.composite_id,
        return_view=january.return_view,
        reporting_currency=january.reporting_currency,
        restatement_sequence=3,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        expected_families=set(),
        source_fingerprint="sha256:march-empty-publication-v3",
    )
    assert (
        store.list_member_return_facts(
            composite_id=january.composite_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            return_view=january.return_view,
            reporting_currency=january.reporting_currency,
        )
        == []
    )
    assert (
        store.list_member_return_facts(
            composite_id=january.composite_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            return_view=january.return_view,
            reporting_currency=january.reporting_currency,
            restatement_sequence=3,
        )
        == []
    )


def test_sqlite_completion_atomically_fences_a_late_fact_writer(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'publication_race.db'}"
    completion_store = CompositeMetadataStore(database_url)
    writer_store = CompositeMetadataStore(database_url)
    completion_store.create_schema()
    completion_store.upsert_definition(_definition("SQLITE_PUBLICATION_RACE"))
    families_read = Event()
    release_completion = Event()
    writer_started = Event()
    writer_finished = Event()
    original_family_lookup = composite_metadata_store_module._member_return_fact_families

    def paused_family_lookup(session, *, filters):
        families = original_family_lookup(session, filters=filters)
        families_read.set()
        assert release_completion.wait(timeout=5)
        return families

    late_fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "SQLITE_PUBLICATION_RACE",
            "portfolio_id": "P1",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": "sqlite-race-p1",
            "source_snapshot_id": "sqlite-race-p1",
            "source_fingerprint": "sha256:sqlite-race-p1",
        }
    )

    def complete_empty_publication():
        completion_store.complete_member_return_fact_publication(
            tenant_id="test-tenant",
            composite_id=late_fact.composite_id,
            return_view=late_fact.return_view,
            reporting_currency=late_fact.reporting_currency,
            restatement_sequence=late_fact.restatement_sequence,
            period_start=late_fact.period_start,
            period_end=late_fact.period_end,
            expected_families=set(),
            source_fingerprint="sha256:sqlite-empty-publication",
        )

    def write_late_fact():
        writer_started.set()
        try:
            writer_store.upsert_member_return_fact(late_fact, tenant_id="test-tenant")
        finally:
            writer_finished.set()

    monkeypatch.setattr(
        composite_metadata_store_module,
        "_member_return_fact_families",
        paused_family_lookup,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            completion_future = executor.submit(complete_empty_publication)
            assert families_read.wait(timeout=5)
            writer_future = executor.submit(write_late_fact)
            assert writer_started.wait(timeout=5)
            assert not writer_finished.wait(timeout=0.2)
            release_completion.set()
            completion_future.result(timeout=5)
            with pytest.raises(CompositeMemberReturnFactConflictError):
                writer_future.result(timeout=5)
        assert (
            completion_store.list_member_return_facts(
                composite_id=late_fact.composite_id,
                period_start=late_fact.period_start,
                period_end=late_fact.period_end,
                return_view=late_fact.return_view,
                reporting_currency=late_fact.reporting_currency,
            )
            == []
        )
    finally:
        release_completion.set()
        completion_store.close()
        writer_store.close()


def test_composite_metadata_store_separates_view_currency_and_rejects_identity_conflicts(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'composite_versions.db'}"
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    store.upsert_definition(_definition())
    net_fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0200",
            "beginning_market_value": "100.00",
            "ending_market_value": "102.00",
            "reporting_currency": "USD",
            "calculation_id": "net-v2",
            "source_snapshot_id": "net-v2-snapshot",
            "source_fingerprint": "sha256:net-v2",
            "restatement_version": "net-correction",
            "restatement_sequence": 2,
        }
    )
    gross_fact = CompositeMemberReturnFact.model_validate(
        net_fact.model_dump(mode="json")
        | {
            "return_value": "0.0300",
            "return_view": "GROSS",
            "ending_market_value": "103.00",
            "calculation_id": "gross-v2",
            "source_snapshot_id": "gross-v2-snapshot",
            "source_fingerprint": "sha256:gross-v2",
        }
    )
    eur_fact = CompositeMemberReturnFact.model_validate(
        net_fact.model_dump(mode="json")
        | {
            "reporting_currency": "EUR",
            "calculation_id": "eur-net-v2",
            "source_snapshot_id": "eur-net-v2-snapshot",
            "source_fingerprint": "sha256:eur-net-v2",
        }
    )

    store.upsert_member_return_fact(net_fact)
    store.upsert_member_return_fact(net_fact)
    store.upsert_member_return_fact(gross_fact)
    store.upsert_member_return_fact(eur_fact)
    _complete_publication(store, net_fact, source_fingerprint="sha256:net-publication-v2")
    _complete_publication(store, gross_fact, source_fingerprint="sha256:gross-publication-v2")
    _complete_publication(store, eur_fact, source_fingerprint="sha256:eur-publication-v2")
    store.close()

    restarted_store = CompositeMetadataStore(database_url)
    restarted_store.create_schema()
    gross = restarted_store.list_member_return_facts(
        composite_id=net_fact.composite_id,
        period_start=net_fact.period_start,
        period_end=net_fact.period_end,
        return_view=CompositeReturnView.GROSS,
        reporting_currency="USD",
    )
    net = restarted_store.list_member_return_facts(
        composite_id=net_fact.composite_id,
        period_start=net_fact.period_start,
        period_end=net_fact.period_end,
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
    )

    assert net == [net_fact]
    assert gross == [gross_fact]
    assert restarted_store.count_records().member_return_facts == 3
    conflicting_fact = CompositeMemberReturnFact.model_validate(
        net_fact.model_dump(mode="json") | {"return_value": "0.0250"}
    )
    with pytest.raises(CompositeMemberReturnFactConflictError):
        restarted_store.upsert_member_return_fact(conflicting_fact)
    assert restarted_store.count_records().member_return_facts == 3


def test_composite_metadata_store_clears_only_requested_composites(tmp_path):
    store = _store(tmp_path)
    keep_definition = CompositeDefinition.model_validate(
        _definition().model_dump(mode="json") | {"composite_id": "KEEP_COMPOSITE"}
    )
    demo_definition = CompositeDefinition.model_validate(
        _definition().model_dump(mode="json") | {"composite_id": "PB_GLOBAL_BALANCED_USD"}
    )
    for definition in (keep_definition, demo_definition):
        store.upsert_definition(definition)
        store.upsert_membership(
            CompositeMembership.model_validate(
                {
                    "composite_id": definition.composite_id,
                    "portfolio_id": f"{definition.composite_id}_PORTFOLIO",
                    "effective_from": "2026-01-01",
                    "source_snapshot_id": f"{definition.composite_id}-membership-snapshot",
                }
            )
        )
        store.upsert_member_return_fact(
            CompositeMemberReturnFact.model_validate(
                {
                    "composite_id": definition.composite_id,
                    "portfolio_id": f"{definition.composite_id}_PORTFOLIO",
                    "period_start": "2026-01-01",
                    "period_end": "2026-01-31",
                    "return_value": "0.0100",
                    "beginning_market_value": "1000000.00",
                    "ending_market_value": "1010000.00",
                    "reporting_currency": "USD",
                    "calculation_id": f"{definition.composite_id}-calculation",
                    "source_snapshot_id": f"{definition.composite_id}-snapshot",
                    "source_fingerprint": f"sha256:{definition.composite_id}-snapshot",
                }
            )
        )

    store.clear_records_for_composites({"PB_GLOBAL_BALANCED_USD"})

    counts = store.count_records()
    assert counts.definitions == 1
    assert counts.memberships == 1
    assert counts.member_return_facts == 1
    assert store.get_definition("KEEP_COMPOSITE") == keep_definition
    assert store.get_definition("PB_GLOBAL_BALANCED_USD") is None
    with store._session() as session:
        assert session.query(CompositeMembershipModel).filter_by(composite_id="PB_GLOBAL_BALANCED_USD").count() == 0
        assert (
            session.query(CompositeMemberReturnFactModel).filter_by(composite_id="PB_GLOBAL_BALANCED_USD").count() == 0
        )


def test_composite_metadata_store_bounds_malformed_definition_source_authority(tmp_path, caplog):
    store = _store(tmp_path)
    definition = _definition()
    store.upsert_definition(definition)
    with store._session() as session:
        row = session.get(
            CompositeDefinitionModel,
            _definition_key(tenant_id="test-tenant", composite_id=definition.composite_id),
        )
        assert row is not None
        row.source_authority_json = "{not-json"

    with caplog.at_level("WARNING", logger="app.services.composite_metadata_store"):
        stored_definition = store.get_definition(definition.composite_id)

    assert stored_definition is None
    assert f"row={definition.composite_id}" in caplog.text


def test_composite_metadata_store_bounds_malformed_member_return_reason_codes(tmp_path, caplog):
    store = _store(tmp_path)
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": "0.0100",
            "beginning_market_value": "1000000.00",
            "ending_market_value": "1010000.00",
            "reporting_currency": "USD",
            "calculation_id": "initial-calculation",
            "source_snapshot_id": "initial-snapshot",
            "source_fingerprint": "sha256:initial-snapshot",
            "status": "DEGRADED",
            "reason_codes": ["missing_final_valuation"],
        }
    )
    store.upsert_member_return_fact(fact)
    _complete_publication(store, fact, source_fingerprint="sha256:degraded-publication")
    _drop_sqlite_guard_for_restore_fixture(
        store,
        MEMBER_RETURN_FACT_IMMUTABLE_UPDATE_TRIGGER,
    )
    with store._session() as session:
        row = session.get(
            CompositeMemberReturnFactModel,
            _fact_key(fact),
        )
        assert row is not None
        row.reason_codes_json = "{not-json"

    with caplog.at_level("WARNING", logger="app.services.composite_metadata_store"):
        facts = store.list_member_return_facts(
            composite_id="PB_GLOBAL_BALANCED_USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            return_view=CompositeReturnView.NET_ACTUAL,
            reporting_currency="USD",
        )

    assert len(facts) == 1
    assert facts[0].reason_codes == [INVALID_COMPOSITE_REASON_CODES_PAYLOAD]
    assert f"row={_fact_key(fact)}" in caplog.text
