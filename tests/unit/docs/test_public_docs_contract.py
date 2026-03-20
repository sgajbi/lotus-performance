import json
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
    assert "include_benchmark" in readme
    assert "relative_performance" in readme
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
    assert "include_benchmark=true" in guide
    assert 'benchmark.input_mode="stateless" | "stateful"' in guide
    assert 'benchmark.return_source="calculated" | "vendor_series"' in guide
    assert "benchmark.stateless_input.component_price_points" in guide
    assert "relative_performance" in guide
    assert "summary.cumulative_return" in guide
    assert "If `calculation_id` is omitted" in guide
    assert "/performance/twr/results/{calculation_id}" in guide
    assert "Older examples using `period_type`" in guide
    assert "`daily_data` are not current" in guide
    assert "stateful_input.consumer_system" not in guide


def test_benchmark_guide_uses_current_request_shape():
    guide = _read("docs/guides/benchmark.md")
    api_reference = _read("docs/guides/api_reference.md")
    readme = _read("README.md")

    assert 'input_mode="stateless"' in guide
    assert 'input_mode="stateful"' in guide
    assert 'return_source="calculated"' in guide
    assert 'return_source="vendor_series"' in guide
    assert "stateless_input.component_price_points" in guide
    assert "multi-segment benchmark composition windows internally" in guide
    assert "benchmark.summary.period_return" in guide
    assert "benchmark.breakdowns.<requested_frequency>[].cumulative_return" in guide
    assert "If `calculation_id` is omitted" in guide
    assert "stateful_input.consumer_system" not in guide
    assert "app.models.benchmark_analytics_requests.BenchmarkAnalyticsRequest" in api_reference
    assert "POST /performance/benchmark" in readme
    assert "TWRAcceptedResponse" in api_reference


def test_mwr_guide_matches_current_method_reality():
    guide = _read("docs/guides/mwr.md")

    assert 'input_mode: "stateless" | "stateful"' in guide
    assert "stateful_input.window_start_date" in guide
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
    api_reference = _read("docs/guides/api_reference.md")
    readme = _read("README.md")

    assert 'input_mode: "stateless" | "stateful"' in guide
    assert "source consumer identity server-side" in guide
    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using nested `daily_data`" in guide
    assert "one hierarchy result under each `results_by_period.<period>` key" in guide
    assert "app.models.contribution_analytics_requests.ContributionAnalyticsRequest" in api_reference
    assert (
        "stateful mode sources portfolio and position timeseries from lotus-core query-control-plane" in api_reference
    )
    assert 'input_mode: "stateless" | "stateful"' in readme
    assert "lotus-performance stamps source consumer identity server-side" in readme


def test_api_reference_documents_endpoint_level_capabilities_contract():
    api_reference = _read("docs/guides/api_reference.md")

    assert "analytics_surfaces" in api_reference
    assert "stateful_restrictions" in api_reference
    assert "supports_async" in api_reference


def test_attribution_guide_uses_current_request_shape():
    guide = _read("docs/guides/attribution.md")

    assert 'input_mode: "stateless" | "stateful"' in guide
    assert "source consumer identity server-side" in guide
    assert '`mode="by_instrument"`' in guide
    assert '`currency_mode="BOTH"` requires `report_ccy`' in guide
    assert "`asset_class`, `sector`, `country`, or `currency`" in guide
    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "Older examples using request-level `period_type`" in guide
    assert "- `model`" in guide
    assert "- `linking`" in guide
    assert "currency_attribution" in guide
    assert "`group_by` includes the `currency` dimension" in guide
    assert "available for both stateless and stateful attribution inputs" in guide
    assert "benchmark engine sourcing path" in guide


def test_returns_series_docs_reflect_benchmark_return_source_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    master_index = _read("docs/methodologies/metrics/master-index.md")
    active_methodology = _read("docs/methodologies/metrics/metric-returns-series-active.md")

    assert 'benchmark.return_source="vendor_series"' in readme
    assert "active_returns" in readme
    assert "stateful benchmark sourcing now defaults to lotus-performance benchmark calculation" in readme
    assert "caller may omit `calculation_id`" in readme
    assert 'benchmark.return_source="vendor_series"' in api_reference
    assert "active_returns" in api_reference
    assert "stateful mode, benchmark sourcing defaults to the shared lotus-performance benchmark calculation path" in api_reference.lower()
    assert "callers may omit `calculation_id`" in api_reference
    assert "Active Return Series" in master_index
    assert "series.active_returns" in active_methodology


