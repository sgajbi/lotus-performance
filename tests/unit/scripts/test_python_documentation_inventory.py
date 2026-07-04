from scripts.python_documentation_inventory import (
    DocumentationInventory,
    PublicDefinitionDocstringGap,
    collect_documentation_inventory,
    render_markdown,
)


def test_collect_documentation_inventory_finds_current_doc_surfaces() -> None:
    inventory = collect_documentation_inventory()

    assert inventory.readme_markers_present == inventory.readme_markers_expected
    assert inventory.wiki_pages >= 15
    assert inventory.markdown_files > inventory.wiki_pages
    assert inventory.guide_files >= 10
    assert inventory.methodology_files >= 10
    assert inventory.operations_files >= 3
    assert inventory.rfc_files >= 30
    assert inventory.api_catalog_files_present == inventory.api_catalog_files_expected
    assert inventory.major_pack_readmes_present == inventory.major_pack_readmes_expected
    assert inventory.docs_test_functions >= 40
    assert inventory.public_definitions > 0
    assert inventory.public_definitions_missing_docstring > 0


def test_render_markdown_reports_docstring_gap_details() -> None:
    inventory = DocumentationInventory(
        readme_markers_present=8,
        readme_markers_expected=8,
        wiki_pages=20,
        markdown_files=80,
        guide_files=15,
        methodology_files=10,
        operations_files=3,
        rfc_files=30,
        certification_files=5,
        api_catalog_files_present=4,
        api_catalog_files_expected=4,
        major_pack_readmes_present=12,
        major_pack_readmes_expected=12,
        docs_test_functions=47,
        public_definitions=10,
        public_definitions_missing_docstring=3,
    )
    gaps = (
        PublicDefinitionDocstringGap(
            path="app/example.py",
            line=12,
            name="ExampleService",
            kind="ClassDef",
        ),
    )

    output = render_markdown(inventory, gaps, limit=1)

    assert "| README required markers present | 8 |" in output
    assert "| Public definition docstring coverage percent | 70.00 |" in output
    assert "| Major pack README files present | 12 |" in output
    assert "| endpoint certification | 5 |" in output
    assert "`app/example.py`" in output
    assert "`ExampleService`" in output
