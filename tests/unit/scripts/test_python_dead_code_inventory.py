from scripts.python_dead_code_inventory import parse_vulture_output, render_markdown


def test_parse_vulture_output_normalizes_and_orders_findings():
    output = "\n".join(
        [
            "app\\models\\sample.py:20: unused variable 'model_config' (60% confidence)",
            "app\\services\\worker.py:4: unused function 'run_unused' (80% confidence)",
        ]
    )

    findings = parse_vulture_output(output)

    assert [finding.name for finding in findings] == ["run_unused", "model_config"]
    assert findings[0].path == "app/services/worker.py"
    assert findings[0].line == 4
    assert findings[0].kind == "function"
    assert findings[0].confidence == 80


def test_parse_vulture_output_ignores_unmatched_lines():
    output = "\n".join(
        [
            "noise",
            "",
            "core\\errors.py:24: unused class 'APIUnprocessableEntityError' (60% confidence)",
        ]
    )

    findings = parse_vulture_output(output)

    assert len(findings) == 1
    assert findings[0].name == "APIUnprocessableEntityError"


def test_render_markdown_summarizes_kinds_areas_and_top_findings():
    findings = parse_vulture_output(
        "\n".join(
            [
                "app\\api\\endpoints\\health.py:10: unused function 'health' (60% confidence)",
                "app\\models\\responses.py:66: unused class 'RelativePerformanceSummary' (60% confidence)",
                "engine\\attribution.py:373: unused attribute 'names' (60% confidence)",
            ]
        )
    )

    output = render_markdown(findings, limit=2, min_confidence=60)

    assert "| Total findings | 3 |" in output
    assert "| Distinct files with findings | 3 |" in output
    assert "| function | 1 |" in output
    assert "| API endpoints | 1 |" in output
    assert "| Pydantic models | 1 |" in output
    assert "| Engine | 1 |" in output
    assert "| 1 | `app/api/endpoints/health.py:10` | `health` | function | 60% |" in output
    assert "`engine/attribution.py:373`" not in output
