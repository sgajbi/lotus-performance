from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_uses_current_twr_contract_terms():
    readme = _read("README.md")

    assert "analyses" in readme
    assert "valuation_points" in readme
    assert "Older examples using `period_type`" in readme
    assert "`daily_data` are not current" in readme
    assert "google.com/search" not in readme


def test_user_guide_documents_async_execution_surfaces():
    guide = _read("docs/Portfolio Performance Analytics - A User Guide.md")

    assert "/performance/executions/{calculation_id}" in guide
    assert "/integration/returns/series/results/{calculation_id}" in guide
    assert "/integration/runtime-status" in guide
    assert "/performance/lineage/{calculation_id}/artifacts/{artifact_name}" in guide


def test_twr_guide_uses_current_request_shape():
    guide = _read("docs/guides/twr.md")

    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using `period_type`" in guide
    assert "`daily_data` are not current" in guide


def test_mwr_guide_matches_current_method_reality():
    guide = _read("docs/guides/mwr.md")

    assert 'mwr_method="MODIFIED_DIETZ"' in guide
    assert "maps to the same implemented Dietz computation path" in guide
    assert "[cite_start]" not in guide


def test_methodology_index_points_to_current_guides():
    index = _read("docs/technical/methodology_index.md")

    assert "../guides/twr.md" in index
    assert "../guides/api_reference.md" in index
    assert "period_type" in index


def test_standalone_guide_uses_current_engine_api():
    guide = _read("docs/guides/standalone_engine_usage.md")

    assert "results_df, diagnostics = run_calculations" in guide
    assert "google.com/search" not in guide


def test_contribution_guide_uses_current_request_shape():
    guide = _read("docs/guides/contribution.md")

    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using nested `daily_data`" in guide
    assert "one hierarchy result under each `results_by_period.<period>` key" in guide


def test_attribution_guide_uses_current_request_shape():
    guide = _read("docs/guides/attribution.md")

    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using request-level `period_type`" in guide
    assert "- `model`" in guide
    assert "- `linking`" in guide
    assert "currency_attribution" in guide
    assert '`group_by` includes the `currency` dimension' in guide
