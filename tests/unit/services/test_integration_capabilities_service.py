from app.services.integration_capabilities_service import (
    PERFORMANCE_EXECUTION_POLL_PATH_TEMPLATE,
    IntegrationCapabilityFlags,
    _async_analytics_surface,
    _build_feature_capabilities,
    _feature_capability,
    _portfolio_analytics_surfaces,
    _sync_analytics_surface,
    _workflow_enabled,
    build_integration_capabilities_report,
)


def test_build_integration_capabilities_report_default():
    report = build_integration_capabilities_report()

    assert report.supported_input_modes == ["stateful", "stateless"]
    assert report.policy_version == "tenant-default-v1"
    assert len(report.features) == 13
    assert len(report.workflows) == 8

    features = {item["key"]: item for item in report.features}
    workflows = {item["workflow_key"]: item for item in report.workflows}
    surfaces = {item["key"]: item for item in report.analytics_surfaces}

    assert features["performance.analytics.twr"]["enabled"] is True
    assert features["performance.analytics.composite_twr"]["enabled"] is True
    assert features["performance.observability.calculation_supportability"]["enabled"] is True
    assert surfaces["composite_twr"]["supported_input_modes"] == ["persisted_member_facts"]
    assert surfaces["composite_twr"]["supports_async"] is False
    assert surfaces["workspace_summary"]["supports_async"] is True
    assert workflows["composite_performance_publication"]["enabled"] is True
    assert workflows["performance_workspace"]["enabled"] is True
    assert surfaces["twr_inspection"]["contract_notes"]


def test_build_integration_capabilities_report_respects_env_overrides(monkeypatch):
    monkeypatch.setenv("PA_CAP_ATTRIBUTION_ENABLED", "false")
    monkeypatch.setenv("PLATFORM_INPUT_MODE_STATELESS_ENABLED", "false")
    monkeypatch.setenv("PA_POLICY_VERSION", " tenant-a-v4 ")

    report = build_integration_capabilities_report()

    assert report.policy_version == "tenant-a-v4"
    assert report.supported_input_modes == ["stateful"]
    features = {item["key"]: item for item in report.features}
    surfaces = {item["key"]: item for item in report.analytics_surfaces}

    assert features["performance.analytics.attribution"]["enabled"] is False
    assert surfaces["returns_series"]["supported_input_modes"] == ["stateful"]
    assert surfaces["attribution"]["enabled"] is False
    assert surfaces["attribution"]["stateful_restrictions"] == []


def test_build_integration_capabilities_report_blank_values_keep_defaults(monkeypatch):
    monkeypatch.setenv("PA_CAP_TWR_ENABLED", " ")
    monkeypatch.setenv("PLATFORM_INPUT_MODE_STATEFUL_ENABLED", " ")
    monkeypatch.setenv("PA_POLICY_VERSION", " ")

    report = build_integration_capabilities_report()

    assert report.policy_version == "tenant-default-v1"
    assert report.supported_input_modes == ["stateful", "stateless"]
    assert {item["key"] for item in report.features} == {
        "performance.analytics.twr",
        "performance.analytics.mwr",
        "performance.analytics.contribution",
        "performance.analytics.attribution",
        "performance.analytics.benchmark",
        "performance.analytics.composite_twr",
        "performance.integration.benchmark_exposure_context",
        "performance.analytics.workspace_summary",
        "performance.support.twr_inspection",
        "performance.observability.calculation_supportability",
        "performance.integration.mandate_performance_health_context",
        "performance.execution.stateful",
        "performance.execution.stateless",
    }


def test_build_integration_capabilities_report_limits_are_applied():
    report = build_integration_capabilities_report(feature_limit=2, workflow_limit=1)

    assert len(report.features) == 2
    assert len(report.workflows) == 1
    assert report.features[0]["key"] == "performance.analytics.twr"
    assert report.workflows[0]["workflow_key"] == "performance_snapshot"


def test_feature_capability_projects_owner_and_description():
    assert _feature_capability(
        key="performance.analytics.twr",
        enabled=True,
        description="Portfolio-level time-weighted return analytics APIs.",
    ) == {
        "key": "performance.analytics.twr",
        "enabled": True,
        "owner_service": "lotus-performance",
        "description": "Portfolio-level time-weighted return analytics APIs.",
    }


