"""Render managed DDL from the same source used by the schema owner, without I/O."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.engine.interfaces import Dialect


class SchemaStatementWriter(Protocol):
    @property
    def dialect(self) -> Dialect: ...

    def exec_driver_sql(self, statement: str) -> object: ...


class SchemaStatements:
    def __init__(self, dialect: Dialect):
        self.dialect = dialect
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)
