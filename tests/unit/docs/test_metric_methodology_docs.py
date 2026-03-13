from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
METRICS_DIR = REPO_ROOT / "docs" / "methodologies" / "metrics"
EXPECTED_SECTIONS = [
    "## Metric",
    "## Endpoint and Mode Coverage",
    "## Inputs",
    "## Upstream Data Sources",
    "## Unit Conventions",
    "## Variable Dictionary",
    "## Methodology and Formulas",
    "## Step-by-Step Computation",
    "## Validation and Failure Behavior",
    "## Configuration Options",
    "## Outputs",
    "## Worked Example",
]
METRIC_DOCS = sorted(path for path in METRICS_DIR.glob("metric-*.md"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_metric_methodology_docs_follow_v3_section_order():
    assert METRIC_DOCS, "Expected at least one metric methodology document."

    for path in METRIC_DOCS:
        headings = [line.strip() for line in _read(path).splitlines() if line.startswith("## ")]
        assert headings == EXPECTED_SECTIONS, f"{path.name} does not match the v3 methodology section order."


def test_metric_methodology_docs_include_worked_example_output_mapping_and_no_placeholders():
    placeholder_tokens = ("TODO", "TBD", "FIXME", "placeholder")

    for path in METRIC_DOCS:
        content = _read(path)
        assert "## Worked Example" in content, f"{path.name} is missing a worked example section."
        assert "|---|" in content, f"{path.name} is missing a worked-example table."
        assert "mapping" in content.lower(), f"{path.name} is missing explicit output mapping."
        for token in placeholder_tokens:
            assert token not in content, f"{path.name} still contains placeholder token {token!r}."


def test_methodology_master_index_covers_all_metric_docs_and_describes_v3_standard():
    index_path = METRICS_DIR / "master-index.md"
    index = _read(index_path)

    for path in METRIC_DOCS:
        assert path.name in index, f"{path.name} is not linked from the methodology master index."

    assert "strict v3 methodology standard" in index
    assert "## Metric" in index
    assert "## Worked Example" in index