def test_feature_capabilities_preserve_publication_order_and_flags():
    flags = IntegrationCapabilityFlags(
        twr_enabled=True,
        mwr_enabled=True,
        contribution_enabled=True,
        attribution_enabled=False,
        benchmark_enabled=True,
        workspace_summary_enabled=False,
        composite_twr_enabled=True,
        stateful_mode_enabled=False,
        stateless_mode_enabled=True,
        policy_version="tenant-default-v1",
    )

    features = _build_feature_capabilities(flags)

    assert [feature["key"] for feature in features] == [
        "performance.analytics.twr",
        "performance.analytics.mwr",
        "performance.analytics.contribution",
        "performance.analytics.attribution",
        "performance.analytics.benchmark",
        "performance.integration.benchmark_exposure_context",
        "performance.analytics.workspace_summary",
        "performance.analytics.composite_twr",
        "performance.support.twr_inspection",
        "performance.observability.calculation_supportability",
        "performance.integration.mandate_performance_health_context",
        "performance.execution.stateful",
        "performance.execution.stateless",
    ]
    feature_flags = {feature["key"]: feature["enabled"] for feature in features}
    assert feature_flags["performance.analytics.attribution"] is False
    assert feature_flags["performance.integration.benchmark_exposure_context"] is False
    assert feature_flags["performance.analytics.workspace_summary"] is False
    assert feature_flags["performance.observability.calculation_supportability"] is True
    assert feature_flags["performance.execution.stateful"] is False
    assert feature_flags["performance.execution.stateless"] is True
    assert {feature["owner_service"] for feature in features} == {"lotus-performance"}


def test_async_analytics_surface_projects_execution_contract():
    supported_input_modes = ["stateful", "stateless"]
    stateful_restrictions = ["mode=by_instrument only"]
    contract_notes = ["supports portfolio-level analytics"]
    options = [{"key": "period", "supported_values": ["YTD"]}]

    surface = _async_analytics_surface(
        key="attribution",
        path="/performance/attribution",
        enabled=True,
        supported_input_modes=supported_input_modes,
        result_path_template="/performance/attribution/results/{calculation_id}",
        stateful_restrictions=stateful_restrictions,
        contract_notes=contract_notes,
        options=options,
    )

    assert surface == {
        "key": "attribution",
        "path": "/performance/attribution",
        "enabled": True,
        "supported_input_modes": ["stateful", "stateless"],
        "supports_async": True,
        "poll_path_template": PERFORMANCE_EXECUTION_POLL_PATH_TEMPLATE,
        "result_path_template": "/performance/attribution/results/{calculation_id}",
        "stateful_restrictions": ["mode=by_instrument only"],
        "contract_notes": ["supports portfolio-level analytics"],
        "options": [{"key": "period", "supported_values": ["YTD"]}],
    }

    supported_input_modes.append("unsupported")
    stateful_restrictions.append("unsupported")
    contract_notes.append("unsupported")
    options.append({"key": "unsupported"})

    assert surface["supported_input_modes"] == ["stateful", "stateless"]
    assert surface["stateful_restrictions"] == ["mode=by_instrument only"]
    assert surface["contract_notes"] == ["supports portfolio-level analytics"]
    assert surface["options"] == [{"key": "period", "supported_values": ["YTD"]}]


def test_sync_analytics_surface_projects_non_async_contract():
    supported_input_modes = ["stateful"]
    stateful_restrictions = ["lotus-core remains the source of record"]
    contract_notes = ["lineage-backed benchmark exposure view"]
    options = [{"key": "group_by", "supported_values": ["POSITION"]}]

    surface = _sync_analytics_surface(
        key="benchmark_exposure_context",
        path="/integration/benchmarks/exposure-context",
        enabled=True,
        supported_input_modes=supported_input_modes,
        stateful_restrictions=stateful_restrictions,
        contract_notes=contract_notes,
        options=options,
    )

    assert surface == {
        "key": "benchmark_exposure_context",
        "path": "/integration/benchmarks/exposure-context",
        "enabled": True,
        "supported_input_modes": ["stateful"],
        "supports_async": False,
        "poll_path_template": None,
        "result_path_template": None,
        "stateful_restrictions": ["lotus-core remains the source of record"],
        "contract_notes": ["lineage-backed benchmark exposure view"],
        "options": [{"key": "group_by", "supported_values": ["POSITION"]}],
    }

    supported_input_modes.append("unsupported")
    stateful_restrictions.append("unsupported")
    contract_notes.append("unsupported")
    options.append({"key": "unsupported"})

    assert surface["supported_input_modes"] == ["stateful"]
    assert surface["stateful_restrictions"] == ["lotus-core remains the source of record"]
    assert surface["contract_notes"] == ["lineage-backed benchmark exposure view"]
    assert surface["options"] == [{"key": "group_by", "supported_values": ["POSITION"]}]


