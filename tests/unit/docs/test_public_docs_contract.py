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


def test_readme_enterprise_readiness_evidence_is_grounded():
    readme = _read("README.md")
    readme_flat = " ".join(readme.split())

    assert "Enterprise Readiness Evidence" in readme
    assert "implementation-backed analytics service" in readme_flat
    assert "`lotus-core` owns source data" in readme_flat
    assert "`lotus-performance` owns performance methodology" in readme_flat
    assert (
        "runtime status, work-item, recovery, recovery-drill, retention, health, readiness, and metrics" in readme_flat
    )
    assert "domain-data-product declarations" in readme
    assert "OpenAPI quality gates" in readme_flat
    assert "no-alias governance" in readme
    assert "This is not a blanket production certification for every client environment." in readme
    assert "target deployment, entitlement model, SLOs" in readme_flat


def test_user_guide_documents_async_execution_surfaces():
    guide = _read("docs/Portfolio Performance Analytics - A User Guide.md")

    assert "/performance/executions/{calculation_id}" in guide
    assert "/performance/twr/results/{calculation_id}" in guide
    assert "/performance/benchmark/results/{calculation_id}" in guide
    assert "/integration/returns/series/results/{calculation_id}" in guide
    assert "/integration/runtime-status" in guide
    assert "/performance/lineage/{calculation_id}/artifacts/{artifact_name}" in guide


def test_lineage_docs_reflect_certified_artifact_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    reproducibility = _read("docs/guides/reproducibility.md")
    certification = _read("docs/technical/lineage-endpoint-certification.md")

    assert "technical/lineage-endpoint-certification.md" in readme
    assert "app.models.lineage_responses.LineageResponse" in api_reference
    assert "Swagger status: documented in `/docs`" in api_reference
    assert "docs/technical/lineage-endpoint-certification.md" in api_reference
    assert '"calculation_type": "WORKSPACE_SUMMARY"' in complete_reference
    assert '"url": "http://performance.dev.lotus/performance/lineage/' in complete_reference
    assert '"request.json": {' in reproducibility
    assert '"daily_results.csv": {' in reproducibility
    assert "Downstream Consumers" in certification
    assert "lotus-gateway#110" in certification
    assert "Test Pyramid Assessment" in certification


def test_runtime_status_docs_reflect_certified_operator_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/runtime-status-endpoint-certification.md")

    assert "technical/runtime-status-endpoint-certification.md" in readme
    assert "app.models.runtime_status.RuntimeStatusResponse" in api_reference
    assert "certification evidence: `docs/technical/runtime-status-endpoint-certification.md`" in api_reference
    assert '"runtime_status": "ready"' in complete_reference
    assert '"compute_queue": {' in complete_reference
    assert '"lineage_queue": {' in complete_reference
    assert '"runtime_retention": {' in complete_reference
    assert "Downstream Consumers" in certification
    assert "Test Pyramid Assessment" in certification
    assert "No duplicate lotus-performance runtime-status endpoint" in certification
    assert "app.services.runtime_status_lifecycle" in certification
    assert "app.services.runtime_status_queue" in certification
    assert "Compute and lineage queue component assembly" in certification
    assert "Recovery-drill and runtime-retention component assembly" in certification


def test_runtime_work_items_docs_reflect_certified_operator_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/runtime-work-items-endpoint-certification.md")

    assert "technical/runtime-work-items-endpoint-certification.md" in readme
    assert "app.models.runtime_work_items.RuntimeWorkItemsResponse" in api_reference
    assert "certification evidence: `docs/technical/runtime-work-items-endpoint-certification.md`" in api_reference
    assert '"queue_filter": "both"' in complete_reference
    assert '"status_filter": "reclaimable"' in complete_reference
    assert '"compute_queue": {' in complete_reference
    assert '"lineage_queue": {' in complete_reference
    assert '"compute_items": [' in complete_reference
    assert '"lineage_items": [' in complete_reference
    assert "Downstream Consumers" in certification
    assert "Test Pyramid Assessment" in certification
    assert "No duplicate lotus-performance work-item endpoint" in certification


def test_runtime_recoveries_docs_reflect_certified_operator_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/runtime-recoveries-endpoint-certification.md")

    assert "technical/runtime-recoveries-endpoint-certification.md" in readme
    assert "app.models.runtime_recoveries.RuntimeRecoveriesResponse" in api_reference
    assert "certification evidence: `docs/technical/runtime-recoveries-endpoint-certification.md`" in api_reference
    assert '"queue_filter": "both"' in complete_reference
    assert '"recovered_after": "2026-03-29T02:00:00Z"' in complete_reference
    assert '"compute_queue": {' in complete_reference
    assert '"lineage_queue": {' in complete_reference
    assert '"compute_recoveries": [' in complete_reference
    assert '"lineage_recoveries": [' in complete_reference
    assert "Downstream Consumers" in certification
    assert "Test Pyramid Assessment" in certification
    assert "No duplicate lotus-performance recovery-event endpoint" in certification


