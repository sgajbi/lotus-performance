from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _read_lines(relative_path: str) -> list[str]:
    return _read(relative_path).splitlines()


def test_readme_uses_current_twr_contract_terms():
    readme = _read("README.md")

    assert "analyses" in readme
    assert "valuation_points" in readme
    assert "Older examples using `period_type`" in readme
    assert "`daily_data` are not current" in readme
    assert "google.com/search" not in readme


def test_user_guide_documents_async_execution_surfaces():
    guide = _read("docs/Portfolio Performance Analytics - A User Guide.md")

    assert "/performance/executions/{calculation_id}" in guide
    assert "/integration/returns/series/results/{calculation_id}" in guide
    assert "/integration/runtime-status" in guide
    assert "/performance/lineage/{calculation_id}/artifacts/{artifact_name}" in guide


def test_twr_guide_uses_current_request_shape():
    guide = _read("docs/guides/twr.md")

    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using `period_type`" in guide
    assert "`daily_data` are not current" in guide


def test_mwr_guide_matches_current_method_reality():
    guide = _read("docs/guides/mwr.md")

    assert 'mwr_method="MODIFIED_DIETZ"' in guide
    assert "maps to the same implemented Dietz computation path" in guide
    assert "[cite_start]" not in guide


def test_methodology_index_points_to_current_guides():
    index = _read("docs/technical/methodology_index.md")

    assert "../guides/twr.md" in index
    assert "../guides/api_reference.md" in index
    assert "period_type" in index


def test_standalone_guide_uses_current_engine_api():
    guide = _read("docs/guides/standalone_engine_usage.md")

    assert "results_df, diagnostics = run_calculations" in guide
    assert "google.com/search" not in guide


def test_contribution_guide_uses_current_request_shape():
    guide = _read("docs/guides/contribution.md")

    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using nested `daily_data`" in guide
    assert "one hierarchy result under each `results_by_period.<period>` key" in guide


def test_attribution_guide_uses_current_request_shape():
    guide = _read("docs/guides/attribution.md")

    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using request-level `period_type`" in guide
    assert "- `model`" in guide
    assert "- `linking`" in guide
    assert "currency_attribution" in guide
    assert "`group_by` includes the `currency` dimension" in guide


def test_runtime_alert_runbook_covers_breach_gauges():
    runbook = _read("docs/runbooks/runtime-alerts.md")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")

    assert "lotus_performance_compute_queue_degradation_breach" in runbook
    assert "lotus_performance_lineage_queue_degradation_breach" in runbook
    assert "lotus_performance_lineage_storage_pressure_breach" in runbook
    assert "lotus_performance_recovery_drill_degradation_breach" in runbook
    assert "GET /integration/runtime-work-items" in runbook
    assert "GET /integration/runtime-recoveries" in runbook
    assert "GET /integration/recovery-drills" in runbook
    assert "docs/runbooks/runtime-alerts.md" in api_reference
    assert "runtime-alerts.md" in runtime_topology


def test_runtime_alert_templates_cover_exported_breach_gauges():
    templates = _read("docs/operations/runtime-alert-rule-templates.md")
    runbook = _read("docs/runbooks/runtime-alerts.md")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")

    assert "lotus_performance_compute_queue_degradation_breach" in templates
    assert "lotus_performance_lineage_queue_degradation_breach" in templates
    assert "lotus_performance_lineage_storage_pressure_breach" in templates
    assert "lotus_performance_recovery_drill_degradation_breach" in templates
    assert "lotus_performance_durable_queue_store_availability" in templates
    assert "lotus_performance_lineage_storage_capacity_availability" in templates
    assert "lotus_performance_recovery_drill_availability" in templates
    assert "docs/operations/runtime-alert-rule-templates.md" in runbook
    assert "runtime-alert-rule-templates.md" in api_reference
    assert "runtime-alert-rule-templates.md" in runtime_topology


def test_runtime_alert_policy_governs_severity_defaults():
    policy = _read("docs/standards/runtime-alert-policy.md")
    templates = _read("docs/operations/runtime-alert-rule-templates.md")
    runbook = _read("docs/runbooks/runtime-alerts.md")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")
    scalability = _read("docs/standards/scalability-availability.md")
    enterprise = _read("docs/standards/enterprise-readiness.md")

    assert "lotus_performance_compute_queue_degradation_breach" in policy
    assert "lotus_performance_lineage_queue_degradation_breach" in policy
    assert "lotus_performance_lineage_storage_pressure_breach" in policy
    assert "lotus_performance_recovery_drill_degradation_breach" in policy
    assert "`page`" in policy
    assert "`ticket`" in policy
    assert "docs/standards/runtime-alert-policy.md" in templates
    assert "docs/standards/runtime-alert-policy.md" in runbook
    assert "runtime-alert-policy.md" in api_reference
    assert "runtime-alert-policy.md" in runtime_topology
    assert "runtime-alert-policy.md" in scalability
    assert "runtime-alert-policy.md" in enterprise


