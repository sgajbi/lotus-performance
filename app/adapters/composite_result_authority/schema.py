"""Explicit owner migration and exact read-only authority metadata guard inventory."""

from sqlalchemy import inspect

from app.adapters.composite_result_authority.records import AuthorityBase
from app.adapters.durable_schema.catalog import require_managed_guards, require_metadata_schema
from app.adapters.durable_schema.statements import SchemaStatements

_APPEND_TABLES = (
    "composite_authority_proposals",
    "composite_authority_approvals",
    "composite_authority_decisions",
    "composite_authority_revisions",
    "composite_authority_proposal_scopes",
)
_SCOPES = "composite_authority_scopes"


def require_authority_schema(connection):
    if any(inspect(connection).has_table(table) for table in AuthorityBase.metadata.tables):
        require_metadata_schema(connection, AuthorityBase.metadata)


def create_authority_schema(connection):
    AuthorityBase.metadata.create_all(connection)
    for statement in authority_guard_statements(connection.dialect):
        connection.exec_driver_sql(statement)


def verify_authority_schema(connection):
    require_metadata_schema(connection, AuthorityBase.metadata)
    require_managed_guards(connection, authority_guard_statements(connection.dialect))


def _guard(writer, table, name, operation, predicate):
    message = "composite authority custody or transition refused"
    if writer.dialect.name == "sqlite":
        writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
        writer.exec_driver_sql(
            f"CREATE TRIGGER {name} BEFORE {operation} ON {table} WHEN {predicate} "
            f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
        )
    elif writer.dialect.name == "postgresql":
        function = name + "_fn"
        level = "STATEMENT" if operation == "TRUNCATE" else "ROW"
        writer.exec_driver_sql(
            f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
            f"BEGIN IF {predicate} THEN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = '{message}'; "
            "END IF; RETURN NEW; END; $$"
        )
        writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {table}")
        writer.exec_driver_sql(
            f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH {level} EXECUTE FUNCTION {function}()"
        )


def _json_field(dialect, column, *path):
    if dialect.name == "sqlite":
        return f"json_extract({column}, '$.{'.'.join(path)}')"
    return f"({column}::jsonb #>> '{{{','.join(path)}}}')"


def _scope_reference(dialect):
    def field(*path):
        return _json_field(dialect, "r.selection_json", *path)

    equal_null = "IS" if dialect.name == "sqlite" else "IS NOT DISTINCT FROM"
    return (
        "NOT EXISTS (SELECT 1 FROM composite_authority_revisions r "  # nosec B608: migration-owned fixed identifiers/JSON paths only; no caller SQL.
        "WHERE r.tenant_id = NEW.tenant_id AND r.scope_id = NEW.scope_id AND r.revision = NEW.revision "
        f"AND {field('scope', 'base_id')} = NEW.base_id "
        f"AND {field('scope', 'period_start')} = CAST(NEW.period_start AS TEXT) "
        f"AND {field('scope', 'period_end')} = CAST(NEW.period_end AS TEXT) "
        f"AND {field('bundle_id')} {equal_null} NEW.bundle_id)"
    )


def _revision_receipt(dialect):
    def field(*path):
        return _json_field(dialect, "NEW.selection_json", *path)

    if dialect.name == "sqlite":
        member = "json_each(d.response_json, '$.selections') s"
        same = "json(s.value) = json(NEW.selection_json)"
    else:
        member = "jsonb_array_elements(d.response_json::jsonb -> 'selections') s(value)"
        same = "s.value = NEW.selection_json::jsonb"
    return (
        f"{field('scope', 'scope_id')} != NEW.scope_id OR "
        f"CAST({field('revision')} AS INTEGER) != NEW.revision OR "
        f"{field('candidate_id')} != NEW.candidate_id OR "
        f"NOT EXISTS (SELECT 1 FROM composite_authority_decisions d, {member} "  # nosec B608: member/same are fixed dialect branches, never caller input.
        "WHERE d.tenant_id = NEW.tenant_id AND d.decision_id = NEW.decision_id "
        f"AND {same})"
    )


def authority_guard_statements(dialect):
    writer = SchemaStatements(dialect)
    for table in _APPEND_TABLES:
        for operation in ("UPDATE", "DELETE", "TRUNCATE"):
            if dialect.name == "sqlite" and operation == "TRUNCATE":
                continue
            _guard(writer, table, f"trg_{table}_{operation.lower()}", operation, "TRUE")
    for operation in ("DELETE", "TRUNCATE"):
        if dialect.name != "sqlite" or operation != "TRUNCATE":
            _guard(writer, _SCOPES, f"trg_{_SCOPES}_{operation.lower()}", operation, "TRUE")
    _guard(
        writer,
        _SCOPES,
        "trg_composite_authority_scope_insert",
        "INSERT",
        "NEW.revision != 1 OR " + _scope_reference(dialect),
    )
    predicate = (
        "NEW.tenant_id != OLD.tenant_id OR NEW.scope_id != OLD.scope_id OR NEW.base_id != OLD.base_id "
        "OR NEW.period_start != OLD.period_start OR NEW.period_end != OLD.period_end "
        "OR NEW.revision != OLD.revision + 1 OR " + _scope_reference(dialect)
    )
    _guard(writer, _SCOPES, "trg_composite_authority_scope_update", "UPDATE", predicate)
    original = (
        "NOT EXISTS (SELECT 1 FROM composite_result_candidates c WHERE c.tenant_id = NEW.tenant_id "
        "AND c.candidate_id = NEW.candidate_id) OR NOT EXISTS "
        "(SELECT 1 FROM composite_authority_decisions d WHERE d.tenant_id = NEW.tenant_id AND d.decision_id = NEW.decision_id)"
    )
    _guard(writer, "composite_authority_revisions", "trg_composite_authority_revision_original", "INSERT", original)
    _guard(
        writer,
        "composite_authority_revisions",
        "trg_composite_authority_revision_receipt",
        "INSERT",
        _revision_receipt(dialect),
    )
    approval = (
        "NOT EXISTS (SELECT 1 FROM composite_authority_approvals a WHERE a.tenant_id = NEW.tenant_id "
        "AND a.approval_id = NEW.approval_id AND a.proposal_id = NEW.proposal_id)"
    )
    _guard(writer, "composite_authority_decisions", "trg_composite_authority_decision_approval", "INSERT", approval)

    def receipt(column, *path):
        return _json_field(dialect, column, *path)

    approved = (
        "NOT EXISTS (SELECT 1 FROM composite_authority_proposals p WHERE p.tenant_id = NEW.tenant_id "  # nosec B608: receipt expressions use fixed columns/JSON paths only.
        "AND p.proposal_id = NEW.proposal_id "
        f"AND {receipt('NEW.response_json', 'proposal_digest')} = p.content_digest) "
        f"OR COALESCE({receipt('NEW.response_json', 'approval_id')}, '') != NEW.approval_id "
        f"OR COALESCE({receipt('NEW.response_json', 'proposal_id')}, '') != NEW.proposal_id "
        f"OR COALESCE({receipt('NEW.checker_json', 'tenant_id')}, '') != NEW.tenant_id "
        f"OR COALESCE({receipt('NEW.checker_json', 'subject')}, '') != COALESCE({receipt('NEW.response_json', 'checker_subject')}, '-')"
    )
    _guard(writer, "composite_authority_approvals", "trg_composite_authority_approval_content", "INSERT", approved)
    return tuple(writer.statements)
