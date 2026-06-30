from pathlib import Path

from scripts.python_test_taxonomy_inventory import (
    TestModuleInventory,
    collect_test_modules,
    evaluate_taxonomy_thresholds,
    render_markdown,
    summarize_test_taxonomy,
)


def test_collect_test_modules_counts_functions_and_classifies_families(tmp_path: Path) -> None:
    tests_root = tmp_path / "tests"
    api_dir = tests_root / "integration"
    api_dir.mkdir(parents=True)
    contract_dir = tests_root / "unit" / "app"
    contract_dir.mkdir(parents=True)
    service_dir = tests_root / "unit" / "services"
    service_dir.mkdir(parents=True)
    api_file = api_dir / "test_returns_api.py"
    api_file.write_text(
        """
def test_api_happy_path():
    pass

async def test_api_async_path():
    pass
""",
        encoding="utf-8",
    )
    contract_file = contract_dir / "test_openapi_contract.py"
    contract_file.write_text(
        """
class TestContract:
    def test_contract_shape(self):
        pass
""",
        encoding="utf-8",
    )
    compute_store_file = service_dir / "test_compute_job_store.py"
    compute_store_file.write_text(
        """
def test_compute_queue_inspection_supportability():
    pass
""",
        encoding="utf-8",
    )
    returns_series_file = service_dir / "test_returns_series_service.py"
    returns_series_file.write_text(
        """
def test_returns_series_policy_boundary():
    pass
""",
        encoding="utf-8",
    )
    runtime_recovery_file = service_dir / "test_runtime_recovery_service.py"
    runtime_recovery_file.write_text(
        """
def test_recovery_queue_filter_preserves_operator_supportability():
    pass
""",
        encoding="utf-8",
    )
    stateful_input_file = service_dir / "test_stateful_input_service.py"
    stateful_input_file.write_text(
        """
def test_stateful_benchmark_market_series_source_boundary():
    pass
""",
        encoding="utf-8",
    )
    benchmark_file = service_dir / "test_benchmark_exposure_context_service.py"
    benchmark_file.write_text(
        """
def test_benchmark_exposure_source_boundary():
    pass
""",
        encoding="utf-8",
    )

    modules = collect_test_modules((str(tests_root),))
    modules_by_path = {module.path: module for module in modules}

    assert [module.test_count for module in modules] == [2, 1, 1, 1, 1, 1, 1]
    api_module = modules_by_path["tests/integration/test_returns_api.py"]
    contract_module = modules_by_path["tests/unit/app/test_openapi_contract.py"]
    compute_store_module = modules_by_path["tests/unit/services/test_compute_job_store.py"]
    returns_series_module = modules_by_path["tests/unit/services/test_returns_series_service.py"]
    runtime_recovery_module = modules_by_path["tests/unit/services/test_runtime_recovery_service.py"]
    stateful_input_module = modules_by_path["tests/unit/services/test_stateful_input_service.py"]
    benchmark_module = modules_by_path["tests/unit/services/test_benchmark_exposure_context_service.py"]
    assert api_module.suite == "integration"
    assert "api_or_runtime" in api_module.families
    assert contract_module.suite == "unit"
    assert "contract_or_governance" in contract_module.families
    assert compute_store_module.suite == "unit"
    assert "observability_or_readiness" in compute_store_module.families
    assert runtime_recovery_module.suite == "unit"
    assert "observability_or_readiness" in runtime_recovery_module.families
    assert returns_series_module.suite == "unit"
    assert "analytics_domain" in returns_series_module.families
    assert stateful_input_module.suite == "unit"
    assert "analytics_domain" in stateful_input_module.families
    assert benchmark_module.suite == "unit"
    assert "analytics_domain" in benchmark_module.families


def test_render_markdown_summarizes_test_taxonomy() -> None:
    modules = collect_test_modules(("tests/unit/scripts/test_python_test_taxonomy_inventory.py",))

    output = render_markdown(modules, limit=1)

    assert "| Test modules inventoried | 1 |" in output
    assert "| Test functions inventoried | 4 |" in output
    assert "| unit | 1 | 4 |" in output
    assert "| quality_or_security | 4 |" in output
    assert "`tests/unit/scripts/test_python_test_taxonomy_inventory.py`" in output


def test_evaluate_taxonomy_thresholds_passes_at_current_summary() -> None:
    summary = summarize_test_taxonomy(
        [
            TestModuleInventory(
                path="tests/integration/test_performance_api.py",
                suite="integration",
                test_count=607,
                families=("api_or_runtime",),
            ),
            TestModuleInventory(
                path="tests/unit/docs/test_public_docs_contract.py",
                suite="unit",
                test_count=111,
                families=("contract_or_governance",),
            ),
            TestModuleInventory(
                path="tests/unit/services/test_existing_service.py",
                suite="unit",
                test_count=1294,
                families=("uncategorized",),
            ),
        ]
    )

    assert (
        evaluate_taxonomy_thresholds(
            summary,
            min_api_runtime_tests=607,
            min_contract_governance_tests=111,
            max_uncategorized_tests=1294,
        )
        == []
    )


def test_evaluate_taxonomy_thresholds_fails_on_weaker_quality_signal() -> None:
    summary = summarize_test_taxonomy(
        [
            TestModuleInventory(
                path="tests/integration/test_performance_api.py",
                suite="integration",
                test_count=606,
                families=("api_or_runtime",),
            ),
            TestModuleInventory(
                path="tests/unit/docs/test_public_docs_contract.py",
                suite="unit",
                test_count=110,
                families=("contract_or_governance",),
            ),
            TestModuleInventory(
                path="tests/unit/services/test_new_unclassified_service.py",
                suite="unit",
                test_count=1295,
                families=("uncategorized",),
            ),
        ]
    )

    assert evaluate_taxonomy_thresholds(
        summary,
        min_api_runtime_tests=607,
        min_contract_governance_tests=111,
        max_uncategorized_tests=1294,
    ) == [
        "Integration/API/runtime test functions 606 below required floor 607.",
        "Contract/governance test functions 110 below required floor 111.",
        "Uncategorized test functions 1295 above allowed ceiling 1294.",
    ]
