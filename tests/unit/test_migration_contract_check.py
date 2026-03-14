from pathlib import Path

from scripts.migration_contract_check import validate_migration_contract


def test_validate_migration_contract_passes_for_durable_schema_document(tmp_path):
    document = tmp_path / "migration-contract.md"
    document.write_text(
        "\n".join(
            [
                "durable metadata schema",
                "forward-only",
                "additive upgrade",
                "rollback runbook",
                "versioned migration",
            ]
        ),
        encoding="utf-8",
    )

    valid, errors = validate_migration_contract(mode="durable-schema", document_path=document)

    assert valid is True
    assert errors is None


def test_validate_migration_contract_reports_missing_phrases(tmp_path):
    document = tmp_path / "migration-contract.md"
    document.write_text("durable metadata schema\nforward-only\n", encoding="utf-8")

    valid, errors = validate_migration_contract(mode="durable-schema", document_path=document)

    assert valid is False
    assert errors == ["additive upgrade", "rollback runbook", "versioned migration"]


def test_validate_migration_contract_reports_missing_document(tmp_path):
    document = Path(tmp_path / "missing.md")

    valid, errors = validate_migration_contract(mode="durable-schema", document_path=document)

    assert valid is False
    assert errors == [f"Missing required migration contract document: {document}"]
