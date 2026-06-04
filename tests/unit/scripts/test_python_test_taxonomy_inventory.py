from pathlib import Path

from scripts.python_test_taxonomy_inventory import collect_test_modules, render_markdown


def test_collect_test_modules_counts_functions_and_classifies_families(tmp_path: Path) -> None:
    tests_root = tmp_path / "tests"
    api_dir = tests_root / "integration"
    api_dir.mkdir(parents=True)
    contract_dir = tests_root / "unit" / "app"
    contract_dir.mkdir(parents=True)
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

    modules = collect_test_modules((str(tests_root),))

    assert [module.test_count for module in modules] == [2, 1]
    assert modules[0].suite == "integration"
    assert "api_or_runtime" in modules[0].families
    assert modules[1].suite == "unit"
    assert "contract_or_governance" in modules[1].families


def test_render_markdown_summarizes_test_taxonomy() -> None:
    modules = collect_test_modules(("tests/unit/scripts/test_python_test_taxonomy_inventory.py",))

    output = render_markdown(modules, limit=1)

    assert "| Test modules inventoried | 1 |" in output
    assert "| Test functions inventoried | 2 |" in output
    assert "| unit | 1 | 2 |" in output
    assert "| quality_or_security | 2 |" in output
    assert "`tests/unit/scripts/test_python_test_taxonomy_inventory.py`" in output
