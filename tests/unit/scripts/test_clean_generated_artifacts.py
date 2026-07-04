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


def test_build_cleanup_plan_collects_runtime_roots_and_local_database_artifacts(tmp_path) -> None:
    runtime_roots = [tmp_path / "artifacts", tmp_path / "output", tmp_path / "lineage_data"]
    for runtime_root in runtime_roots:
        runtime_root.mkdir()
        (runtime_root / "latest.json").write_text("generated", encoding="utf-8")
    database_files = [
        tmp_path / "lineage_metadata.db",
        tmp_path / "lineage_metadata.db-wal",
        tmp_path / "runtime.sqlite",
        tmp_path / "runtime.sqlite3-shm",
        tmp_path / "local.log",
        tmp_path / ".coverage.branch.unit",
    ]
    for database_file in database_files:
        database_file.write_text("local", encoding="utf-8")

    plan = build_cleanup_plan(tmp_path)

    assert set(plan.directories) == set(runtime_roots)
    assert set(plan.files) == set(database_files)


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


def test_build_cleanup_plan_prunes_marker_backed_virtualenv_before_descent(tmp_path) -> None:
    env_dir = tmp_path / "env"
    (env_dir / "Lib" / "site-packages" / "__pycache__").mkdir(parents=True)
    (env_dir / "pyvenv.cfg").write_text("home = C:/Python313", encoding="utf-8")

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


def test_clean_generated_artifacts_removes_runtime_artifacts_without_source_truth(tmp_path) -> None:
    runtime_root = tmp_path / "output"
    runtime_file = runtime_root / "demo-api-certification" / "latest.json"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text("generated", encoding="utf-8")
    database_file = tmp_path / "lineage_metadata.db"
    database_file.write_text("local", encoding="utf-8")
    protected_files = [
        tmp_path / "docs" / "example.db",
        tmp_path / "contracts" / "contract.sqlite",
        tmp_path / "quality" / "quality.db",
        tmp_path / "wiki" / "audit.log",
    ]
    for protected_file in protected_files:
        protected_file.parent.mkdir(parents=True, exist_ok=True)
        protected_file.write_text("source truth", encoding="utf-8")

    plan = clean_generated_artifacts(tmp_path)

    assert plan.directories == (runtime_root,)
    assert plan.files == (database_file,)
    assert not runtime_root.exists()
    assert not database_file.exists()
    for protected_file in protected_files:
        assert protected_file.exists()
