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
    assert "benchmark_context" in readme
    assert "Older examples using `period_type`" in readme
    assert "`daily_data` are not current" in readme
    assert "google.com/search" not in readme


def test_user_guide_documents_async_execution_surfaces():
    guide = _read("docs/Portfolio Performance Analytics - A User Guide.md")

    assert "/performance/executions/{calculation_id}" in guide
    assert "/performance/twr/results/{calculation_id}" in guide
    assert "/performance/benchmark/results/{calculation_id}" in guide
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
    assert "benchmark_context" in guide
    assert "summary.cumulative_return" in guide
    assert '"portfolio": {' in guide
    assert '"portfolio_return"' not in guide.split("## Example stateful request")[0]
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
    assert "position_contributions[].average_weight" in guide
    assert "levels[].rows[].weight_avg" in guide
    assert "position_contributions` remains the first-class output" in guide
    assert "app.models.contribution_analytics_requests.ContributionAnalyticsRequest" in api_reference
    assert (
        "stateful mode sources portfolio and position timeseries from lotus-core query-control-plane" in api_reference
    )
    assert (
        "position-level `average_weight` and grouped `weight_avg` are both emitted in percentage units" in api_reference
    )
    assert 'input_mode: "stateless" | "stateful"' in readme
    assert "lotus-performance stamps source consumer identity server-side" in readme


def test_api_reference_documents_endpoint_level_capabilities_contract():
    api_reference = _read("docs/guides/api_reference.md")
    readme = _read("README.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")

    assert "analytics_surfaces" in api_reference
    assert "stateful_restrictions" in api_reference
    assert "supports_async" in api_reference
    assert "contract_notes" in api_reference
    assert "poll_path_template" in api_reference
    assert "result_path_template" in api_reference
    assert "options" in api_reference
    assert "docs/examples/integration_capabilities_response.json" in api_reference
    assert "/performance/twr/results/{calculation_id}" in readme
    assert "/performance/benchmark/results/{calculation_id}" in readme
    assert "/performance/twr/results/{calculation_id}" in runtime_topology
    assert "/performance/benchmark/results/{calculation_id}" in runtime_topology
    assert (
        "`result_path` can now point directly to async result routes for `TWR`, `BENCHMARK`, `ReturnsSeries`, `Contribution`, and `Attribution`"
        in api_reference
    )
    assert "POST /performance/workspace-summary" in api_reference
    assert "GET /performance/workspace-summary/results/{calculation_id}" in api_reference
    assert "app.models.workspace_summary_requests.WorkspaceSummaryRequest" in api_reference
    assert "annualized return is always present" in api_reference
    assert "summary blocks emit `period_return`, `cumulative_return`, and `annualized_return`" in api_reference
    assert "benchmark blocks do not fabricate market-value economics" in api_reference
    assert "retrieves only the longest required portfolio window" in api_reference
    assert "docs/guides/workspace_summary.md" in readme
    assert "`workspace_summary` is now advertised as a first-class analytics surface" in api_reference
    assert "async-capable surfaces now also advertise their canonical execution polling" in api_reference
    assert "workspace_summary` now also advertises machine-readable request options" in api_reference
    assert "Canonical capabilities response excerpt" in api_reference


def test_attribution_guide_uses_current_request_shape():
    guide = _read("docs/guides/attribution.md")
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")

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
    assert "benchmark_context" in guide
    assert "portfolio_weight_avg" in guide
    assert "benchmark_weight_avg" in guide
    assert "portfolio_return" in guide
    assert "benchmark_return" in guide
    assert "benchmark_context" in readme
    assert "benchmark_context" in api_reference
    assert "each attribution group row now includes average portfolio weight" in api_reference


