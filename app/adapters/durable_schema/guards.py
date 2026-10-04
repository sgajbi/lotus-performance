"""Read-only verification of source-owned trigger and function definitions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError

_TRIGGER_NAME = re.compile(r"CREATE\s+TRIGGER\s+(\w+)", re.IGNORECASE)
_PG_TRIGGER = re.compile(
    r"CREATE\s+TRIGGER\s+(\w+)\s+BEFORE\s+(INSERT|UPDATE|DELETE)\s+ON\s+(\w+)\s+"
    r"FOR\s+EACH\s+ROW\s+EXECUTE\s+FUNCTION\s+(\w+)\(\)\s*;?\s*$",
    re.IGNORECASE,
)
_PG_FUNCTION = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(\w+)\((.*?)\)\s+RETURNS\s+(\w+)\s+"
    r"LANGUAGE\s+(\w+)\s*(.*?)\s+AS\s+\$\$(.*?)\$\$\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SQL_TOKEN = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[a-zA-Z_][a-zA-Z_0-9$]*|[^\s]")


def sql_identity(sql: str) -> str:
    """Ignore layout and unquoted identifier case, never string contents or grouping."""
    tokens = [token if token[0] in "'\"" else token.lower() for token in _SQL_TOKEN.findall(sql)]
    if tokens and tokens[-1] == ";":
        tokens.pop()
    return " ".join(tokens)


def require_managed_guards(connection: Connection, statements: Sequence[str]) -> None:
    if not any(_TRIGGER_NAME.match(statement.strip()) for statement in statements):
        raise DurableSchemaMigrationRequiredError(["empty_managed_guard_contract"])
    if connection.dialect.name == "sqlite":
        issues = _sqlite_guard_issues(connection, statements)
    elif connection.dialect.name == "postgresql":
        issues = _postgres_guard_issues(connection, statements)
    else:
        issues = ["unsupported_durable_dialect"]
    if issues:
        raise DurableSchemaMigrationRequiredError(issues)


def _sqlite_guard_issues(connection: Connection, statements: Sequence[str]) -> list[str]:
    rows = connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type='trigger'"))
    installed = {row[0]: row[1] for row in rows}
    issues = []
    for statement in statements:
        match = _TRIGGER_NAME.match(statement.strip())
        if match and sql_identity(installed.get(match[1]) or "") != sql_identity(statement):
            issues.append(f"trigger:{match[1]}")
    return issues


@dataclass(frozen=True)
class _FunctionContract:
    name: str
    arguments: str
    returns: str
    language: str
    volatility: str
    parallel: str
    body: str


def _function_contract(statement: str) -> _FunctionContract | None:
    if not statement.strip().upper().startswith("CREATE OR REPLACE FUNCTION"):
        return None
    match = _PG_FUNCTION.fullmatch(statement.strip())
    if match is None:
        raise DurableSchemaMigrationRequiredError(["unsupported_managed_function_contract"])
    attributes = sql_identity(match[5])
    if attributes not in ("", "immutable parallel safe"):
        raise DurableSchemaMigrationRequiredError([f"function_contract:{match[1]}"])
    return _FunctionContract(
        match[1], match[2], match[3], match[4], "i" if attributes else "v", "s" if attributes else "u", match[6]
    )


def _postgres_guard_issues(connection: Connection, statements: Sequence[str]) -> list[str]:
    triggers = _postgres_triggers(connection)
    functions = _postgres_functions(connection)
    issues = []
    for statement in statements:
        name = _TRIGGER_NAME.match(statement.strip())
        if name and not _postgres_trigger_matches(statement, triggers.get(name[1])):
            issues.append(f"trigger:{name[1]}")
        contract = _function_contract(statement)
        if contract and not _postgres_function_matches(contract, functions.get(contract.name, [])):
            issues.append(f"function:{contract.name}")
    return issues


def _postgres_triggers(connection: Connection) -> dict[str, Any]:
    rows = connection.execute(
        text(
            "SELECT t.tgname, c.relname, t.tgtype, t.tgenabled, t.tgnargs, t.tgqual, "
            "t.tgdeferrable, t.tginitdeferred, p.proname, pn.nspname = current_schema() AS local_function "
            "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_namespace pn ON pn.oid = p.pronamespace "
            "WHERE n.nspname = current_schema() AND NOT t.tgisinternal"
        )
    ).mappings()
    return {row["tgname"]: row for row in rows}


def _postgres_functions(connection: Connection) -> dict[str, list[Any]]:
    rows = connection.execute(
        text(
            "SELECT p.proname, p.prosrc, p.provolatile, p.proparallel, p.prosecdef, p.proconfig, "
            "p.proisstrict, p.proleakproof, p.prokind, l.lanname, "
            "pg_get_function_identity_arguments(p.oid) AS arguments, "
            "format_type(p.prorettype, NULL) AS returns "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_language l ON l.oid = p.prolang WHERE n.nspname = current_schema()"
        )
    ).mappings()
    functions: dict[str, list[Any]] = {}
    for row in rows:
        functions.setdefault(row["proname"], []).append(row)
    return functions


def _postgres_trigger_matches(statement: str, actual: Any) -> bool:
    match = _PG_TRIGGER.fullmatch(statement.strip())
    if match is None or actual is None:
        return False
    event = {"INSERT": 4, "DELETE": 8, "UPDATE": 16}[match[2].upper()]
    expected = (match[3], 1 | 2 | event, "O", 0, None, False, False, match[4], True)
    observed = tuple(
        actual[key]
        for key in (
            "relname",
            "tgtype",
            "tgenabled",
            "tgnargs",
            "tgqual",
            "tgdeferrable",
            "tginitdeferred",
            "proname",
            "local_function",
        )
    )
    return observed == expected


def _postgres_function_matches(contract: _FunctionContract, rows: list[Any]) -> bool:
    if len(rows) != 1:
        return False
    row = rows[0]
    expected = (
        contract.arguments,
        contract.returns,
        contract.language,
        contract.volatility,
        contract.parallel,
        contract.body,
    )
    actual = tuple(row[key] for key in ("arguments", "returns", "lanname", "provolatile", "proparallel", "prosrc"))
    if tuple(map(sql_identity, actual)) != tuple(map(sql_identity, expected)):
        return False
    return (
        not any((row["prosecdef"], row["proconfig"], row["proisstrict"], row["proleakproof"])) and row["prokind"] == "f"
    )
