from pathlib import Path

from scripts.generate_quality_baseline import (
    RepositoryStatistics,
    generated_reports,
    render_baseline_report,
    render_quality_scorecard,
    write_or_check_reports,
)


def _stats() -> RepositoryStatistics:
    return RepositoryStatistics(
        report_date="2026-06-27",
        branch="feature/test",
        commit="abc1234",
        python_files=12,
        package_markers=3,
        python_loc=456,
        test_modules=7,
        collected_tests="89 tests collected in 1.23s",
        configured_workflows=5,
        largest_python_files=(("app/services/example.py", 120), ("tests/unit/test_example.py", 90)),
    )


def test_render_baseline_report_includes_repeatable_command_and_current_branch():
    report = render_baseline_report(_stats())

    assert "Branch: `feature/test`" in report
    assert "Baseline commit" not in report
    assert "`make quality-baseline`" in report
    assert "| 1 | `app/services/example.py` | 120 |" in report


def test_render_quality_scorecard_uses_bank_buyable_status_vocabulary():
    scorecard = render_quality_scorecard(_stats())

    assert "| Architecture | `Partially implemented` |" in scorecard
    assert "| API and contracts | `Implemented` |" in scorecard
    assert "does not claim\nthe whole application is procurement-ready" in scorecard


def test_write_or_check_reports_detects_stale_generated_reports(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[3]
    for path, content in generated_reports(_stats()).items():
        output_path = tmp_path / path.relative_to(repo_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    assert write_or_check_reports(_stats(), write=False, root=tmp_path) == 0

    (tmp_path / "quality" / "baseline_report.md").write_text("stale\n", encoding="utf-8")

    assert write_or_check_reports(_stats(), write=False, root=tmp_path) == 1