def test_returns_series_docs_reflect_benchmark_return_source_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    master_index = _read("docs/methodologies/metrics/master-index.md")
    active_methodology = _read("docs/methodologies/metrics/metric-returns-series-active.md")

    assert 'benchmark.return_source="vendor_series"' in readme
    assert "active_returns" in readme
    assert "cumulative_active_returns" in readme
    assert "benchmark_context" in readme
    assert "stateful benchmark sourcing now defaults to lotus-performance benchmark calculation" in readme
    assert "caller may omit `calculation_id`" in readme
    assert 'benchmark.return_source="vendor_series"' in api_reference
    assert "active_returns" in api_reference
    assert "cumulative_active_returns" in api_reference
    assert "benchmark_context" in api_reference
    assert (
        "stateful mode, benchmark sourcing defaults to the shared lotus-performance benchmark calculation path"
        in api_reference.lower()
    )
    assert "callers may omit `calculation_id`" in api_reference
    assert "Active Return Series" in master_index
    assert "series.active_returns" in active_methodology
    assert "series.cumulative_active_returns" in active_methodology


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
    assert '"day"' not in guide
    assert "window_start_date" in guide
    assert "consumer_system" not in guide
    assert "stateful attribution can also emit currency attribution" in guide.lower()
    assert "Older examples using request-level `period_type` or nested `daily_data` are not current." in guide
    assert "POST /performance/workspace-summary" in guide
    assert '"period_return"' in guide
    assert '"annualized_return"' in guide
    assert '"flow_adjusted_end_market_value"' in guide
    assert "docs/examples/workspace_summary_request.json" in guide
    assert "docs/examples/workspace_summary_stateful_detail_request.json" in guide
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
        "docs/examples/workspace_summary_request.json",
        "docs/examples/workspace_summary_stateful_detail_request.json",
        "docs/examples/integration_capabilities_response.json",
    ]

    for relative_path in example_paths:
        payload = json.loads(_read(relative_path))
        payload_text = json.dumps(payload)

        assert "period_type" not in payload_text
        assert "daily_data" not in payload_text
        assert '"day"' not in payload_text

        if relative_path == "docs/examples/integration_capabilities_response.json":
            continue

        expected_input_mode = (
            "stateful"
            if relative_path == "docs/examples/workspace_summary_stateful_detail_request.json"
            else "stateless"
        )
        assert payload["input_mode"] == expected_input_mode

    benchmark_request = json.loads(_read("docs/examples/benchmark_request.json"))
    assert "stateless_input" in benchmark_request
    assert benchmark_request["return_source"] == "calculated"
    assert benchmark_request["stateless_input"]["component_observations"][0]["perf_date"] == "2026-01-02"

    benchmark_price_request = json.loads(_read("docs/examples/benchmark_request_price_points.json"))
    assert "stateless_input" in benchmark_price_request
    assert "component_price_points" in benchmark_price_request["stateless_input"]
    assert benchmark_price_request["return_source"] == "calculated"
    assert benchmark_price_request["stateless_input"]["component_price_points"][0]["perf_date"] == "2026-01-01"

    benchmark_vendor_request = json.loads(_read("docs/examples/benchmark_vendor_series_request.json"))
    assert "stateless_input" in benchmark_vendor_request
    assert benchmark_vendor_request["return_source"] == "vendor_series"
    assert benchmark_vendor_request["stateless_input"]["benchmark_return_points"][0]["perf_date"] == "2026-01-02"

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

    workspace_summary = json.loads(_read("docs/examples/workspace_summary_request.json"))
    assert workspace_summary["input_mode"] == "stateless"
    assert workspace_summary["include_benchmark"] is True
    assert workspace_summary["benchmark"]["input_mode"] == "stateless"
    assert workspace_summary["periods"][0]["period"] == "1M"

    workspace_stateful = json.loads(_read("docs/examples/workspace_summary_stateful_detail_request.json"))
    assert workspace_stateful["input_mode"] == "stateful"
    assert workspace_stateful["benchmark"]["input_mode"] == "stateful"
    assert "segmentation" not in workspace_stateful
    assert "contribution" not in workspace_stateful
    assert "attribution" not in workspace_stateful

    capabilities = json.loads(_read("docs/examples/integration_capabilities_response.json"))
    assert capabilities["contract_version"] == "v1"
    assert capabilities["analytics_surfaces"][0]["key"] == "workspace_summary"
    assert capabilities["analytics_surfaces"][0]["options"][0]["key"] == "benchmark_mode"
    assert capabilities["analytics_surfaces"][0]["stateful_restrictions"] == []
    assert len(capabilities["analytics_surfaces"][0]["options"]) == 1


