"""Bind existing durable stores to the composite capability's typed ports."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from app.adapters.composite_materialization_repository import (
    CompositeMaterializationStore,
    composite_materialization_store,
    get_composite_materialization_store,
)
from app.core.config import get_settings
from app.ports.composite_materialization import CompositeFactsRepository, CompositeMaterializationRepository
from app.services.composite_metadata_store import composite_metadata_store
from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.submission_fencing_service import AsyncSubmissionStores

materialization_ledger = cast(CompositeMaterializationRepository, composite_materialization_store)
member_facts = cast(CompositeFactsRepository, composite_metadata_store)


@contextmanager
def materialization_admission_transaction() -> (
    Iterator[tuple[CompositeMaterializationRepository, AsyncSubmissionStores]]
):
    """Publish the reservation and existing execution/queue rows atomically.

    SQLite explicitly starts its write transaction before any SAVEPOINT; PostgreSQL
    retains the composite advisory locks until this outer transaction commits.
    Borrowed adapters never dispose the owner engine or commit this transaction.
    """
    owner = get_composite_materialization_store()
    database_url = get_settings().LINEAGE_METADATA_DATABASE_URL
    with owner._engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.begin()
        try:
            yield (
                CompositeMaterializationStore(database_url, connection=connection),
                AsyncSubmissionStores(
                    ExecutionRegistry(database_url, connection=connection),
                    ComputeJobStore(database_url, connection=connection),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
