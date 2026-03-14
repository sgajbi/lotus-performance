from pathlib import Path

from scripts.durable_schema_inventory_check import validate_durable_schema_inventory


def test_validate_durable_schema_inventory_passes_for_complete_document(tmp_path):
    document = tmp_path / "durable-schema-inventory.md"
    document.write_text(
        "\n".join(
            [
                "analytics_execution",
                "analytics_execution_stage",
                "analytics_upstream_snapshot",
                "analytics_compute_job",
                "analytics_async_result",
                "lineage_records",
                "lineage_payloads",
                "additive upgrade",
                "rollback runbook",
                "backup and restore",
            ]
        ),
        encoding="utf-8",
    )

    valid, errors = validate_durable_schema_inventory(document_path=document)

    assert valid is True
    assert errors is None


def test_validate_durable_schema_inventory_reports_missing_phrases(tmp_path):
    document = tmp_path / "durable-schema-inventory.md"
    document.write_text("analytics_execution\nlineage_records\n", encoding="utf-8")

    valid, errors = validate_durable_schema_inventory(document_path=document)

    assert valid is False
    assert errors == [
        "analytics_execution_stage",
        "analytics_upstream_snapshot",
        "analytics_compute_job",
        "analytics_async_result",
        "lineage_payloads",
        "additive upgrade",
        "rollback runbook",
        "backup and restore",
    ]


def test_validate_durable_schema_inventory_reports_missing_document(tmp_path):
    document = Path(tmp_path / "missing.md")

    valid, errors = validate_durable_schema_inventory(document_path=document)

    assert valid is False
    assert errors == [f"Missing required durable schema inventory document: {document}"]