def test_workspace_summary_guide_documents_explicit_return_vocabulary():
    guide = _read("docs/guides/workspace_summary.md")
    rfc = _read("docs/RFCs/RFC 044 - Interaction-Efficient Performance Workspace Analytics Contract.md")

    assert (
        "`period_return` is the return earned inside the current resolved summary window or breakdown bucket" in guide
    )
    assert "portfolio_twr.<basis>.breakdowns.<frequency>[].period_return" in guide
    assert "benchmark.summary.period_return" in guide
    assert "money_weighted_return.period_return" in guide
    assert "active.net.period_return" in guide
    assert "summary blocks should emit `period_return`, `cumulative_return`, and `annualized_return`" in rfc
    assert "breakdown rows should emit `period_return`, `cumulative_return`, and `annualized_return`" in rfc
    assert "it should not fabricate pseudo market values or pseudo cash flows" in rfc


def test_workspace_summary_docs_publish_canonical_examples():
    api_reference = _read("docs/guides/api_reference.md")
    rfc = _read("docs/RFCs/RFC 044 - Interaction-Efficient Performance Workspace Analytics Contract.md")
    guide = _read("docs/guides/workspace_summary.md")
    methodology_index = _read("docs/technical/methodology_index.md")

    assert "Canonical example: stateless workspace summary" in api_reference
    assert "Canonical example: stateful workspace summary" in api_reference
    assert "Canonical response excerpt" in api_reference
    assert "docs/examples/workspace_summary_request.json" in api_reference
    assert "docs/examples/workspace_summary_stateful_detail_request.json" in api_reference
    assert "Illustrative Canonical Request Example" in rfc
    assert "Illustrative Canonical Response Excerpt" in rfc
    assert '"workspace_detail_block_count": 2' not in rfc
    assert "interaction-efficient" in guide
    assert "front-office performance workspaces" in guide
    assert "../examples/workspace_summary_request.json" in guide
    assert "../examples/workspace_summary_stateful_detail_request.json" in guide
    assert "../examples/workspace_summary_accepted_response.json" in guide
    assert "`POST /performance/workspace-summary`" in guide
    assert "`GET /performance/workspace-summary/results/{calculation_id}`" in guide
    assert "`GET /integration/capabilities` now advertises `workspace_summary`" in guide
    assert "`contract_notes`" in guide
    assert "`poll_path_template=/performance/executions/{calculation_id}`" in guide
    assert "`result_path_template=/performance/workspace-summary/results/{calculation_id}`" in guide
    assert "`benchmark_mode`" in guide
    assert "`linked_stateful`" in guide
    assert "../examples/integration_capabilities_response.json" in guide
    assert "workspace_summary.md" in methodology_index


def test_complete_service_reference_covers_endpoint_surface_and_config_inventory():
    guide = _read("docs/guides/complete_service_reference.md")
    readme = _read("README.md")

    assert "single consolidated reference for `lotus-performance`" in guide
    assert "POST /performance/twr" in guide
    assert "POST /performance/workspace-summary" in guide
    assert "GET /integration/capabilities" in guide
    assert "GET /integration/runtime-status" in guide
    assert "POST /integration/recovery-drills/run" in guide
    assert "POST /integration/runtime-retention-cleanups/run" in guide
    assert "GET /metrics" in guide
    assert "CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE" in guide
    assert "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS" in guide
    assert "LINEAGE_STORAGE_PATH" in guide
    assert "CORE_CONTROL_PLANE_BASE_URL" in guide
    assert "CORE_QUERY_BASE_URL" in guide
    assert "docs/examples/workspace_summary_request.json" in guide
    assert "docs/examples/integration_capabilities_response.json" in guide
    assert "twr_inspection_checks.md" in guide
    assert "guides/complete_service_reference.md" in readme


