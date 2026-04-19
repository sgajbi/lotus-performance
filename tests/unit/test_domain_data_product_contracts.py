from scripts.validate_domain_data_product_contracts import (
    LOCAL_DECLARATION_DIR,
    _collect_required_upstream_product_paths,
    validate_repo_native_contracts,
)


def test_repo_native_domain_data_product_validation_passes() -> None:
    assert validate_repo_native_contracts() == []


def test_repo_native_domain_data_product_directory_contains_expected_files() -> None:
    declaration_names = {path.name for path in LOCAL_DECLARATION_DIR.glob("*.json")}

    assert declaration_names == {
        "lotus-performance-products.v1.json",
        "lotus-performance-consumers.v1.json",
    }


def test_repo_native_declaration_readme_documents_local_validation_path() -> None:
    readme = (LOCAL_DECLARATION_DIR / "README.md").read_text(encoding="utf-8")

    assert "python scripts/validate_domain_data_product_contracts.py" in readme
    assert "make domain-product-validate" in readme
    assert "docs/technical/RFC-0082-upstream-contract-family-map.md" in readme


def test_repo_native_validation_script_stages_upstream_core_products() -> None:
    upstream_paths = _collect_required_upstream_product_paths(LOCAL_DECLARATION_DIR)

    assert [path.name for path in upstream_paths] == ["lotus-core-products.v1.json"]
