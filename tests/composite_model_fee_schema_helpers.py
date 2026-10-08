"""Known populated legacy ledger bytes for SQLite and PostgreSQL migration proof."""

import json
from datetime import date

from sqlalchemy.schema import CreateTable

from app.adapters.composite_materialization_records import CompositeMaterializationModel
from tests.composite_materialization_helpers import command_for


def create_populated_legacy_ledger(engine):
    table = CompositeMaterializationModel.__table__
    ddl = str(CreateTable(table).compile(dialect=engine.dialect))
    current = "return_view IN ('GROSS', 'NET_ACTUAL', 'NET_MODEL_FEE')"
    assert ddl.count(current) == 1
    ddl = ddl.replace(current, "return_view IN ('GROSS', 'NET_ACTUAL')")
    with engine.begin() as connection:
        connection.exec_driver_sql(ddl)
        for view in ("GROSS", "NET_ACTUAL"):
            for sequence, state in enumerate(("WAITING", "PUBLISHING", "COMPLETE", "BLOCKED"), 1):
                command = command_for(return_view=view, restatement_sequence=sequence)
                connection.execute(
                    table.insert().values(
                        tenant_id="tenant-a",
                        materialization_id=str(command.materialization_id),
                        composite_id=command.composite_id,
                        return_view=view,
                        reporting_currency="USD",
                        restatement_sequence=sequence,
                        period_start=date(2026, 1, 5),
                        period_end=date(2026, 1, 5),
                        command_json=json.dumps(command.immutable_payload(), sort_keys=True),
                        actor_id="original-operator",
                        # Owner migration preserves opaque historical bytes; it
                        # never re-authors or approves their financial evidence.
                        source_json='{"retained": "original source"}',
                        outcomes_json='[ {"retained": "original outcome"} ]',
                        state=state,
                        reason_code="ORIGINAL_REASON",
                        revision=sequence,
                    )
                )
