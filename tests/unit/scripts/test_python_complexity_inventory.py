from scripts.python_complexity_inventory import (
    parse_complexity_payload,
    parse_maintainability_payload,
    render_markdown,
)


def test_parse_complexity_payload_orders_highest_complexity_first():
    payload = {
        "app\\sample.py": [
            {
                "type": "function",
                "rank": "B",
                "complexity": 8,
                "name": "small",
                "lineno": 2,
                "endline": 10,
            },
            {
                "type": "method",
                "rank": "E",
                "complexity": 34,
                "name": "large",
                "lineno": 20,
                "endline": 80,
            },
        ]
    }

    findings = parse_complexity_payload(payload)

    assert [finding.name for finding in findings] == ["large", "small"]
    assert findings[0].path == "app/sample.py"
    assert findings[0].complexity == 34
    assert findings[0].rank == "E"


def test_parse_maintainability_payload_orders_lowest_index_first():
    payload = {
        "app\\healthy.py": {"mi": 81.5, "rank": "A"},
        "app\\hotspot.py": {"mi": 22.1, "rank": "A"},
    }

    findings = parse_maintainability_payload(payload)

    assert [finding.path for finding in findings] == ["app/hotspot.py", "app/healthy.py"]
    assert findings[0].maintainability_index == 22.1


def test_render_markdown_summarizes_complexity_and_maintainability():
    complexity = parse_complexity_payload(
        {
            "app\\sample.py": [
                {
                    "type": "function",
                    "rank": "D",
                    "complexity": 25,
                    "name": "complex_path",
                    "lineno": 5,
                    "endline": 50,
                },
                {
                    "type": "function",
                    "rank": "B",
                    "complexity": 7,
                    "name": "simple_path",
                    "lineno": 60,
                    "endline": 70,
                },
            ]
        }
    )
    maintainability = parse_maintainability_payload(
        {
            "app\\sample.py": {"mi": 40.0, "rank": "A"},
            "app\\other.py": {"mi": 80.0, "rank": "A"},
        }
    )

    output = render_markdown(complexity, maintainability, limit=1)

    assert "| Max cyclomatic complexity | 25 |" in output
    assert "| High-complexity functions (rank D-F) | 1 |" in output
    assert "| Average maintainability index | 60.00 |" in output
    assert "| 1 | `complex_path` | function | `app/sample.py:5` | 25 | D |" in output
    assert "| 1 | `app/sample.py` | 40.00 | A |" in output


def test_render_markdown_handles_empty_findings():
    output = render_markdown([], [], limit=1)

    assert "| Max cyclomatic complexity | 0 |" in output
    assert "| High-complexity functions (rank D-F) | 0 |" in output
    assert "| Average maintainability index | 0.00 |" in output
