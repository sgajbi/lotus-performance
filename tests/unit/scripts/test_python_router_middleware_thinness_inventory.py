from pathlib import Path

from scripts.python_router_middleware_thinness_inventory import (
    ThinnessFinding,
    collect_thinness_findings,
    max_findings_violation,
    render_markdown,
)


def test_collect_thinness_findings_only_router_and_middleware_paths(tmp_path: Path):
    endpoint_file = tmp_path / "app" / "api" / "endpoints" / "sample.py"
    middleware_file = tmp_path / "app" / "enterprise_audit_middleware.py"
    unrelated_file = tmp_path / "app" / "services" / "sample.py"
    endpoint_file.parent.mkdir(parents=True)
    unrelated_file.parent.mkdir(parents=True)

    endpoint_file.write_text(
        "\n".join(
            [
                "def compact(x):",
                "    return x",
                "",
                "def endpoint_handler():",
                "    line1 = 1",
                "    line2 = 2",
                "    line3 = 3",
                "    line4 = 4",
                "    line5 = 5",
                "    line6 = 6",
                "    line7 = 7",
                "    line8 = 8",
                "    line9 = 9",
                "    line10 = 10",
            ],
        ),
        encoding="utf-8",
    )
    middleware_file.write_text(
        "\n".join(
            [
                "async def call_with_middleware(x, call_next):",
                "    step1 = 1",
                "    step2 = 2",
                "    step3 = 3",
                "    step4 = 4",
                "    step5 = 5",
                "    step6 = 6",
                "    step7 = 7",
                "    step8 = 8",
                "    step9 = 9",
                "    step10 = 10",
            ],
        ),
        encoding="utf-8",
    )
    unrelated_file.write_text(
        "\n".join(
            [
                "def long_service_method():",
                "    a = 1",
                "    b = 2",
                "    c = 3",
                "    d = 4",
                "    e = 5",
                "    f = 6",
                "    g = 7",
                "    h = 8",
                "    i = 9",
                "    j = 10",
            ],
        ),
        encoding="utf-8",
    )

    findings = collect_thinness_findings(["app/api/endpoints", "app"], root=tmp_path, threshold=5)
    kinds = sorted((finding.kind for finding in findings))

    assert kinds == ["middleware", "router"]
    assert findings[0].path == "app/enterprise_audit_middleware.py"
    assert findings[1].path == "app/api/endpoints/sample.py"


def test_render_markdown_reports_findings_order():
    output = render_markdown(
        [
            ThinnessFinding(
                path="app/api/endpoints/sample.py",
                qualified_name="endpoint_handler",
                start_line=1,
                end_line=5,
                lines=5,
                kind="router",
            ),
            ThinnessFinding(
                path="app/enterprise_audit_middleware.py",
                qualified_name="call_with_middleware",
                start_line=10,
                end_line=18,
                lines=9,
                kind="middleware",
            ),
        ],
        limit=2,
    )

    assert "| Router and middleware oversized function findings | 2 |" in output
    assert "| 1 | router | `app/api/endpoints/sample.py:1` | `endpoint_handler` | 5 |" in output


def test_max_findings_violation_enforces_router_middleware_thinness_gate():
    assert max_findings_violation(0, 0) is None
    assert max_findings_violation(1, None) is None
    assert max_findings_violation(3, 2) == (
        "Router/middleware thinness gate failed: 3 finding(s) exceed configured maximum 2."
    )