def test_runtime_threshold_profiles_cover_controlled_settings():
    profiles = _read("docs/standards/runtime-threshold-profiles.md")
    policy = _read("docs/standards/runtime-alert-policy.md")
    templates = _read("docs/operations/runtime-alert-rule-templates.md")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")
    scalability = _read("docs/standards/scalability-availability.md")
    enterprise = _read("docs/standards/enterprise-readiness.md")

    assert "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS" in profiles
    assert "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT" in profiles
    assert "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS" in profiles
    assert "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES" in profiles
    assert "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS" in profiles
    assert "Development" in profiles
    assert "Staging" in profiles
    assert "Production" in profiles
    assert "docs/standards/runtime-threshold-profiles.md" in policy
    assert "docs/standards/runtime-threshold-profiles.md" in templates
    assert "runtime-threshold-profiles.md" in api_reference
    assert "runtime-threshold-profiles.md" in runtime_topology
    assert "runtime-threshold-profiles.md" in scalability
    assert "runtime-threshold-profiles.md" in enterprise


def test_runtime_threshold_env_examples_match_profile_defaults():
    profiles = _read("docs/standards/runtime-threshold-profiles.md")
    development = _read_lines("docs/examples/runtime-thresholds.development.env")
    staging = _read_lines("docs/examples/runtime-thresholds.staging.env")
    production = _read_lines("docs/examples/runtime-thresholds.production.env")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")

    assert "docs/examples/runtime-thresholds.development.env" in profiles
    assert "docs/examples/runtime-thresholds.staging.env" in profiles
    assert "docs/examples/runtime-thresholds.production.env" in profiles
    assert "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS=1800" in development
    assert "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS=900" in staging
    assert "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS=600" in production
    assert "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO=0.10" in development
    assert "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO=0.15" in staging
    assert "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO=0.20" in production
    assert "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS=1209600" in development
    assert "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS=604800" in staging
    assert "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS=259200" in production
    assert "runtime-thresholds.production.env" in api_reference
    assert "docs/examples/" in runtime_topology


def test_runtime_threshold_compose_overlays_match_profile_defaults():
    profiles = _read("docs/standards/runtime-threshold-profiles.md")
    development = _read("docs/examples/docker-compose.runtime-thresholds.development.yml")
    staging = _read("docs/examples/docker-compose.runtime-thresholds.staging.yml")
    production = _read("docs/examples/docker-compose.runtime-thresholds.production.yml")
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")

    assert "docker-compose.runtime-thresholds.development.yml" in profiles
    assert "docker-compose.runtime-thresholds.staging.yml" in profiles
    assert "docker-compose.runtime-thresholds.production.yml" in profiles
    assert 'RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS: "1800"' in development
    assert 'RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS: "900"' in staging
    assert 'RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS: "600"' in production
    assert 'RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO: "0.10"' in development
    assert 'RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO: "0.15"' in staging
    assert 'RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO: "0.20"' in production
    assert (
        "docker compose -f docker-compose.yml -f docs/examples/docker-compose.runtime-thresholds.production.yml up"
        in readme
    )
    assert "docker-compose.runtime-thresholds.production.yml" in api_reference
    assert "docker-compose.yml" in runtime_topology


def test_runtime_retention_cleanup_runbook_is_governed():
    runbook = _read("docs/runbooks/runtime-retention-cleanup.md")
    api_reference = _read("docs/guides/api_reference.md")

    assert "python scripts/runtime_retention_cleanup.py" in runbook
    assert "python scripts/runtime_retention_cleanup.py --apply" in runbook
    assert "RUNTIME_RETENTION_DAYS" in runbook
    assert "analytics_execution" in runbook
    assert "analytics_compute_job" in runbook
    assert "analytics_async_result" in runbook
    assert "lineage_records" in runbook
    assert "LINEAGE_STORAGE_PATH" in runbook
    assert "docs/runbooks/runtime-retention-cleanup.md" in api_reference