def test_recovery_drills_docs_reflect_certified_operator_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/recovery-drills-endpoint-certification.md")

    assert "technical/recovery-drills-endpoint-certification.md" in readme
    assert "app.models.recovery_drill_history.RecoveryDrillHistoryResponse" in api_reference
    assert "app.models.recovery_drill_history.RecoveryDrillRunRequest" in api_reference
    assert "app.models.recovery_drill_history.RecoveryDrillRunResponse" in api_reference
    assert "certification evidence: `docs/technical/recovery-drills-endpoint-certification.md`" in api_reference
    assert '"latest_file_name": "recovery-drill-20260329T013000Z.json"' in complete_reference
    assert '"entries": [' in complete_reference
    assert '"compute_job_processed_count": 1' in complete_reference
    assert '"materialized_artifact_exists": true' in complete_reference
    assert "Downstream Consumers" in certification
    assert "Test Pyramid Assessment" in certification
    assert "No duplicate lotus-performance recovery-drill endpoint" in certification
    assert "app.services.operator_action_history_manifest" in certification
    assert "app.services.operator_action_history_filters" in certification


def test_runtime_retention_docs_reflect_certified_operator_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/runtime-retention-endpoint-certification.md")

    assert "technical/runtime-retention-endpoint-certification.md" in readme
    assert "app.models.runtime_retention_history.RuntimeRetentionHistoryResponse" in api_reference
    assert "app.models.runtime_retention_history.RuntimeRetentionCleanupRunRequest" in api_reference
    assert "app.models.runtime_retention_history.RuntimeRetentionCleanupRunResponse" in api_reference
    assert "certification evidence: `docs/technical/runtime-retention-endpoint-certification.md`" in api_reference
    assert '"latest_file_name": "runtime-retention-20260329T014500Z.json"' in complete_reference
    assert '"prunable_execution_count": 3' in complete_reference
    assert '"prunable_lineage_artifact_count": 1' in complete_reference
    assert "Downstream Consumers" in certification
    assert "Test Pyramid Assessment" in certification
    assert "No duplicate lotus-performance runtime-retention endpoint" in certification
    assert "app.services.operator_action_history_manifest" in certification
    assert "app.services.operator_action_history_filters" in certification


def test_platform_surfaces_docs_reflect_certified_operational_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/platform-surfaces-endpoint-certification.md")

    assert "technical/platform-surfaces-endpoint-certification.md" in readme
    assert "app.models.platform_surfaces.RootResponse" in api_reference
    assert "app.models.platform_surfaces.HealthStatusResponse" in api_reference
    assert "text/plain" in api_reference
    assert "Access /docs for API documentation." in complete_reference
    assert "lotus_performance_compute_queue_degradation_breach" in complete_reference
    assert "GET /metrics" in certification
    assert "GET /health/ready" in certification
    assert "app.services.queue_metric_builders" in certification
    assert "source-to-builder wiring" in certification
    assert "Test Pyramid Assessment" in certification
    assert "no duplicate lotus-performance health or metrics endpoint" in certification.lower()


def test_execution_polling_docs_reflect_certified_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/execution-polling-endpoint-certification.md")

    assert "technical/execution-polling-endpoint-certification.md" in readme
    assert "app.models.execution_polling.ExecutionResponse" in api_reference
    assert "upstream_snapshots[]" in api_reference
    assert "`lotus-risk` uses this endpoint" in api_reference
    assert "docs/technical/execution-polling-endpoint-certification.md" in api_reference
    assert '"stage_name": "execution"' in complete_reference
    assert '"job_status": "complete"' in complete_reference
    assert '"result_status": "complete"' in complete_reference
    assert "Downstream Consumers" in certification
    assert "`lotus-risk`" in certification
    assert "Test Pyramid Assessment" in certification
    assert "No duplicate lotus-performance polling endpoint" in certification


def test_twr_guide_uses_current_request_shape():
    guide = _read("docs/guides/twr.md")
    certification = _read("docs/technical/twr-endpoint-certification.md")

    assert "analyses" in guide
    assert "valuation_points" in guide
    assert "include_benchmark=true" in guide
    assert 'benchmark.input_mode="stateless" | "stateful"' in guide
    assert 'benchmark.return_source="calculated" | "vendor_series"' in guide
    assert "benchmark.stateless_input.component_price_points" in guide
    assert "relative_performance" in guide
    assert "benchmark_context" in guide
    assert "summary.cumulative_return" in guide
    assert "calculation_evidence" in guide
    assert "absolute_begin_mv_plus_bod_cf" in guide
    assert "Beginning-of-day flows adjust invested capital" in guide
    assert "`linkability_status` explains whether the day can participate in geometric linking" in guide
    assert "`episode_status` explains the row's TWR episode" in guide
    assert "calculation_supportability.source_quality_evidence" in guide
    assert "UNSUPPORTED_CASHFLOW_LABELS" in guide
    assert "benchmark_context.supportability_evidence" in guide
    assert "BENCHMARK_CALENDAR_GAP" in guide
    assert "vendor_series_base_only" in guide
    assert '"portfolio": {' in guide
    assert '"portfolio_return"' not in guide.split("## Example stateful request")[0]
    assert "If `calculation_id` is omitted" in guide
    assert "/performance/twr/results/{calculation_id}" in guide
    assert "Older examples using `period_type`" in guide
    assert "`daily_data` are not current" in guide
    assert "stateful_input.consumer_system" not in guide
    assert "Downstream Consumers" in certification
    assert "`lotus-gateway`" in certification
    assert "`lotus-risk`" in certification
    assert "Test Pyramid Assessment" in certification
    assert "long-window results are not front-office safe" in certification
    assert "Long and short exposure handling" in guide
    assert "Long and short sleeve handling" not in guide
    assert "Composite, group, and sleeve TWR" in guide
    assert "calculation is not part of the current `POST /performance/twr` contract" in guide


