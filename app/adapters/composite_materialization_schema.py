"""Refuse incompatible restored ledgers before shared bootstrap changes durable state."""

from __future__ import annotations

import re

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect
from sqlalchemy.engine import Connection

from app.adapters.composite_materialization_records import CompositeMaterializationModel


class CompositeMaterializationMigrationRequiredError(RuntimeError):
    """An existing ledger requires reviewed migration rather than guessed repair."""


def _predicate_identity(predicate: str) -> str:
    # PostgreSQL deparses text/date casts and IN lists as ANY(ARRAY[...]).
    # Only normalize these representation differences; preserve operators and
    # literal contents so a same-named weakened constraint is not accepted.
    predicate = re.sub(r"::(?:character varying|text|date|integer|bigint)\b(?:\[\])?", "", predicate)
    predicate = re.sub(r"=\s*ANY\s*\(ARRAY\[([^]]+)\]\)", r" IN (\1)", predicate)
    predicate = re.sub(
        r"([A-Za-z_][A-Za-z_0-9]*(?:\([^)]*\))?)\s+BETWEEN\s+('[^']*'|[0-9]+)\s+AND\s+('[^']*'|[0-9]+)",
        r"\1 >= \2 AND \1 <= \3",
        predicate,
    )
    predicate = _canonical_strip_characters(predicate)
    tokens = re.findall(r"'(?:''|[^'])*'|[^']+", predicate)
    return "".join(token if token.startswith("'") else re.sub(r"\s", "", token).lower() for token in tokens)


def _canonical_strip_characters(predicate: str) -> str:
    # Only flatten PostgreSQL's associative parentheses around the constant
    # chr() concatenation. Never erase grouping from boolean predicates/functions.
    match = re.search(r"btrim\(tenant_id,\s*(.*)\)$", predicate)
    if match is None:
        return predicate
    argument = match.group(1)
    calls = re.findall(r"chr\([0-9]+\)", argument)
    remainder = re.sub(r"chr\([0-9]+\)", "", argument)
    if not calls or re.fullmatch(r"[\s()|]*", remainder) is None:
        return predicate
    return predicate[: match.start(1)] + " || ".join(calls) + ")"


def _column_issues(connection: Connection) -> list[str]:
    table = CompositeMaterializationModel.__table__
    columns = {item["name"]: item for item in inspect(connection).get_columns(table.name)}
    issues = []
    for expected in table.columns:
        actual = columns.get(expected.name)
        if actual is None:
            issues.append(f"missing column {expected.name}")
        elif actual["nullable"] != expected.nullable or not expected.type._compare_type_affinity(actual["type"]):
            issues.append(f"incompatible column {expected.name}")
    return issues


def _identity_issues(connection: Connection) -> list[str]:
    table = CompositeMaterializationModel.__table__
    inspector = inspect(connection)
    primary_key = tuple(inspector.get_pk_constraint(table.name).get("constrained_columns") or ())
    expected_primary_key = tuple(column.name for column in table.primary_key.columns)
    issues = []
    if primary_key != expected_primary_key:
        issues.append("incompatible authority primary key")
    return [*issues, *_unique_scope_issues(connection)]


def _unique_scope_issues(connection: Connection) -> list[str]:
    table = CompositeMaterializationModel.__table__
    inspector = inspect(connection)
    unique_constraints = {
        item["name"]: tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)
    }
    expected_unique = {
        item.name: tuple(column.name for column in item.columns)
        for item in table.constraints
        if isinstance(item, UniqueConstraint)
    }
    issues = []
    if unique_constraints != expected_unique:
        issues.append("incompatible financial-scope uniqueness")
    return [*issues, *_global_index_issues(connection)]


def _global_index_issues(connection: Connection) -> list[str]:
    if any(
        item.get("unique") and "tenant_id" not in (item.get("column_names") or [])
        for item in inspect(connection).get_indexes(CompositeMaterializationModel.__tablename__)
    ):
        return ["unexpected global identity uniqueness"]
    return []


def _constraint_issues(connection: Connection, *, expected: dict[str | None, str] | None = None) -> list[str]:
    table = CompositeMaterializationModel.__table__
    installed = {item["name"]: item["sqltext"] for item in inspect(connection).get_check_constraints(table.name)}
    expected = _expected_constraints(connection) if expected is None else expected
    return [
        f"missing or incompatible constraint {name}"
        for name, predicate in expected.items()
        if _predicate_identity(installed.get(name, "")) != _predicate_identity(predicate)
    ]


def _expected_constraints(connection: Connection) -> dict[str | None, str]:
    expected = {}
    table = CompositeMaterializationModel.__table__
    for item in table.constraints:
        if not isinstance(item, CheckConstraint):
            continue
        dialect = item._ddl_if.dialect if item._ddl_if is not None else None
        if dialect is not None and dialect != connection.dialect.name:
            continue
        expected[item.name] = str(item.sqltext)
    return expected


def require_materialization_schema(connection: Connection) -> None:
    table_name = CompositeMaterializationModel.__tablename__
    if not inspect(connection).has_table(table_name):
        return
    issues = [*_column_issues(connection), *_identity_issues(connection), *_constraint_issues(connection)]
    if issues:
        raise CompositeMaterializationMigrationRequiredError(
            "Composite materialization schema requires reviewed migration: " + "; ".join(sorted(issues))
        )