def test_api_examples_recipes_match_current_dual_mode_contract():
    guide = _read("docs/API Examples & Recipes.md")

    assert 'input_mode": "stateless"' in guide
    assert 'input_mode": "stateful"' in guide
    assert '"stateless_input"' in guide
    assert '"stateful_input"' in guide
    assert '"analyses"' in guide
    assert '"valuation_points"' in guide
    assert '"include_benchmark": true' in guide
    assert '"relative_performance"' in guide
    assert '"component_price_points"' in guide
    assert "window_start_date" in guide
    assert "consumer_system" not in guide
    assert 'stateful attribution can also emit currency attribution' in guide.lower()
    assert "Older examples using request-level `period_type` or nested `daily_data` are not current." in guide
    assert '"period_type"' not in guide
    assert '"daily_data"' not in guide


def test_json_examples_match_current_dual_mode_contract():
    example_paths = [
        "docs/examples/benchmark_request.json",
        "docs/examples/benchmark_request_price_points.json",
        "docs/examples/benchmark_vendor_series_request.json",
        "docs/examples/twr_request.json",
        "docs/examples/twr_request_with_benchmark.json",
        "docs/examples/twr_request_with_benchmark_price_points.json",
        "docs/examples/twr_request_multiccy_hedged.json",
        "docs/examples/mwr_request.json",
        "docs/examples/contribution_request.json",
        "docs/examples/contribution_request_multiccy.json",
        "docs/examples/attribution_request.json",
        "docs/examples/attribution_request_multiccy.json",
    ]

    for relative_path in example_paths:
        payload = json.loads(_read(relative_path))
        payload_text = json.dumps(payload)

        assert payload["input_mode"] == "stateless"
        assert "period_type" not in payload_text
        assert "daily_data" not in payload_text

    benchmark_request = json.loads(_read("docs/examples/benchmark_request.json"))
    assert "stateless_input" in benchmark_request
    assert benchmark_request["return_source"] == "calculated"

    benchmark_price_request = json.loads(_read("docs/examples/benchmark_request_price_points.json"))
    assert "stateless_input" in benchmark_price_request
    assert "component_price_points" in benchmark_price_request["stateless_input"]
    assert benchmark_price_request["return_source"] == "calculated"

    benchmark_vendor_request = json.loads(_read("docs/examples/benchmark_vendor_series_request.json"))
    assert "stateless_input" in benchmark_vendor_request
    assert benchmark_vendor_request["return_source"] == "vendor_series"

    assert "stateless_input" in json.loads(_read("docs/examples/twr_request.json"))
    benchmark_twr_request = json.loads(_read("docs/examples/twr_request_with_benchmark.json"))
    assert benchmark_twr_request["include_benchmark"] is True
    assert "benchmark" in benchmark_twr_request
    benchmark_twr_price_request = json.loads(_read("docs/examples/twr_request_with_benchmark_price_points.json"))
    assert benchmark_twr_price_request["include_benchmark"] is True
    assert "component_price_points" in benchmark_twr_price_request["benchmark"]["stateless_input"]
    assert "stateless_input" in json.loads(_read("docs/examples/mwr_request.json"))
    assert "stateless_input" in json.loads(_read("docs/examples/contribution_request.json"))
    assert "stateless_input" in json.loads(_read("docs/examples/attribution_request.json"))

    multiccy_attribution = json.loads(_read("docs/examples/attribution_request_multiccy.json"))
    assert multiccy_attribution["currency_mode"] == "BOTH"
    assert multiccy_attribution["input_mode"] == "stateless"


def test_runtime_alert_runbook_covers_breach_gauges():
    runbook = _read("docs/runbooks/runtime-alerts.md")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")

    assert "lotus_performance_compute_queue_degradation_breach" in runbook
    assert "lotus_performance_lineage_queue_degradation_breach" in runbook
    assert "lotus_performance_lineage_storage_pressure_breach" in runbook
    assert "lotus_performance_recovery_drill_degradation_breach" in runbook
    assert "lotus_performance_runtime_retention_degradation_breach" in runbook
    assert "recovery_drill_reclaim_pressure_exceeded" in runbook
    assert "runtime_retention_reclaim_pressure_exceeded" in runbook
    assert "GET /integration/runtime-work-items" in runbook
    assert "GET /integration/runtime-recoveries" in runbook
    assert "GET /integration/recovery-drills" in runbook
    assert "GET /integration/runtime-retention-cleanups" in runbook
    assert "docs/runbooks/runtime-alerts.md" in api_reference
    assert "runtime-alerts.md" in runtime_topology


