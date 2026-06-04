from scripts.python_security_inventory import (
    BanditIssue,
    build_bandit_command,
    parse_bandit_payload,
    parse_bandit_scan,
    render_markdown,
)


def test_build_bandit_command_scans_core_runtime_paths():
    command = build_bandit_command(("app", "engine"))

    assert command[:4] == [command[0], "-m", "bandit", "-q"]
    assert command[4:] == ["-r", "app", "engine", "-f", "json"]


def test_parse_bandit_payload_normalizes_and_orders_issues():
    payload = {
        "results": [
            {
                "filename": "app\\models\\example.py",
                "issue_confidence": "MEDIUM",
                "issue_severity": "LOW",
                "issue_text": "Possible hardcoded password: 'None'",
                "line_number": 20,
                "test_id": "B105",
                "test_name": "hardcoded_password_string",
            },
            {
                "filename": "app\\services\\example.py",
                "issue_confidence": "HIGH",
                "issue_severity": "HIGH",
                "issue_text": "high severity issue",
                "line_number": 10,
                "test_id": "B999",
                "test_name": "example_test",
            },
        ]
    }

    issues = parse_bandit_payload(payload)

    assert [issue.severity for issue in issues] == ["HIGH", "LOW"]
    assert issues[0].filename == "app/services/example.py"
    assert issues[1].filename == "app/models/example.py"


def test_parse_bandit_scan_includes_totals_metrics():
    scan = parse_bandit_scan({"metrics": {"_totals": {"loc": 123, "nosec": 2, "skipped_tests": 4}}, "results": []})

    assert scan.issues == []
    assert scan.lines_scanned == 123
    assert scan.nosec_count == 2
    assert scan.skipped_tests == 4


def test_render_markdown_summarizes_bandit_findings():
    issues = [
        BanditIssue(
            severity="LOW",
            confidence="MEDIUM",
            test_id="B105",
            test_name="hardcoded_password_string",
            filename="app/models/benchmark_exposure_context.py",
            line_number=63,
            issue_text="Possible hardcoded password: 'None'",
        ),
        BanditIssue(
            severity="MEDIUM",
            confidence="HIGH",
            test_id="B999",
            test_name="example_test",
            filename="app/services/example.py",
            line_number=10,
            issue_text="service | issue",
        ),
    ]

    output = render_markdown(issues, limit=2, lines_scanned=123, nosec_count=2, skipped_tests=4)

    assert "| Total Bandit findings | 2 |" in output
    assert "| High severity findings | 0 |" in output
    assert "| Medium severity findings | 1 |" in output
    assert "| Low severity findings | 1 |" in output
    assert "| Lines scanned | 123 |" in output
    assert "| `nosec` markers | 2 |" in output
    assert "| Targeted skipped tests | 4 |" in output
    assert "| HIGH | 1 |" in output
    assert "| MEDIUM | 1 |" in output
    assert "| B105 | 1 |" in output
    assert "| Application models | 1 |" in output
    assert "| Services | 1 |" in output
    assert "service \\| issue" in output
    assert "`app/models/benchmark_exposure_context.py:63`" in output