def test_twr_documentation_map_and_wiki_navigation_are_present():
    map_doc = _read("docs/technical/twr-documentation-map.md")
    methodology_index = _read("docs/technical/methodology_index.md")
    wiki_page = _read("wiki/Time-Weighted-Return.md")
    wiki_sidebar = _read("wiki/_Sidebar.md")
    wiki_home = _read("wiki/Home.md")
    wiki_api_surface = _read("wiki/API-Surface.md")
    wiki_integrations = _read("wiki/Integrations.md")
    supported_features = _read("wiki/Supported-Features.md")
    mesh_data_products = _read("wiki/Mesh-Data-Products.md")

    assert "Source Of Truth Layers" in map_doc
    assert "wiki/Time-Weighted-Return.md" in map_doc
    assert "wiki/Supported-Features.md" in map_doc
    assert "Composite, group, and sleeve TWR are not promoted" in map_doc
    assert "twr-documentation-map.md" in methodology_index
    assert "Stateful TWR source flow" in wiki_integrations
    assert "benchmark_context.supportability_evidence" in wiki_integrations
    assert "lotus-core source authority" in wiki_page
    assert "daily calculation evidence" in wiki_page
    assert "Benchmark Evidence" in wiki_page
    assert "composite, group, and sleeve TWR are not promoted" in wiki_page
    assert "[Time-Weighted Return](Time-Weighted-Return)" in wiki_sidebar
    assert "[Supported Features](Supported-Features)" in wiki_sidebar
    assert "[Time-Weighted Return](Time-Weighted-Return)" in wiki_home
    assert "[Supported Features](Supported-Features)" in wiki_home
    assert "docs/technical/twr-documentation-map.md" in wiki_api_surface
    assert "TimeWeightedReturnAnalytics:v1" in supported_features
    assert "composite TWR is supported only through `POST /performance/composites/twr`" in supported_features
    assert "lotus-performance:TimeWeightedReturnAnalytics:v1" in mesh_data_products


def test_architecture_wiki_explains_runtime_and_non_functional_posture():
    wiki_architecture = _read("wiki/Architecture.md")

    assert "Application wiring" in wiki_architecture
    assert "Request Lifecycle" in wiki_architecture
    assert "Non-Functional Architecture" in wiki_architecture
    assert "performance-compute-executor" in wiki_architecture
    assert "performance-lineage-worker" in wiki_architecture
    assert "OpenAPI, API vocabulary, no-alias guard" in wiki_architecture
    assert "`lotus-performance` owns performance methodology" in wiki_architecture
    assert "`lotus-core` owns source" in wiki_architecture
    assert "runtime-control surfaces are operator contracts" in wiki_architecture


def test_attribution_documentation_map_and_wiki_navigation_are_present():
    map_doc = _read("docs/technical/attribution-documentation-map.md")
    methodology_index = _read("docs/technical/methodology_index.md")
    certification = _read("docs/technical/attribution-endpoint-certification.md")
    wiki_page = _read("wiki/Attribution-Analytics.md")
    wiki_sidebar = _read("wiki/_Sidebar.md")
    wiki_home = _read("wiki/Home.md")
    wiki_api_surface = _read("wiki/API-Surface.md")
    supported_features = _read("wiki/Supported-Features.md")

    assert "Source Of Truth Layers" in map_doc
    assert "wiki/Attribution-Analytics.md" in map_doc
    assert "fixed-income factor attribution" in map_doc
    assert "attribution-documentation-map.md" in methodology_index
    assert "lotus-gateway#105` is closed" in certification
    assert "lotus-gateway#106` is closed" in certification
    assert "Attribution analytics explains the active return" in wiki_page
    assert "lotus-performance attribution input normalization" in wiki_page
    assert "Current Boundaries" in wiki_page
    assert "material residual classification" in wiki_page
    assert "currency_attribution_totals" in wiki_page
    assert "portfolio-level Karnosky-Singer total" in wiki_page
    assert "weight-averaged local/FX" in wiki_page
    assert "portfolio-level FX attribution" in certification
    assert "should consume these totals rather than reconstructing" in certification
    assert "does not sum granular sector" in certification
    assert "[Attribution Analytics](Attribution-Analytics)" in wiki_sidebar
    assert "[Attribution Analytics](Attribution-Analytics)" in wiki_home
    assert "docs/technical/attribution-documentation-map.md" in wiki_api_surface
    assert (
        "fixed-income factor, derivative, sleeve, and composite attribution are not current supported claims"
        in supported_features
    )