def test_twr_inspection_checks_guide_lists_current_check_inventory():
    guide = _read("docs/guides/twr_inspection_checks.md")

    assert "POST /performance/inspections/twr" in guide
    assert "inspection_summary.json" in guide
    assert "findings.json" in guide
    assert "source_quality_summary.json" in guide
    assert "reconciliation_summary.json" in guide
    assert "source_economics_summary.json" in guide
    assert "INSPECTION_CHECK_FAMILY_FAILED" in guide
    assert "RELATIVE_PERFORMANCE_SUMMARY_MISMATCH" in guide
    assert "RELATIVE_PERFORMANCE_BENCHMARK_BLOCK_MISSING" in guide
    assert "BENCHMARK_RELATIVE_PERFORMANCE_BLOCK_MISSING" in guide
    assert "RELATIVE_BREAKDOWN_BUCKET_ALIGNMENT_MISMATCH" in guide
    assert "WEEKEND_OBSERVATIONS_PRESENT" in guide
    assert "STALE_VALUATION_SERIES_DETECTED" in guide
    assert "NONPOSITIVE_DAILY_CAPITAL_BASE_DETECTED" in guide
    assert "MANDATE_DAILY_MOVE_OUTLIER_DETECTED" in guide
    assert "RETURN_CONCENTRATION_DETECTED" in guide
    assert "REPEATED_DAILY_MOVE_PATTERN_DETECTED" in guide
    assert "MONTHLY_RETURN_DAY_DOMINANCE_DETECTED" in guide
    assert "EXTREME_DAILY_MOVE_DETECTED" in guide
    assert "MIXED_POSITION_EPOCH_SNAPSHOT" in guide
    assert "DUPLICATE_POSITION_SNAPSHOT_ROW_PRESENT" in guide
    assert "INVALID_POSITION_EPOCH_PRESENT" in guide
    assert "INVALID_POSITION_END_VALUE_PRESENT" in guide
    assert "PORTFOLIO_POSITION_RECONCILIATION_GAP" in guide
    assert "FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED" in guide
    assert "FEE_SOURCE_TOTAL_MISMATCH" in guide
    assert "POSITIVE_FEE_SOURCE_SIGNAL" in guide
    assert "FEE_CASHFLOW_TIMING_BUCKET_UNSUPPORTED" in guide
    assert "FEE_CASHFLOW_MIXED_TIMING_BUCKETS" in guide
    assert "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH" in guide
    assert "EXTERNAL_CASHFLOW_TIMING_BUCKET_CONTRADICTION" in guide
    assert "EXTERNAL_CASHFLOW_MIXED_TIMING_BUCKETS" in guide
    assert "CONFLICTING_EXPLICIT_SOURCE_TOTAL_PRESENT" in guide
    assert "INVALID_EXPLICIT_SOURCE_AMOUNT_PRESENT" in guide
    assert "INVALID_CASHFLOW_COLLECTION_PRESENT" in guide
    assert "INVALID_CASHFLOW_AMOUNT_PRESENT" in guide
    assert "INVALID_CASHFLOW_TIMING_PRESENT" in guide
    assert "MISSING_CASHFLOW_TYPE_PRESENT" in guide
    assert "NONCANONICAL_CASHFLOW_TYPE_PRESENT" in guide
    assert "GOVERNED_ALIAS_CASHFLOW_TYPE_PRESENT" in guide
    assert "UNSUPPORTED_CASHFLOW_TYPE_PRESENT" in guide
    assert 'cash_flow_type="expense"` is not a governed analytics-input label' in guide
    assert "stateful valuation normalization" in guide


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