def test_enterprise_readiness_covers_privileged_operator_reads():
    enterprise = _read("docs/standards/enterprise-readiness.md")
    api_reference = _read("docs/guides/api_reference.md")

    assert "Privileged operator read surfaces can be protected" in enterprise
    assert "Allowed privileged write operations also emit audit metadata" in enterprise
    assert "Allowed privileged operator reads also emit audit metadata" in enterprise
    assert "ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ" in api_reference
    assert "operations.runtime.read" in api_reference
    assert "operations.runtime.manage" in api_reference
    assert "governed surface and required-capability metadata" in api_reference
    assert "/integration/recovery-drills/run" in enterprise


def test_runtime_alert_templates_cover_exported_breach_gauges():
    templates = _read("docs/operations/runtime-alert-rule-templates.md")
    runbook = _read("docs/runbooks/runtime-alerts.md")
    api_reference = _read("docs/guides/api_reference.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")

    assert "lotus_performance_compute_queue_degradation_breach" in templates
    assert "lotus_performance_lineage_queue_degradation_breach" in templates
    assert "lotus_performance_lineage_storage_pressure_breach" in templates
    assert "lotus_performance_recovery_drill_degradation_breach" in templates
    assert "lotus_performance_runtime_retention_degradation_breach" in templates
    assert "lotus_performance_durable_queue_store_availability" in templates
    assert "lotus_performance_lineage_storage_capacity_availability" in templates
    assert "lotus_performance_recovery_drill_availability" in templates
    assert "lotus_performance_runtime_retention_availability" in templates
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
    assert "lotus_performance_runtime_retention_degradation_breach" in policy
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
    assert "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT" in profiles
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS" in profiles
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT" in profiles
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
    assert "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT=5" in development
    assert "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS=604800" in staging
    assert "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT=3" in staging
    assert "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS=259200" in production
    assert "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT=2" in production
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS=1209600" in development
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT=5" in development
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS=604800" in staging
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT=3" in staging
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS=259200" in production
    assert "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT=2" in production
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
    assert 'RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS: "1209600"' in development
    assert 'RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT: "5"' in development
    assert 'RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS: "604800"' in staging
    assert 'RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT: "3"' in staging
    assert 'RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS: "259200"' in production
    assert 'RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT: "2"' in production
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
    assert "GET /integration/runtime-retention-cleanups" in runbook
    assert "POST /integration/runtime-retention-cleanups/run" in runbook
    assert "RUNTIME_RETENTION_DAYS" in runbook
    assert "analytics_execution" in runbook
    assert "analytics_compute_job" in runbook
    assert "analytics_async_result" in runbook
    assert "lineage_records" in runbook
    assert "LINEAGE_STORAGE_PATH" in runbook
    assert "runtime_retention.preview_status" in runbook
    assert "trigger_mode" in runbook
    assert "job_id" in runbook
    assert "make runtime-retention-smoke" in runbook
    assert "docs/runbooks/runtime-retention-cleanup.md" in api_reference
    assert "/integration/runtime-retention-cleanups" in api_reference
    assert "/integration/runtime-retention-cleanups/run" in api_reference
    assert "trigger_mode" in api_reference
    assert "tenant_id" in api_reference
    assert "correlation_id" in api_reference


def test_recovery_drill_control_plane_is_governed():
    api_reference = _read("docs/guides/api_reference.md")

    assert "GET /integration/recovery-drills" in api_reference
    assert "POST /integration/recovery-drills/run" in api_reference
    assert "backup_identifier" in api_reference
    assert "tenant_id" in api_reference
    assert "correlation_id" in api_reference
    assert "job_id" in api_reference
    assert "make runtime-retention-smoke" in api_reference
    assert "lotus_performance_runtime_retention_preview_availability" in api_reference
    assert "lotus_performance_runtime_retention_prunable_items" in api_reference
