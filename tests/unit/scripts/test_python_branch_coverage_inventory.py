import json
from decimal import Decimal
from pathlib import Path

from scripts.python_branch_coverage_inventory import (
    BranchCoverageSnapshot,
    load_branch_coverage_snapshot,
    render_branch_coverage_inventory,
    write_or_check_report,
)


def _coverage_json(path: Path) -> Path:
    payload = {
        "meta": {"version": "7.10.6", "branch_coverage": True},
        "totals": {
            "covered_lines": 95,
            "missing_lines": 5,
            "num_statements": 100,
            "percent_covered": 88.0,
            "covered_branches": 45,
            "missing_branches": 5,
            "num_partial_branches": 2,
            "num_branches": 50,
        },
        "files": {
            "app/services/a.py": {
                "summary": {
                    "covered_branches": 10,
                    "missing_branches": 1,
                    "num_partial_branches": 0,
                    "num_branches": 11,
                }
            },
            "app/services/b.py": {
                "summary": {
                    "covered_branches": 20,
                    "missing_branches": 3,
                    "num_partial_branches": 1,
                    "num_branches": 24,
                }
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_branch_coverage_snapshot_reads_totals_and_top_gaps(tmp_path: Path) -> None:
    snapshot = load_branch_coverage_snapshot(
        _coverage_json(tmp_path / "coverage.json"),
        report_date="2026-06-28",
        root=tmp_path,
    )

    assert snapshot.branch_coverage_enabled is True
    assert snapshot.covered_lines == 95
    assert snapshot.line_coverage_percent == Decimal("95.00")
    assert snapshot.branch_coverage_percent == Decimal("90.0")
    assert snapshot.top_branch_gaps[0].path == "app/services/b.py"


def test_render_branch_coverage_inventory_is_report_only_and_names_command() -> None:
    snapshot = BranchCoverageSnapshot(
        report_date="2026-06-28",
        branch="feature/test",
        coverage_version="7.10.6",
        branch_coverage_enabled=True,
        covered_lines=95,
        missing_lines=5,
        total_statements=100,
        line_coverage_percent=Decimal("95.0"),
        covered_branches=45,
        missing_branches=5,
        partial_branches=2,
        total_branches=50,
        top_branch_gaps=(),
    )

    report = render_branch_coverage_inventory(snapshot)

    assert "make branch-coverage-baseline" in report
    assert "Combined branch coverage | 90.00%" in report
    assert "Branch-coverage gate | not configured" in report
    assert "Existing line-coverage gate | unchanged" in report


def test_write_or_check_report_detects_stale_inventory(tmp_path: Path) -> None:
    snapshot = BranchCoverageSnapshot(
        report_date="2026-06-28",
        branch="feature/test",
        coverage_version="7.10.6",
        branch_coverage_enabled=True,
        covered_lines=95,
        missing_lines=5,
        total_statements=100,
        line_coverage_percent=Decimal("95.0"),
        covered_branches=45,
        missing_branches=5,
        partial_branches=2,
        total_branches=50,
        top_branch_gaps=(),
    )
    output_path = tmp_path / "quality" / "coverage_inventory.md"

    assert write_or_check_report(snapshot, output_path=output_path, write=True) == 0
    assert write_or_check_report(snapshot, output_path=output_path, write=False) == 0

    output_path.write_text("stale\n", encoding="utf-8")

    assert write_or_check_report(snapshot, output_path=output_path, write=False) == 1
