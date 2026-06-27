from __future__ import annotations

from scripts.clean_generated_artifacts import build_cleanup_plan, clean_generated_artifacts


def test_build_cleanup_plan_collects_known_local_artifacts(tmp_path) -> None:
    cache_dir = tmp_path / "app" / "__pycache__"
    cache_dir.mkdir(parents=True)
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    coverage_file = tmp_path / ".coverage.unit"
    coverage_file.write_text("coverage", encoding="utf-8")

    plan = build_cleanup_plan(tmp_path)

    assert plan.directories == (cache_dir, build_dir)
    assert plan.files == (coverage_file,)


def test_build_cleanup_plan_prunes_git_venv_and_node_modules(tmp_path) -> None:
    for pruned_root in [".git", ".venv", "venv", "node_modules"]:
        cache_dir = tmp_path / pruned_root / "__pycache__"
        cache_dir.mkdir(parents=True)
        coverage_file = tmp_path / pruned_root / ".coverage"
        coverage_file.write_text("coverage", encoding="utf-8")

    assert build_cleanup_plan(tmp_path).directories == ()
    assert build_cleanup_plan(tmp_path).files == ()


def test_build_cleanup_plan_prunes_local_path_without_resolving_target(tmp_path) -> None:
    outside_target = tmp_path.parent / "outside-venv-target"
    outside_target.mkdir()
    local_venv = tmp_path / ".venv"
    try:
        local_venv.symlink_to(outside_target, target_is_directory=True)
    except OSError:
        local_venv.mkdir()

    cache_dir = local_venv / "__pycache__"
    cache_dir.mkdir(exist_ok=True)

    assert build_cleanup_plan(tmp_path).directories == ()


def test_build_cleanup_plan_prunes_dependency_trees_before_descent(tmp_path) -> None:
    (tmp_path / "node_modules" / "package" / "__pycache__").mkdir(parents=True)
    (tmp_path / "venv" / "Lib" / "site-packages" / "__pycache__").mkdir(parents=True)

    assert build_cleanup_plan(tmp_path).directories == ()


def test_clean_generated_artifacts_removes_only_planned_artifacts(tmp_path) -> None:
    cache_dir = tmp_path / "tests" / "__pycache__"
    cache_dir.mkdir(parents=True)
    coverage_file = tmp_path / ".coverage"
    coverage_file.write_text("coverage", encoding="utf-8")
    source_file = tmp_path / "app" / "service.py"
    source_file.parent.mkdir()
    source_file.write_text("print('kept')", encoding="utf-8")

    plan = clean_generated_artifacts(tmp_path)

    assert plan.directories == (cache_dir,)
    assert plan.files == (coverage_file,)
    assert not cache_dir.exists()
    assert not coverage_file.exists()
    assert source_file.exists()
