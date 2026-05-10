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


def test_mwr_methodology_docs_cover_stateful_source_owned_input_resolution():
    xirr = _read(METRICS_DIR / "metric-mwr-xirr.md")
    dietz = _read(METRICS_DIR / "metric-mwr-dietz.md")
    master_index = _read(METRICS_DIR / "master-index.md")

    for content in (xirr, dietz):
        assert "Stateless + Stateful" in master_index
        assert "stateful_input.window_start_date" in content
        assert "CORE_CONTROL_PLANE_BASE_URL" in content
        assert "cross-observation carry-forward capital adjustments" in content
        assert "fee-classified rows" in content
        assert "must not reconstruct" not in content

    assert "resolved start date" in xirr
    assert "MULTIPLE_IRR_ROOTS_DETECTED" in xirr
    assert "holding_period_return" in xirr
    assert "Modified Dietz fallback" in xirr
    assert "dated cash-flow weights" in dietz
    assert "ZERO_DENOMINATOR" in dietz
    assert 'status="FALLBACK_USED"' in dietz
    assert "Stateful MWR resolves lotus-core portfolio timeseries" in master_index


def test_contribution_methodology_docs_cover_stateful_source_owned_input_resolution():
    total = _read(METRICS_DIR / "metric-contribution-total.md")
    local = _read(METRICS_DIR / "metric-contribution-local.md")
    fx = _read(METRICS_DIR / "metric-contribution-fx.md")
    master_index = _read(METRICS_DIR / "master-index.md")

    for content in (total, local, fx):
        assert "stateful payload (`stateful_input`)" in content
        assert "lotus-core portfolio and position timeseries" in content
        assert "stateful_input.metric_basis" in content
        assert "stateful_input.include_cash_flows" in content
        assert "calculation_supportability" in content

    assert "Position Total Contribution | POST /performance/contribution | Stateless + Stateful" in master_index
    assert "Stateful contribution resolves" in master_index


def test_attribution_metric_docs_describe_top_down_linking_factor_explicitly():
    for name in [
        "metric-attribution-allocation.md",
        "metric-attribution-selection.md",
        "metric-attribution-interaction.md",
    ]:
        content = _read(METRICS_DIR / name)
        assert "AR_geo" in content
        assert "AR_arith" in content
        assert "scale" in content


def test_attribution_methodology_docs_cover_stateful_source_owned_input_resolution():
    attribution_docs = [
        "metric-attribution-active-return.md",
        "metric-attribution-allocation.md",
        "metric-attribution-selection.md",
        "metric-attribution-interaction.md",
    ]
    currency_docs = [
        "metric-currency-local-allocation.md",
        "metric-currency-local-selection.md",
        "metric-currency-allocation.md",
        "metric-currency-selection.md",
    ]
    master_index = _read(METRICS_DIR / "master-index.md")

    for name in attribution_docs:
        content = _read(METRICS_DIR / name)
        assert "stateful payload (`stateful_input`)" in content
        assert "lotus-core portfolio" in content
        assert "position timeseries" in content
        assert "benchmark assignment" in content
        assert "benchmark component inputs" in content
        assert "calculation_supportability" in content

    for name in currency_docs:
        content = _read(METRICS_DIR / name)
        assert "stateful attribution inputs" in content
        assert "FX/source currency evidence" in content
        assert "calculation_supportability" in content

    assert "Attribution Allocation Effect | POST /performance/attribution | Stateless + Stateful" in master_index
    assert "Currency Allocation | POST /performance/attribution | Stateless + Stateful" in master_index
    assert "Stateful attribution resolves" in master_index


def test_currency_attribution_metric_docs_describe_total_effect_relationship():
    for name in [
        "metric-currency-local-allocation.md",
        "metric-currency-local-selection.md",
        "metric-currency-allocation.md",
        "metric-currency-selection.md",
    ]:
        content = _read(METRICS_DIR / name)
        assert "TE_c" in content
        assert "total_effect" in content
