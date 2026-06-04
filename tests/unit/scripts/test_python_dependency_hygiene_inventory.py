from pathlib import Path

from scripts.python_dependency_hygiene_inventory import build_deptry_command, parse_deptry_payload, render_markdown


def test_build_deptry_command_includes_reviewed_runtime_only_dependency_ignores():
    command = build_deptry_command((".",), output_path=Path("deptry-report.json"), known_first_party=("app",))

    assert command[:4] == [command[0], "-m", "deptry", "."]
    assert "--known-first-party" in command
    assert "--per-rule-ignores" in command
    assert "DEP002=psycopg|uvicorn" in command


def test_parse_deptry_payload_normalizes_and_orders_issues():
    payload = [
        {
            "error": {"code": "DEP003", "message": "'numpy' imported but it is a transitive dependency"},
            "module": "numpy",
            "location": {"file": "engine\\compute.py", "line": 6, "column": 8},
        },
        {
            "error": {"code": "DEP002", "message": "'uvicorn' defined as a dependency but not used in the codebase"},
            "module": "uvicorn",
            "location": {"file": "pyproject.toml", "line": None, "column": None},
        },
    ]

    issues = parse_deptry_payload(payload)

    assert [issue.code for issue in issues] == ["DEP002", "DEP003"]
    assert issues[0].module == "uvicorn"
    assert issues[0].line is None
    assert issues[1].path == "engine/compute.py"
    assert issues[1].line == 6


def test_render_markdown_summarizes_codes_modules_areas_and_findings():
    issues = parse_deptry_payload(
        [
            {
                "error": {"code": "DEP003", "message": "'httpx' imported but it is a transitive dependency"},
                "module": "httpx",
                "location": {"file": "app\\services\\http_resilience.py", "line": 5, "column": 8},
            },
            {
                "error": {"code": "DEP003", "message": "'numpy' imported but it is a transitive dependency"},
                "module": "numpy",
                "location": {"file": "engine\\compute.py", "line": 6, "column": 8},
            },
            {
                "error": {"code": "DEP002", "message": "'uvicorn' defined as a dependency but not used"},
                "module": "uvicorn",
                "location": {"file": "pyproject.toml", "line": None, "column": None},
            },
        ]
    )

    output = render_markdown(issues, limit=2)

    assert "| Total dependency hygiene findings | 3 |" in output
    assert "| DEP002 | 1 |" in output
    assert "| DEP003 | 2 |" in output
    assert "| `numpy` | 1 |" in output
    assert "| Services | 1 |" in output
    assert "| Engine | 1 |" in output
    assert "| Dependency declarations | 1 |" in output
    assert "| 1 | DEP002 | `uvicorn` | `pyproject.toml` | 'uvicorn' defined as a dependency but not used |" in output
    assert "`app/services/http_resilience.py:5`" in output
    assert "`engine/compute.py:6`" not in output