def test_portfolio_analytics_surfaces_project_governed_surface_group():
    flags = IntegrationCapabilityFlags(
        twr_enabled=True,
        mwr_enabled=True,
        contribution_enabled=True,
        attribution_enabled=True,
        benchmark_enabled=True,
        workspace_summary_enabled=False,
        composite_twr_enabled=True,
        stateful_mode_enabled=True,
        stateless_mode_enabled=True,
        policy_version="tenant-default-v1",
    )

    surfaces = _portfolio_analytics_surfaces(flags=flags, supported_input_modes=["stateful", "stateless"])

    assert [surface["key"] for surface in surfaces] == [
        "twr",
        "twr_inspection",
        "mwr",
        "benchmark",
        "workspace_summary",
    ]
    assert surfaces[0]["contract_notes"] == [
        "supports portfolio-level TWR only",
        "does not advertise composite, group, or sleeve TWR calculation support",
    ]
    assert surfaces[2]["supports_async"] is False
    assert surfaces[4]["enabled"] is False
    assert surfaces[4]["contract_notes"] == []
    assert surfaces[4]["options"] == []


def test_workflow_enabled_requires_every_feature_flag():
    assert _workflow_enabled(True, True, True) is True
    assert _workflow_enabled(True, False, True) is False
    assert _workflow_enabled(False) is False


def test_build_integration_capabilities_report_supportability_stays_enabled_without_twr(monkeypatch):
    monkeypatch.setenv("PA_CAP_TWR_ENABLED", "false")

    report = build_integration_capabilities_report()
    features = {item["key"]: item for item in report.features}
    surfaces = {item["key"]: item for item in report.analytics_surfaces}

    assert surfaces["twr"]["enabled"] is False
    assert features["performance.support.twr_inspection"]["enabled"] is False
    assert features["performance.observability.calculation_supportability"]["enabled"] is True
    assert surfaces["twr_inspection"]["contract_notes"] == []
    assert surfaces["twr_inspection"]["options"] == []


def test_build_integration_capabilities_report_hides_workspace_options_when_disabled(monkeypatch):
    monkeypatch.setenv("PA_CAP_WORKSPACE_SUMMARY_ENABLED", "false")

    report = build_integration_capabilities_report()
    features = {item["key"]: item for item in report.features}
    workflows = {item["workflow_key"]: item for item in report.workflows}
    surfaces = {item["key"]: item for item in report.analytics_surfaces}

    assert features["performance.analytics.workspace_summary"]["enabled"] is False
    assert workflows["performance_workspace"]["enabled"] is False
    assert surfaces["workspace_summary"]["enabled"] is False
    assert surfaces["workspace_summary"]["contract_notes"] == []
    assert surfaces["workspace_summary"]["options"] == []


def test_build_integration_capabilities_report_hides_benchmark_exposure_details_without_stateful_mode(
    monkeypatch,
):
    monkeypatch.setenv("PLATFORM_INPUT_MODE_STATEFUL_ENABLED", "false")

    report = build_integration_capabilities_report()
    features = {item["key"]: item for item in report.features}
    surfaces = {item["key"]: item for item in report.analytics_surfaces}

    assert features["performance.integration.benchmark_exposure_context"]["enabled"] is False
    assert surfaces["benchmark_exposure_context"]["enabled"] is False
    assert surfaces["benchmark_exposure_context"]["supported_input_modes"] == []
    assert surfaces["benchmark_exposure_context"]["stateful_restrictions"] == []
    assert surfaces["benchmark_exposure_context"]["contract_notes"] == []
