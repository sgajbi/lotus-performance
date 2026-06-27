from __future__ import annotations

from pathlib import Path

from scripts.repository_hygiene_gate import find_repository_hygiene_violations

ROOT = Path(__file__).resolve().parents[3]


def _makefile_target_block(target: str) -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{target}:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break
        block.append(line)
    return "\n".join(block)


def test_repository_hygiene_gate_is_wired_into_lint() -> None:
    assert "$(MAKE) repository-hygiene-gate" in _makefile_target_block("lint")


def test_clean_target_uses_reviewable_cleanup_script() -> None:
    assert "python scripts/clean_generated_artifacts.py" in _makefile_target_block("clean")


def test_repository_hygiene_gate_passes_current_tracked_files() -> None:
    assert (
        find_repository_hygiene_violations(
            [
                "app/services/performance.py",
                "quality/quality_scorecard.md",
                "docs/architecture/CODEBASE-REVIEW-LEDGER.md",
            ]
        )
        == []
    )


def test_repository_hygiene_gate_blocks_python_cache_artifacts() -> None:
    violations = find_repository_hygiene_violations(
        [
            "scripts/__pycache__/demo_api_certification.cpython-312.pyc",
            "tests/unit/scripts/__pycache__/test_demo.cpython-312.pyc",
            "app/services/generated.pyo",
        ]
    )

    assert violations == [
        "app/services/generated.pyo: generated or local-only file type must not be tracked",
        "scripts/__pycache__/demo_api_certification.cpython-312.pyc: generated or dependency directory content must not be tracked",
        "tests/unit/scripts/__pycache__/test_demo.cpython-312.pyc: generated or dependency directory content must not be tracked",
    ]


def test_repository_hygiene_gate_blocks_local_environment_and_coverage_artifacts() -> None:
    violations = find_repository_hygiene_violations(
        [
            ".env",
            ".coverage",
            ".coverage.unit",
            ".pytest_cache/v/cache/nodeids",
            ".ruff_cache/0.14.6/12345",
            ".mypy_cache/3.12/app.meta.json",
        ]
    )

    assert violations == [
        ".coverage.unit: generated or local-only artifact must not be tracked",
        ".coverage: generated or local-only artifact must not be tracked",
        ".env: generated or local-only artifact must not be tracked",
        ".mypy_cache/3.12/app.meta.json: generated or dependency directory content must not be tracked",
        ".pytest_cache/v/cache/nodeids: generated or dependency directory content must not be tracked",
        ".ruff_cache/0.14.6/12345: generated or dependency directory content must not be tracked",
    ]


def test_repository_hygiene_gate_blocks_build_outputs_and_local_databases() -> None:
    violations = find_repository_hygiene_violations(
        [
            "build/lib/app.py",
            "dist/lotus_performance.whl",
            "htmlcov/index.html",
            "lotus_performance.egg-info/PKG-INFO",
            "local/dev.sqlite",
            "local/service.db",
            "logs/runtime.log",
        ]
    )

    assert violations == [
        "build/lib/app.py: generated or dependency directory content must not be tracked",
        "dist/lotus_performance.whl: generated or dependency directory content must not be tracked",
        "htmlcov/index.html: generated or dependency directory content must not be tracked",
        "local/dev.sqlite: generated or local-only file type must not be tracked",
        "local/service.db: generated or local-only file type must not be tracked",
        "logs/runtime.log: generated or local-only file type must not be tracked",
        "lotus_performance.egg-info/PKG-INFO: generated or dependency directory content must not be tracked",
    ]
