from scripts.python_architecture_boundary_inventory import (
    ArchitectureBoundaryFinding,
    classify_import,
    collect_architecture_findings,
    is_enforced_rule,
    max_findings_violation,
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


def test_classify_application_service_concrete_store_imports_as_report_only():
    classification = classify_import("app/services/execution_polling_service.py", "app.services.execution_registry")

    assert classification is not None
    assert classification[0] == "APPLICATION_SERVICE_CONCRETE_STORE_IMPORT"
    assert not is_enforced_rule(classification[0])


def test_collect_architecture_findings_flags_route_workflow_dto_direct_calls(tmp_path):
    endpoint_dir = tmp_path / "app" / "api" / "endpoints"
    endpoint_dir.mkdir(parents=True)
    endpoint_path = endpoint_dir / "performance.py"
    endpoint_path.write_text(
        "\n".join(
            [
                "async def calculate_twr_endpoint(request):",
                "    return await calculate_twr_workflow(request)",
                "",
                "async def calculate_safe_twr_endpoint(request):",
                "    return await calculate_twr_workflow(map_twr_request(request))",
            ]
        ),
        encoding="utf-8",
    )

    findings = collect_architecture_findings(("app/api/endpoints",), root=tmp_path)

    direct_call_findings = [finding for finding in findings if finding.rule == "ROUTE_WORKFLOW_DTO_DIRECT_CALL"]
    assert len(direct_call_findings) == 1
    assert direct_call_findings[0].path == "app/api/endpoints/performance.py"
    assert direct_call_findings[0].imported_module == "calculate_twr_workflow"
    assert direct_call_findings[0].enforced


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
        ArchitectureBoundaryFinding(
            path="app/services/runtime_status_queue.py",
            line=6,
            imported_module="app.services.compute_job_store",
            rule="APPLICATION_SERVICE_CONCRETE_STORE_IMPORT",
            description="report-only app service issue",
            enforced=False,
        ),
    ]

    output = render_markdown(findings, limit=1)

    assert "| Architecture boundary findings | 3 |" in output
    assert "| Enforced findings | 2 |" in output
    assert "| Report-only findings | 1 |" in output
    assert "| Distinct rules | 3 |" in output
    assert "| API routers | 1 |" in output
    assert "| Engine | 1 |" in output
    assert "| Application services | 1 |" in output
    assert "| `ROUTER_DIRECT_BOUNDARY_IMPORT` | 1 |" in output
    assert (
        "| 1 | `ROUTER_DIRECT_BOUNDARY_IMPORT` | enforced | `app/api/endpoints/performance.py:54` | `engine.mwr` | router issue |"
        in output
    )
    assert "`engine/mwr.py:8`" not in output


def test_max_findings_violation_enforces_architecture_boundary_gate():
    assert max_findings_violation(0, 0) is None
    assert max_findings_violation(1, None) is None
    assert max_findings_violation(2, 1) == (
        "Architecture boundary gate failed: 2 finding(s) exceed configured maximum 1."
    )