def test_rfc_049_advanced_composite_analytics_are_gated():
    decision = _read("docs/RFCs/RFC-049-advanced-analytics-decision-slice8.md")
    supported_features = _read("wiki/Supported-Features.md")
    rfc_index = _read("docs/RFCs/RFC-INDEX.md")

    assert "RFC 049 will not implement the following advanced scopes in this wave" in decision
    for unsupported_scope in (
        "composite contribution",
        "composite attribution",
        "composite MWR",
        "carve-outs",
        "sleeves",
        "model portfolios",
        "wrap programs",
        "pooled fund composites",
        "private-market composites",
        "portability records",
        "tax-aware composites",
        "leveraged composites",
        "long/short special composite structures",
        "multi-currency composite aggregation beyond the current single reporting-currency guard",
    ):
        assert unsupported_scope in decision
        assert unsupported_scope in supported_features

    assert "RFC-049 promotes persisted-fact composite performance" in supported_features
    assert "Gateway route realization, Workbench typed BFF consumption" in supported_features
    assert "`POST /performance/composites/twr`" in supported_features
    assert "`POST /performance/composites/inspect`" in supported_features
    assert "docs/RFCs/RFC-049-advanced-analytics-decision-slice8.md" in rfc_index


def test_rfc_049_composite_documentation_productization_is_grounded():
    guide = _read("docs/guides/composite_performance.md")
    methodology_index = _read("docs/technical/methodology_index.md")
    certification = _read("docs/technical/composite-twr-endpoint-certification.md")
    map_doc = _read("docs/technical/composite-performance-documentation-map.md")
    wiki_page = _read("wiki/Composite-Performance.md")
    wiki_sidebar = _read("wiki/_Sidebar.md")
    wiki_home = _read("wiki/Home.md")
    wiki_api_surface = _read("wiki/API-Surface.md")
    wiki_integrations = _read("wiki/Integrations.md")
    mesh_data_products = _read("wiki/Mesh-Data-Products.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    readme = _read("README.md")
    rfc_index = _read("docs/RFCs/RFC-INDEX.md")

    for content in (guide, certification, map_doc, wiki_page):
        assert "persisted member-return facts" in content
        assert "CompositePerformanceAnalytics" in content
        assert "composite contribution" in content
        assert "multi-currency composite aggregation" in content

    assert "metric-composite-twr.md" in methodology_index
    assert "composite-performance-documentation-map.md" in methodology_index
    assert "member_inputs.csv" in guide
    assert "period_weights.csv" in certification
    assert "Composite performance source flow" in wiki_integrations
    assert "Composite Performance](Composite-Performance)" in wiki_sidebar
    assert "Composite Performance](Composite-Performance)" in wiki_home
    assert "POST /performance/composites/twr" in wiki_api_surface
    assert "POST /performance/composites/inspect" in api_reference
    assert "calculate composite TWR from persisted member-return facts" in complete_reference
    assert "docs/guides/composite_performance.md" in readme
    assert "wiki/Composite-Performance.md" in readme
    assert "contracts/trust-telemetry/composite-performance-analytics.telemetry.v1.json" in mesh_data_products
    assert "Slice 11 productized methodology/docs/wiki" in rfc_index
    assert "Slice 12 live proof" in certification
    assert "Slice 13 Swagger hardening" in certification
    assert "COMPOSITE_NOT_FOUND" in certification
    assert "COMPOSITE_DEFINITION_NOT_FOUND" not in certification
    assert "Promotes only the persisted-fact composite TWR" in map_doc
    assert "Supported after RFC-049 implementation proof" in wiki_page
    assert "Business And Demo Readiness" in wiki_page
    assert "Operational Support Model" in wiki_page


def test_benchmark_guide_uses_current_request_shape():
    guide = _read("docs/guides/benchmark.md")
    api_reference = _read("docs/guides/api_reference.md")
    readme = _read("README.md")
    certification = _read("docs/technical/benchmark-endpoint-certification.md")

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
    assert "daily_returns[].benchmark_return" in api_reference
    assert "docs/technical/benchmark-endpoint-certification.md" in api_reference
    assert "POST /integration/returns/series" in guide
    assert "POST /performance/benchmark" in readme
    assert "technical/benchmark-endpoint-certification.md" in readme
    assert "Required Figure Tie-Outs" in certification
    assert "component_contributions[]" in certification
    assert "`lotus-risk`" in certification
    assert "No duplicate downstream use of `/performance/benchmark`" in certification
    assert "TWRAcceptedResponse" in api_reference


def test_mwr_guide_matches_current_method_reality():
    guide = _read("docs/guides/mwr.md")
    certification = _read("docs/technical/mwr-endpoint-certification.md")
    api_reference = _read("docs/guides/api_reference.md")
    readme = _read("README.md")

    assert 'input_mode: "stateless" | "stateful"' in guide
    assert "stateful_input.window_start_date" in guide
    assert 'mwr_method="MODIFIED_DIETZ"' in guide
    assert "uses weighted cash-flow capital" in guide
    assert "carry-forward adjustments" in guide
    assert "emit_cashflows_used=true" in guide
    assert "cashflows_used" in guide
    assert "currency_evidence" in guide
    assert "not_required_single_currency_inputs" in guide
    assert "upstream_preconverted_missing_per_input_fx_metadata" in guide
    assert "holding_period_return" in guide
    assert "fallback_reason" in guide
    assert "root_count_detected" in guide
    assert "lotus_performance_mwr_solver_outcome_total" in guide
    assert "mwr-lotus-production-controls.md" in guide
    assert "mwr-fx-contract-design.md" in guide
    assert "cashflows_used` proves the signed schedule" in guide
    assert "stateful single-currency MWR emits" in api_reference
    assert "stateful cross-currency MWR keeps" in api_reference
    assert "mwr-production-support-playbook.md" in guide
    assert "mwr-industry-review-findings.md" in guide
    assert "investor capital-timing lens" in certification
    assert "No-root and multiple-root cases are not silently interpreted" in certification
    assert "lotus_performance_mwr_solver_outcome_total" in certification
    assert 'status="FALLBACK_USED"' in certification
    assert "CORE_CONTROL_PLANE_BASE_URL" in certification
    assert "lotus-gateway" in certification
    assert "`lotus-risk` does not call `/performance/mwr`" in certification
    assert "cross-observation capital carry-forward adjustments" in api_reference
    assert "technical/mwr-endpoint-certification.md" in readme
    assert "[cite_start]" not in guide


def test_mwrr_industry_material_is_converted_to_lotus_product_docs():
    controls = _read("docs/guides/mwr-lotus-production-controls.md")
    playbook = _read("docs/operations/mwr-production-support-playbook.md")
    alert_templates = _read("docs/operations/mwr-alert-rule-templates.md")
    findings = _read("docs/technical/mwr-industry-review-findings.md")
    fx_design = _read("docs/technical/mwr-fx-contract-design.md")
    guide = _read("docs/guides/mwr.md")
    api_wiki = _read("wiki/API-Surface.md")
    ops_wiki = _read("wiki/Operations-Runbook.md")
    integrations_wiki = _read("wiki/Integrations.md")
    mesh_wiki = _read("wiki/Mesh-Data-Products.md")

    assert not (REPO_ROOT / "docs/reference/mwrr-industry-pack").exists()

    for text in (controls, playbook, findings):
        assert "lotus-performance" in text
        assert "MULTIPLE_IRR_ROOTS_DETECTED" in text
        assert "holding_period_return" in text

    assert "lotus-gateway" in controls
    assert "data mesh" in controls.lower()
    assert "calculation_supportability" in playbook
    assert "lotus_performance_mwr_solver_outcome_total" in playbook
    assert "mwr-alert-rule-templates.md" in playbook
    assert "NO_ECONOMIC_CONTENT" in playbook
    assert "Adopted Into The Current Contract" in findings
    assert "Areas Where Lotus Is Stronger" in findings
    assert "Backlog Candidates" in findings
    assert "mwr-alert-rule-templates.md" in findings
    assert "mwr-fx-contract-design.md" in findings
    assert "Required Input Provenance" in fx_design
    assert "Current stateful execution does preserve the reporting-currency context" in fx_design
    assert "source_amount" in fx_design
    assert "conversion_fingerprint" in fx_design
    assert "not_required_single_currency_inputs" in fx_design
    assert "no_conversion_required" in fx_design
    assert "upstream_preconverted_missing_per_input_fx_metadata" in fx_design
    assert "must not reconstruct FX conversion" in fx_design
    assert "fail closed" in fx_design
    assert "LotusPerformanceMWRFallbackRateElevated" in alert_templates
    assert "LotusPerformanceMWRNoRootRateElevated" in alert_templates
    assert "LotusPerformanceMWRMultipleRootRateElevated" in alert_templates
    assert "LotusPerformanceMWRSourceDataRejectionRateElevated" in alert_templates
    assert "MULTIPLE_IRR_ROOTS_DETECTED" in alert_templates
    assert "NO_ROOT_FOUND" in alert_templates
    assert 'supportability_state=~"empty|stale"' in alert_templates
    assert "mwr-lotus-production-controls.md" in guide
    assert "mwr-alert-rule-templates.md" in guide
    assert "mwr-lotus-production-controls.md" in api_wiki
    assert "mwr-fx-contract-design.md" in api_wiki
    assert "currency_evidence" in api_wiki
    assert "currency_evidence" in mesh_wiki
    assert "not_required_single_currency_inputs" in api_wiki
    assert "not_required_single_currency_inputs" in mesh_wiki
    assert "mwr-production-support-playbook.md" in ops_wiki
    assert "mwr-alert-rule-templates.md" in ops_wiki
    assert "must not infer FX rates" in integrations_wiki
    assert "MoneyWeightedReturnAnalytics" in mesh_wiki


def test_mwr_rfc_closure_truth_is_implementation_backed():
    rfc_016 = _read("docs/RFCs/RFC 016 - MWR Enhancements (XIRR + Modified Dietz).md")
    rfc_index = _read("docs/RFCs/RFC-INDEX.md")
    status = _read("docs/RFCs/RFC_IMPLEMENTATION_STATUS.md")
    wiki_rfc_index = _read("wiki/RFC-Index.md")

    assert "**Status:** Implemented" in rfc_016
    assert "Requirement-To-Implementation Traceability" in rfc_016
    assert "`engine/mwr.py`" in rfc_016
    assert "tests/integration/test_response_attribute_certification.py" in rfc_016
    assert "does not depend on SciPy" in rfc_016 or "does\nnot depend on SciPy" in rfc_016
    assert "`money_weighted_return`" in rfc_016
    assert "`holding_period_return`" in rfc_016
    assert "`calculation_supportability`" in rfc_016
    assert "single reporting-currency MWR contract" in rfc_016
    assert "FX-aware per-flow MWR conversion is not part of RFC-016 closure" in rfc_016
    assert "| RFC-016 | MWR Enhancements (XIRR + Modified Dietz) | Implemented | Implemented |" in rfc_index
    assert "RFC 016    | MWR Enhancements (XIRR + Modified Dietz)" in status
    assert "RFC-016" in wiki_rfc_index


def test_rfc_020_status_does_not_overstate_fx_aware_mwr():
    status = _read("docs/RFCs/RFC_IMPLEMENTATION_STATUS.md")
    rfc_index = _read("docs/RFCs/RFC-INDEX.md")
    backlog = _read("docs/RFCs/RFC-DELTA-BACKLOG.md")
    fx_design = _read("docs/technical/mwr-fx-contract-design.md")
    wiki_rfc_index = _read("wiki/RFC-Index.md")

    assert (
        "RFC 020    | Multi-Currency & FX-Aware Performance"
        not in status.split("## Partially Implemented Or Gated RFCs")[0]
    )
    assert "RFC 020 | Multi-Currency & FX-Aware Performance | ⚠️ Partially Implemented" in status
    assert "MWR remains a single reporting-currency schedule" in status
    assert "per-flow conversion evidence" in status or "per-flow\n      conversion evidence" in status
    assert (
        "| RFC-020 | Multi-Currency & FX-Aware Performance | Final (For Approval) | Partially Implemented |"
        in rfc_index
    )
    assert "MWR remains pre-converted input model" in backlog
    assert "FX-aware MWR is not done until all of these are true" in fx_design
    assert "partially implemented" in wiki_rfc_index


def test_twr_mwr_response_attribute_certification_documents_field_level_checks():
    certification = _read("docs/technical/twr-mwr-response-attribute-certification.md")
    readme = _read("README.md")

    assert (
        "This certification checks the full emitted response contract, not only headline return values."
        in certification
    )
    assert "`portfolio.summary.period_return.base`" in certification
    assert "`portfolio.breakdowns.<frequency>[]`" in certification
    assert "`meta.input_fingerprint` / `meta.calculation_hash`" in certification
    assert "`diagnostics.effective_period_start`" in certification
    assert "`audit.counts.input_rows`" in certification
    assert "`money_weighted_return`" in certification
    assert "`cashflows_used[].amount` / `date`" in certification
    assert "`audit.counts.cashflows`" in certification
    assert "40 / 1040 = 3.846153846%" in certification
    assert "Workspace may shape the UI response, but it must not" in certification
    assert "Workspace economics must not include internal MWR carry-forward capital adjustments" in certification
    assert "`flow_adjusted_end_market_value = end_market_value - explicit net_cash_flow`" in certification
    assert "tests/integration/test_response_attribute_certification.py" in certification
    assert "technical/twr-mwr-response-attribute-certification.md" in readme


def test_methodology_index_points_to_current_guides():
    index = _read("docs/technical/methodology_index.md")
    master_index = _read("docs/methodologies/metrics/master-index.md")
    xirr_methodology = _read("docs/methodologies/metrics/metric-mwr-xirr.md")
    dietz_methodology = _read("docs/methodologies/metrics/metric-mwr-dietz.md")
    integrations_wiki = _read("wiki/Integrations.md")

    assert "../guides/twr.md" in index
    assert "../guides/api_reference.md" in index
    assert "period_type" in index
    assert "`POST /performance/mwr` support stateful" in index
    assert "must not reconstruct MWR inputs from TWR, benchmark, or workspace summary payloads" in index
    assert "MWR (XIRR) | POST /performance/mwr | Stateless + Stateful" in master_index
    assert (
        "MWR (Modified Dietz fallback / Dietz explicit) | POST /performance/mwr | Stateless + Stateful" in master_index
    )
    assert "stateful_input.window_start_date" in xirr_methodology
    assert "stateful_input.window_start_date" in dietz_methodology
    assert "Stateful MWR source flow" in integrations_wiki
    assert "Gateway and Workbench should consume the emitted MWR response" in integrations_wiki
    assert "FX-aware MWR remains gated" in index
    assert "stateful lotus-core portfolio" in index
    assert "Stateful contribution source flow" in integrations_wiki
    assert "they must not reconstruct position contribution" in integrations_wiki
    assert "Stateful attribution source flow" in integrations_wiki
    assert "reconstruct allocation, selection, interaction" in integrations_wiki
    assert "source-normalized attribution" in index
    assert "inputs; callers should consume emitted allocation" in index


def test_standalone_guide_uses_current_engine_api():
    guide = _read("docs/guides/standalone_engine_usage.md")

    assert "results_df, diagnostics = run_calculations" in guide
    assert "google.com/search" not in guide


def test_engine_config_docs_describe_current_calendar_contract():
    engine_config = _read("docs/technical/engine_config.md")
    engine_config_flat = " ".join(engine_config.split())

    assert "placeholder" not in engine_config.lower()
    assert "Optional exchange-calendar identifier preserved in the request" in engine_config
    assert "venue-specific holiday calendars are not applied" in engine_config_flat
    assert not engine_config.rstrip().endswith("````")


def test_contribution_guide_uses_current_request_shape():
    guide = _read("docs/guides/contribution.md")
    guide_flat = " ".join(guide.split())
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
    assert "`lookthrough` is accepted as a compatibility request block only" in guide
    assert "does not decompose fund or structured-product holdings" in guide_flat
    assert "app.models.contribution_analytics_requests.ContributionAnalyticsRequest" in api_reference
    assert (
        "stateful mode sources portfolio and position timeseries from lotus-core query-control-plane" in api_reference
    )
    assert (
        "position-level `average_weight` and grouped `weight_avg` are both emitted in percentage units" in api_reference
    )
    assert "fund or structured-product decomposition is not performed inside lotus-performance" in api_reference
    assert 'input_mode: "stateless" | "stateful"' in readme
    assert "lotus-performance stamps source consumer identity server-side" in readme


def test_api_reference_documents_endpoint_level_capabilities_contract():
    api_reference = _read("docs/guides/api_reference.md")
    readme = _read("README.md")
    runtime_topology = _read("docs/technical/runtime_topology.md")
    certification = _read("docs/technical/integration-capabilities-endpoint-certification.md")
    example = json.loads(_read("docs/examples/integration_capabilities_response.json"))

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
    assert "consumer_system" in api_reference
    assert "tenant_id" in api_reference
    assert "lotus-gateway#109" in certification
    assert "Downstream Consumers" in certification
    assert "Test Pyramid Assessment" in certification
    assert "implemented TWR, MWR, contribution, and attribution calculation supportability posture" in certification
    assert {surface["key"] for surface in example["analytics_surfaces"]} == {
        "twr",
        "twr_inspection",
        "mwr",
        "benchmark",
        "workspace_summary",
        "contribution",
        "attribution",
        "composite_twr",
        "mandate_performance_health_context",
        "returns_series",
        "benchmark_exposure_context",
    }


def test_benchmark_exposure_context_docs_reflect_certified_contract():
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    certification = _read("docs/technical/benchmark-exposure-context-endpoint-certification.md")

    assert "POST /integration/benchmarks/exposure-context" in readme
    assert "Benchmark Exposure Context Endpoint Certification" in readme
    assert "frequency=DAILY" in readme
    assert "`ASSET_CLASS`, and `ISSUER`" in readme
    assert "`frequency=DAILY` is the only supported v1 frequency" in api_reference
    assert "row weights are returned as decimal fractions" in api_reference
    assert "`POSITION` rows carry `component_id`" in api_reference
    assert "docs/technical/benchmark-exposure-context-endpoint-certification.md" in api_reference
    assert "docs/technical/benchmark-exposure-context-endpoint-certification.md" in _read(
        "docs/guides/complete_service_reference.md"
    )
    assert "lotus-risk" in certification
    assert "No duplicate downstream endpoint use was found" in certification


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
    capability_surfaces = {surface["key"]: surface for surface in capabilities["analytics_surfaces"]}
    assert capability_surfaces["workspace_summary"]["options"][0]["key"] == "benchmark_mode"
    assert capability_surfaces["workspace_summary"]["stateful_restrictions"] == []
    assert len(capability_surfaces["workspace_summary"]["options"]) == 1
    assert capability_surfaces["mwr"]["supports_async"] is False
    assert capability_surfaces["returns_series"]["result_path_template"] == (
        "/integration/returns/series/results/{calculation_id}"
    )


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


def test_front_office_supportability_docs_cover_all_completed_calculation_surfaces():
    twr_certification = _read("docs/technical/twr-endpoint-certification.md")
    mwr_certification = _read("docs/technical/mwr-endpoint-certification.md")
    contribution_certification = _read("docs/technical/contribution-endpoint-certification.md")
    attribution_certification = _read("docs/technical/attribution-endpoint-certification.md")
    runbook = _read("wiki/Operations-Runbook.md")
    repo_context = _read("REPOSITORY-ENGINEERING-CONTEXT.md")

    for operation in ("twr", "mwr", "contribution", "attribution"):
        assert f'operation="{operation}"' in twr_certification or f"`{operation}`" in runbook

    assert 'operation="mwr"' in mwr_certification
    assert 'operation="contribution"' in contribution_certification
    assert 'operation="attribution"' in attribution_certification
    assert "`calculation_supportability`" in repo_context
    assert 'supportability_state="stale"' in runbook
    assert (
        "Bounded TWR, MWR, contribution, and attribution calculation supportability response metadata and Prometheus posture metrics."
        in _read("docs/examples/integration_capabilities_response.json")
    )


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
    assert "docs/technical/workspace-summary-endpoint-certification.md" in api_reference
    assert "legacy top-level `valuation_points` remains deprecated compatibility input" in api_reference
    assert "/performance/contribution" in api_reference
    assert "/performance/attribution" in api_reference
    assert "Illustrative Canonical Request Example" in rfc
    assert "Illustrative Canonical Response Excerpt" in rfc
    assert '"workspace_detail_block_count": 2' not in rfc
    assert "interaction-efficient" in guide
    assert "front-office performance workspaces" in guide
    assert "../examples/workspace_summary_request.json" in guide
    assert "../examples/workspace_summary_stateful_detail_request.json" in guide
    assert "../examples/workspace_summary_accepted_response.json" in guide
    assert "../technical/workspace-summary-endpoint-certification.md" in guide
    assert "Legacy top-level `valuation_points` remains as deprecated compatibility input" in guide
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
    assert "all return values are decimal ratios, not percentages" in guide
    assert '"cumulative_active_returns"' in guide
    assert '"return_value": 0.00603' in guide
    assert '"return_value": 0.7' not in guide
    assert "CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE" in guide
    assert "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS" in guide
    assert "LINEAGE_STORAGE_PATH" in guide
    assert "CORE_CONTROL_PLANE_BASE_URL" in guide
    assert "CORE_QUERY_BASE_URL" in guide
    assert "docs/examples/workspace_summary_request.json" in guide
    assert "docs/technical/workspace-summary-endpoint-certification.md" in guide
    assert "docs/examples/integration_capabilities_response.json" in guide
    assert "twr_inspection_checks.md" in guide
    assert "guides/complete_service_reference.md" in readme
    assert "docs/technical/twr-endpoint-certification.md" in readme


def test_twr_inspection_checks_guide_lists_current_check_inventory():
    guide = _read("docs/guides/twr_inspection_checks.md")
    readme = _read("README.md")
    api_reference = _read("docs/guides/api_reference.md")
    complete_reference = _read("docs/guides/complete_service_reference.md")
    certification = _read("docs/technical/twr-inspection-endpoint-certification.md")

    assert "POST /performance/inspections/twr" in guide
    assert "POST /performance/inspections/twr" in api_reference
    assert "GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}" in api_reference
    assert "scripts/validate_canonical_twr_inspection.py" in guide
    assert "scripts/validate_canonical_twr_inspection.py" in readme
    assert "--require-support-brief" in guide
    assert "technical/twr-inspection-endpoint-certification.md" in readme
    assert "docs/technical/twr-inspection-endpoint-certification.md" in complete_reference
    assert "inspection_summary.json" in guide
    assert "findings.json" in guide
    assert "support_brief.md" in guide
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
    assert "EXTERNAL_CASHFLOW_EXPLICIT_MIXED_TIMING_BUCKETS" in guide
    assert "CONFLICTING_EXPLICIT_SOURCE_TOTAL_PRESENT" in guide
    assert "INVALID_EXPLICIT_SOURCE_AMOUNT_PRESENT" in guide
    assert "INVALID_PORTFOLIO_OBSERVATION_DATE_PRESENT" in guide
    assert "INVALID_CASHFLOW_COLLECTION_PRESENT" in guide
    assert "INVALID_CASHFLOW_ROW_PRESENT" in guide
    assert "INVALID_CASHFLOW_AMOUNT_PRESENT" in guide
    assert "INVALID_CASHFLOW_TIMING_PRESENT" in guide
    assert "MISSING_CASHFLOW_TYPE_PRESENT" in guide
    assert "NONCANONICAL_CASHFLOW_TYPE_PRESENT" in guide
    assert "GOVERNED_ALIAS_CASHFLOW_TYPE_PRESENT" in guide
    assert "UNSUPPORTED_CASHFLOW_TYPE_PRESENT" in guide
    assert 'cash_flow_type="expense"` is not a governed analytics-input label' in guide
    assert "stateful valuation normalization" in guide
    assert "Downstream Consumers" in certification
    assert "`lotus-gateway`" in certification
    assert "`lotus-risk`" in certification
    assert "Swagger Readiness" in certification
    assert "Test Pyramid Assessment" in certification


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
    mwr_templates = _read("docs/operations/mwr-alert-rule-templates.md")
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
    assert "lotus_performance_mwr_solver_outcome_total" in mwr_templates
    assert "lotus_performance_calculation_supportability_total" in mwr_templates
    assert "docs/operations/runtime-alert-rule-templates.md" in runbook
    assert "runtime-alert-rule-templates.md" in api_reference
    assert "mwr-alert-rule-templates.md" in api_reference
    assert "runtime-alert-rule-templates.md" in runtime_topology
    assert "mwr-alert-rule-templates.md" in runtime_topology


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
    assert "MWR fallback/no-root/multiple-root rate alerts" in policy
    assert "MWR source-data rejection rate alert" in policy
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
