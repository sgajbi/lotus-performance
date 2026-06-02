from scripts.python_architecture_boundary_inventory import (
    ArchitectureBoundaryFinding,
    classify_import,
    render_markdown,
)


def test_classify_router_direct_boundary_imports():
    classification = classify_import("app/api/endpoints/performance.py", "engine.mwr")

    assert classification is not None
    assert classification[0] == "ROUTER_DIRECT_BOUNDARY_IMPORT"


def test_classify_domain_infra_or_framework_imports():
    app_classification = classify_import("engine/mwr.py", "app.models.mwr_requests")
    framework_classification = classify_import("core/errors.py", "fastapi")

    assert app_classification is not None
    assert app_classification[0] == "DOMAIN_INFRA_OR_FRAMEWORK_IMPORT"
    assert framework_classification is not None
    assert framework_classification[0] == "DOMAIN_INFRA_OR_FRAMEWORK_IMPORT"


def test_classify_allows_service_imports_from_routers():
    assert classify_import("app/api/endpoints/performance.py", "app.services.twr_service") is None


def test_render_markdown_summarizes_architecture_findings():
    findings = [
        ArchitectureBoundaryFinding(
            path="app/api/endpoints/performance.py",
            line=54,
            imported_module="engine.mwr",
            rule="ROUTER_DIRECT_BOUNDARY_IMPORT",
            description="router issue",
        ),
        ArchitectureBoundaryFinding(
            path="engine/mwr.py",
            line=8,
            imported_module="app.models.mwr_requests",
            rule="DOMAIN_INFRA_OR_FRAMEWORK_IMPORT",
            description="domain issue",
        ),
    ]

    output = render_markdown(findings, limit=1)

    assert "| Architecture boundary findings | 2 |" in output
    assert "| Distinct rules | 2 |" in output
    assert "| API routers | 1 |" in output
    assert "| Engine | 1 |" in output
    assert "| `ROUTER_DIRECT_BOUNDARY_IMPORT` | 1 |" in output
    assert (
        "| 1 | `ROUTER_DIRECT_BOUNDARY_IMPORT` | `app/api/endpoints/performance.py:54` | `engine.mwr` | router issue |"
        in output
    )
    assert "`engine/mwr.py:8`" not in output
