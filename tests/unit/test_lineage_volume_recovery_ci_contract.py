from pathlib import Path


def _workflow(name: str) -> str:
    return Path(f".github/workflows/{name}").read_text(encoding="utf-8")


def test_pull_request_required_aggregate_enforces_lineage_volume_recovery() -> None:
    workflow = _workflow("pr-merge-gate.yml")

    assert "name: PR Merge Gate / Lineage Volume Recovery" in workflow
    assert "run: make lineage-volume-recovery-smoke" in workflow
    assert "needs: [static-quality-gates, contract-security-gates, lineage-volume-recovery]" in workflow
    assert "needs.lineage-volume-recovery.result" in workflow


def test_main_releasability_repeats_lineage_volume_recovery() -> None:
    workflow = _workflow("main-releasability.yml")

    assert "name: Main Releasability / Lineage Volume Recovery" in workflow
    assert "run: make lineage-volume-recovery-smoke" in workflow
    assert "continue-on-error" not in workflow
