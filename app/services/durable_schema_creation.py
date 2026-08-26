"""Create durable schema safely when several processes start at the same time.

`MetaData.create_all` is a check-then-create: it queries for existing tables, then issues
`CREATE TABLE` for the ones it did not find. Every worker replica runs this at boot, so two workers
starting together both observe a table as absent and both issue the `CREATE TABLE`. The loser
crashes.

The collision surfaces on PostgreSQL's own catalog rather than on the table:

    psycopg.errors.UniqueViolation: duplicate key value violates unique constraint
      "pg_type_typname_nsp_index"
    DETAIL:  Key (typname, typnamespace)=(composite_definitions, 2200) already exists.

which is the implicit composite *type* created alongside the table. That is why `checkfirst` does
not close the window - it guards table existence, and the race is inside the `CREATE TABLE` itself.
See issue #480.

Serialising with a transaction-scoped advisory lock makes the second starter wait rather than race:
it acquires the lock after the first commits, runs `create_all`, finds everything present, and does
nothing. The lock is released by the transaction, so a process that dies mid-bootstrap cannot leave
it held.

The shared durable engine configures a short PostgreSQL `lock_timeout` for ordinary database work.
Schema-lock acquisition is exempt from that timeout so a healthy, slower first bootstrap does not
turn the second starter's wait back into a crash. A dedicated 30-second statement timeout bounds
the acquisition even when the runtime statement timeout is disabled; both configured timeouts are
restored before DDL. Store-specific column and index upgrades run before the transaction releases
the shared lock, so protecting only `create_all` cannot leave a second catalog race behind it.

Single-owner schema creation - a bootstrap step that runs before any worker, with workers verifying
and failing closed - remains the better end state and is tracked on #480. This closes the crash
without requiring every deployment surface to guarantee step ordering first.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sqlalchemy import MetaData, text
from sqlalchemy.engine import Connection, Engine

# Any constant works; it only has to be identical in every process that creates this schema. Derived
# from "lotus durable schema" so a `pg_locks` row is attributable rather than anonymous.
DURABLE_SCHEMA_ADVISORY_LOCK_KEY = 0x10D55CDB
DURABLE_SCHEMA_LOCK_ACQUISITION_TIMEOUT_MS = 30_000

_POSTGRESQL_DIALECTS = frozenset({"postgresql"})


def create_durable_schema(
    engine: Engine,
    metadata: MetaData,
    *,
    schema_upgrades: Sequence[Callable[[Connection], None]] = (),
) -> None:
    """Create and upgrade `metadata`'s tables as one serialised PostgreSQL operation.

    SQLite uses the same transaction boundary without an advisory statement. The durable SQLite
    deployments are single-process and `pg_advisory_xact_lock` does not exist there.
    """

    with engine.begin() as connection:
        if engine.dialect.name in _POSTGRESQL_DIALECTS:
            _acquire_postgresql_schema_lock(connection)
        # Bound to the locked connection on purpose: the DDL and the lock share one transaction, so
        # the lock cannot be released before the tables and upgrades it protects exist. The ordinary
        # configured lock and statement timeouts are back in force for the DDL itself.
        metadata.create_all(connection)
        for upgrade_schema in schema_upgrades:
            upgrade_schema(connection)


def _acquire_postgresql_schema_lock(connection: Connection) -> None:
    """Acquire the shared lock with an explicit bound independent of engine configuration."""

    configured_lock_timeout = connection.execute(text("SELECT current_setting('lock_timeout')")).scalar_one()
    configured_statement_timeout = connection.execute(text("SELECT current_setting('statement_timeout')")).scalar_one()
    connection.execute(
        text("SELECT set_config('lock_timeout', :lock_timeout, true)"),
        {"lock_timeout": "0"},
    )
    connection.execute(
        text("SELECT set_config('statement_timeout', :statement_timeout, true)"),
        {"statement_timeout": f"{DURABLE_SCHEMA_LOCK_ACQUISITION_TIMEOUT_MS}ms"},
    )
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": DURABLE_SCHEMA_ADVISORY_LOCK_KEY},
    )
    connection.execute(
        text("SELECT set_config('statement_timeout', :statement_timeout, true)"),
        {"statement_timeout": configured_statement_timeout},
    )
    connection.execute(
        text("SELECT set_config('lock_timeout', :lock_timeout, true)"),
        {"lock_timeout": configured_lock_timeout},
    )
