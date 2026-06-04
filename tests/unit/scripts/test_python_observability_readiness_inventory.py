from scripts.python_observability_readiness_inventory import collect_readiness_surfaces, render_markdown


def test_collect_readiness_surfaces_reports_endpoint_and_marker_coverage() -> None:
    surfaces = collect_readiness_surfaces(
        schema={"paths": {"/health": {}, "/health/live": {}, "/health/ready": {}, "/metrics": {}}},
        test_paths=("tests/unit/test_observability.py",),
    )

    by_family = {surface.family: surface for surface in surfaces}

    assert by_family["health_metrics_endpoints"].present_markers == 4
    assert by_family["health_metrics_endpoints"].expected_markers == 4
    assert by_family["correlation_propagation"].present_markers == 6
    assert by_family["structured_logging"].present_markers == 6
    assert by_family["metrics"].present_markers == 6
    assert by_family["health_readiness"].present_markers == 6
    assert by_family["correlation_propagation"].test_functions > 0


def test_render_markdown_summarizes_missing_markers() -> None:
    surfaces = collect_readiness_surfaces(
        schema={"paths": {"/health": {}, "/metrics": {}}},
        test_paths=("tests/unit/test_observability.py",),
    )

    output = render_markdown(surfaces, limit=5)

    assert "| Operational readiness families | 5 |" in output
    assert "| Expected implementation markers | 28 |" in output
    assert "| Missing implementation markers | 2 |" in output
    assert "`/health/live`" in output
    assert "`/health/ready`" in output
