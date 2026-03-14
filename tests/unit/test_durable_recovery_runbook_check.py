from pathlib import Path

from scripts.durable_recovery_runbook_check import validate_durable_recovery_runbook


def test_validate_durable_recovery_runbook_passes_for_complete_document(tmp_path):
    document = tmp_path / "durable-metadata-recovery.md"
    document.write_text(
        "\n".join(
            [
                "backup and restore order",
                "worker restart order",
                "performance-analytics",
                "performance-compute-executor",
                "performance-lineage-worker",
                "analytics_execution",
                "analytics_compute_job",
                "lineage_payloads",
                "scripts/durable_recovery_drill.py",
                "structured recovery evidence json",
                "operator-id",
                "backup-identifier",
                "timestamped evidence file",
                "manifest.json",
                "retention limit",
                "maximum age policy",
                "/health/ready",
                "/integration/runtime-status",
                "forward-only",
            ]
        ),
        encoding="utf-8",
    )

    valid, errors = validate_durable_recovery_runbook(document_path=document)

    assert valid is True
    assert errors is None


def test_validate_durable_recovery_runbook_reports_missing_phrases(tmp_path):
    document = tmp_path / "durable-metadata-recovery.md"
    document.write_text("backup and restore order\nperformance-analytics\n", encoding="utf-8")

    valid, errors = validate_durable_recovery_runbook(document_path=document)

    assert valid is False
    assert errors == [
        "worker restart order",
        "performance-compute-executor",
        "performance-lineage-worker",
        "analytics_execution",
        "analytics_compute_job",
        "lineage_payloads",
        "scripts/durable_recovery_drill.py",
        "structured recovery evidence json",
        "operator-id",
        "backup-identifier",
        "timestamped evidence file",
        "manifest.json",
        "retention limit",
        "maximum age policy",
        "/health/ready",
        "/integration/runtime-status",
        "forward-only",
    ]


def test_validate_durable_recovery_runbook_reports_missing_document(tmp_path):
    document = Path(tmp_path / "missing.md")

    valid, errors = validate_durable_recovery_runbook(document_path=document)

    assert valid is False
    assert errors == [f"Missing required durable recovery runbook: {document}"]
