# API Reference

Canonical machine-readable contract:

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`

This guide is a human-oriented map of the current endpoint surface. Model-level field
descriptions and examples are maintained in the generated OpenAPI contract.

## Performance APIs

### `POST /performance/twr`

- purpose: calculate time-weighted return
- request model: `app.models.twr_requests.TWRAnalyticsRequest`
- response model: `app.models.responses.PerformanceResponse | app.models.responses.TWRAcceptedResponse`
- execution mode: synchronous or async depending on workload shape
- lineage: durable lineage metadata is written and artifacts are materialized asynchronously
- supported input modes:
  - `stateless`
  - `stateful`
- contract note:
  - `calculation_id` is caller-optional; when omitted, lotus-performance generates one and returns it in the response
  - existing stateless callers can continue sending top-level `valuation_points`
  - new callers should prefer the Lotus-style envelope with `input_mode`, `stateless_input`, and `stateful_input`
  - stateful mode sources portfolio timeseries from lotus-core query-control-plane via `CORE_CONTROL_PLANE_BASE_URL` and normalizes them into canonical valuation points before engine execution
  - `include_benchmark=true` is the canonical switch for returning benchmark performance alongside portfolio TWR
  - the nested `benchmark` object is optional configuration; it can supply `benchmark_id`, `input_mode`, and `return_source`
  - when `include_benchmark=true`, explicit `benchmark.benchmark_id` overrides lotus-core assignment lookup; otherwise stateful mode can source the portfolio-to-benchmark mapping from lotus-core
  - when `include_benchmark=true`, each period result also includes arithmetic `relative_performance` versus the resolved benchmark
  - when a benchmark is resolved, the response also emits top-level `benchmark_context`

### `GET /performance/twr/results/{calculation_id}`

- purpose: retrieve durable async TWR result
- response model:
  - completed: `app.models.responses.PerformanceResponse`
  - still running: `app.models.responses.TWRAcceptedResponse`

### `GET /performance/executions/{calculation_id}`

- purpose: poll durable execution lifecycle state for async and synchronous calculations
- response model: `app.models.execution_polling.ExecutionResponse`
- use this endpoint when:
  - an analytics endpoint returns `202 Accepted` with a `poll_path`
  - support needs to inspect stage progress, retry state, terminal failure details, or upstream snapshot lineage
  - downstream clients need to decide whether to continue polling or call the endpoint-specific `result_path`
- do not use this endpoint as the analytics result payload; call the endpoint-specific result route once `status=complete`
- response includes:
  - top-level `status`, `execution_mode`, `analytics_type`, `portfolio_id`, requested-window metadata, timestamps, and fingerprints
  - `stages[]` for submission, retrieval, normalization, execution, and lineage materialization progress where applicable
  - `upstream_snapshots[]` for stateful source provenance including upstream endpoint, source identifier, fingerprints, retrieval status, and paging metadata
  - `compute_job` for async executor status, attempts, worker lease, retry, and failure-pressure metadata
  - `async_result` for endpoint-specific result materialization status and terminal error details
- downstream consumers:
  - `lotus-risk` uses this endpoint when polling async returns-series integration results
  - `lotus-gateway` currently handles synchronous analytics and accepted-payload replay behavior but does not directly poll this endpoint
- certification evidence: `docs/technical/execution-polling-endpoint-certification.md`

### `POST /performance/inspections/twr`

- purpose: submit a durable supportability inspection for a TWR result or proposed TWR request
- request model: `app.models.inspection_requests.TWRInspectionRequest`
- response model: `app.models.inspection_responses.TWRInspectionAcceptedResponse`
- execution mode: async only
- use this endpoint when:
  - a TWR number is mathematically available but source quality, source economics, reconciliation, or response arithmetic needs to be explained
  - support or front office needs owner-routed findings and downloadable evidence artifacts
  - canonical portfolio validation needs to prove no nonpositive capital-base days, reconciliation gaps, cash-flow timing contradictions, unsupported cash-flow labels, or extreme source-driven daily moves remain
- do not use this endpoint to calculate TWR; use `POST /performance/twr` for the return result
- supported subject modes:
  - `subject_type=twr_calculation` inspects an existing durable TWR calculation and can run calculation-consistency, source-quality, reconciliation, and source-economics checks when lineage is available
  - `subject_type=twr_request` inspects a proposed request payload and runs request-local source-quality and plausibility checks without mutating the normal TWR contract
- supported inspection profiles:
  - `support_triage`: default support workflow for explainability and owner routing
  - `canonical_validation`: governed validation profile for canonical seeded portfolios such as `PB_SG_GLOBAL_BAL_001`
  - `deep_reconciliation`: heavier profile for upstream state and economics escalation
- async accepted responses return:
  - `poll_path=/performance/executions/{inspection_id}`
  - `result_path=/performance/inspections/{inspection_id}`

### `GET /performance/inspections/{inspection_id}`

- purpose: retrieve a durable TWR inspection result when complete, or the accepted envelope while queued or running
- response model:
  - completed: `app.models.inspection_responses.TWRInspectionResponse`
  - still running: `app.models.inspection_responses.TWRInspectionAcceptedResponse`
- response includes:
  - `verdict`: `supportable`, `supportable_with_warnings`, `not_supportable`, or `inspection_failed`
  - `findings[]`: stable finding code, severity, category, owning repository, explanation, recommendation, and structured evidence
  - `owner_summary`: primary and secondary owning repositories inferred from findings
  - `evidence_summary`: count and tie-out metrics from completed check families
  - `check_coverage`: completed and pending check families, so absence of findings is not misread as universal coverage
  - `related_lineage`: source TWR lineage pointer for existing-calculation inspections
  - `artifacts`: downloadable evidence artifact paths
  - `workflow_pack_run`: bounded Lotus AI workflow-pack posture when the optional support brief is generated through the explicit workflow-pack seam

### `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}`

- purpose: download one completed TWR inspection evidence artifact
- Swagger status: documented in `/docs` because the route is part of the supportability contract
- supported artifact names:
  - `inspection_summary.json`
  - `findings.json`
  - `support_brief.md` when Lotus AI support-brief generation succeeds
  - `source_quality_summary.json` when source-quality checks run
  - `reconciliation_summary.json` when stateful reconciliation runs
  - `source_economics_summary.json` when stateful source-economics checks run
- error behavior:
  - `404` when the inspection record is missing, incomplete, not a TWR inspection, or the artifact name is not recorded for that inspection
  - `503` when durable metadata declares the artifact but the artifact content is missing from storage
- support-facing check inventory lives in:
  - `docs/guides/twr_inspection_checks.md`
- certification evidence lives in:
  - `docs/technical/twr-inspection-endpoint-certification.md`

### `POST /performance/mwr`

- purpose: calculate money-weighted return
- request model: `app.models.mwr_analytics_requests.MoneyWeightedReturnAnalyticsRequest`
- response model: `app.models.mwr_responses.MoneyWeightedReturnResponse`
- execution mode: synchronous
- lineage: durable lineage metadata is written and artifacts are materialized asynchronously
- supported input modes:
  - `stateless`
  - `stateful`
- contract note:
  - use MWR for the investor capital-timing return lens; use TWR for manager or strategy performance independent of client deposits and withdrawals
  - existing stateless callers can continue sending top-level `begin_mv`, `end_mv`, and `cash_flows`
  - new callers should prefer the Lotus-style envelope with `input_mode`, `stateless_input`, and `stateful_input`
  - stateful mode sources portfolio timeseries from lotus-core query-control-plane via `CORE_CONTROL_PLANE_BASE_URL` and normalizes them into canonical `begin_mv`, `end_mv`, `cash_flows`, and authoritative `start_date` before engine execution
  - stateful MWR includes explicit external source cash flows and cross-observation capital carry-forward adjustments in the MWR cash-flow schedule
  - operational fees remain performance drag; they are not treated as investor deposits or withdrawals
  - `emit_cashflows_used=true` returns the signed cash-flow schedule used by the calculation
  - lotus-performance stamps source consumer identity server-side for the stateful envelope

### `POST /performance/workspace-summary`

- purpose: calculate an interaction-efficient workspace summary in one source-owned response
- request model: `app.models.workspace_summary_requests.WorkspaceSummaryRequest`
- response model: `app.models.workspace_summary_responses.WorkspaceSummaryResponse | app.models.workspace_summary_responses.WorkspaceSummaryAcceptedResponse`
- execution mode: synchronous for lighter requests, `202 Accepted` for heavier requests offloaded to the compute executor
- lineage: durable lineage metadata is written and artifacts are materialized asynchronously
- supported input modes:
  - `stateless`
  - `stateful`
- contract note:
  - one request returns multi-horizon `portfolio_twr.net`, `portfolio_twr.gross`, benchmark summary, active summary, and money-weighted return summary
  - the workspace period family currently supports `1D`, `2D`, `5D`, `10D`, `1M`, `3M`, `6M`, `YTD`, `1Y`, `2Y`, `5Y`, `10Y`, `SI`, and `EXPLICIT`
  - annualized return is always present; for periods up to one year it intentionally equals cumulative return to keep the response shape consistent
  - the service resolves the longest requested window once and derives shorter periods from the same sourced data
  - stateful mode retrieves only the longest required portfolio window from lotus-core and preserves retrieval chunk counts in audit output
  - benchmark context remains explicit across stateless user-input and stateful lotus-core-linked modes
  - summary and breakdown blocks include beginning market value, ending market value, beginning-of-day cash flow, end-of-day cash flow, fees, net cash flow, and flow-adjusted end market value where those economics belong to the surface
  - legacy top-level `valuation_points` remains deprecated compatibility input; new stateless callers should use `stateless_input.valuation_points`
  - contribution and attribution drill-downs are intentionally not embedded in this endpoint; use `/performance/contribution` and `/performance/attribution` for those analytical details
  - async accepted responses return:
    - `poll_path=/performance/executions/{calculation_id}`
    - `result_path=/performance/workspace-summary/results/{calculation_id}`
  - canonical example payloads live in:
    - `docs/examples/workspace_summary_request.json`
    - `docs/examples/workspace_summary_stateful_detail_request.json`
  - certification evidence lives in:
    - `docs/technical/workspace-summary-endpoint-certification.md`

**Canonical example: stateless workspace summary**

```json
{
  "input_mode": "stateless",
  "portfolio_id": "WORKSPACE_SUMMARY_01",
  "report_end_date": "2026-03-31",
  "performance_start_date": "2025-12-31",
  "periods": [
    { "period": "1M", "frequencies": ["daily", "monthly"] },
    { "period": "YTD", "frequencies": ["monthly"] },
    { "period": "1Y", "frequencies": ["monthly", "yearly"] }
  ],
  "include_benchmark": true,
  "stateless_input": {
    "valuation_points": [
      { "perf_date": "2026-01-02", "begin_mv": 1000000.0, "end_mv": 1008500.0 },
      { "perf_date": "2026-02-27", "begin_mv": 1008500.0, "bod_cf": 25000.0, "end_mv": 1039500.0 },
      { "perf_date": "2026-03-31", "begin_mv": 1039500.0, "eod_cf": -5000.0, "mgmt_fees": -350.0, "end_mv": 1054100.0 }
    ]
  },
  "benchmark": {
    "benchmark_id": "BMK_GLOBAL_60_40",
    "input_mode": "stateless",
    "return_source": "vendor_series",
    "stateless_input": {
      "benchmark_currency": "USD",
      "benchmark_return_points": [
        { "perf_date": "2026-01-02", "benchmark_return": 0.0065 },
        { "perf_date": "2026-02-27", "benchmark_return": 0.011 },
        { "perf_date": "2026-03-31", "benchmark_return": 0.009 }
      ]
    }
  }
}
```

**Canonical example: stateful workspace summary**

```json
{
  "input_mode": "stateful",
  "portfolio_id": "WORKSPACE_SUMMARY_STATEFUL_01",
  "report_end_date": "2026-03-31",
  "periods": [
    { "period": "1M", "frequencies": ["daily", "monthly"] },
    { "period": "YTD", "frequencies": ["monthly"] },
    { "period": "SI", "frequencies": ["monthly", "yearly"] }
  ],
  "stateful_input": {},
  "include_benchmark": true,
  "benchmark": {
    "input_mode": "stateful",
    "stateful_input": {}
  },
  "report_ccy": "USD",
  "currency_mode": "BASE_ONLY"
}
```

**Canonical response excerpt**

```json
{
  "results_by_period": {
    "YTD": {
      "portfolio_twr": {
        "net": {
          "summary": {
            "economics": {
              "begin_market_value": 1000000.0,
              "end_market_value": 1054100.0,
              "beginning_cash_flow": 25000.0,
              "ending_cash_flow": -5000.0,
              "fees": -350.0,
              "net_cash_flow": 20000.0,
              "flow_adjusted_end_market_value": 1034100.0
            },
            "period_return": { "base": 3.41, "local": 3.18, "fx": 0.23 },
            "cumulative_return": { "base": 3.41, "local": 3.18, "fx": 0.23 },
            "annualized_return": { "base": 3.41, "local": 3.18, "fx": 0.23 }
          },
          "breakdowns": {
            "monthly": [
              {
                "period": "2026-03",
                "period_start": "2026-03-01",
                "period_end": "2026-03-31",
                "period_return": { "base": 1.4, "local": 1.25, "fx": 0.15 },
                "cumulative_return": { "base": 1.4, "local": 1.25, "fx": 0.15 },
                "annualized_return": { "base": 1.4, "local": 1.25, "fx": 0.15 }
              }
            ]
          }
        }
      },
      "benchmark": {
      "benchmark_id": "BMK_GLOBAL_60_40",
      "summary": {
        "period_return": { "base": 2.98 },
        "cumulative_return": { "base": 2.98 },
        "annualized_return": { "base": 2.98 }
      },
      "breakdowns": {}
      },
      "active": {
      "net": {
        "period_return": { "base": 0.43 },
        "cumulative_return": { "base": 0.43 },
        "annualized_return": { "base": 0.43 }
      },
      "gross": {
        "period_return": { "base": 0.46 },
        "cumulative_return": { "base": 0.46 },
        "annualized_return": { "base": 0.46 }
      }
      },
      "money_weighted_return": {
      "method": "XIRR",
      "period_return": 3.27,
      "cumulative_return": 3.27,
      "annualized_return": 3.27
      }
    }
  },
  "audit": {
    "counts": {
      "portfolio_chunk_count": 3,
      "benchmark_chunk_count": 2
    }
  }
}
```

Return semantics for the workspace surface are now explicit rather than inferred:

- summary blocks emit `period_return`, `cumulative_return`, and `annualized_return`
- breakdown rows emit `period_return`, `cumulative_return`, and `annualized_return`
- for periods up to one year, `annualized_return` intentionally equals `cumulative_return`
- benchmark and active blocks follow the same vocabulary so downstream apps do not need a
  surface-specific mapping layer
- benchmark blocks do not fabricate market-value economics when the benchmark source only owns
  return history

### `GET /performance/workspace-summary/results/{calculation_id}`

- purpose: retrieve the durable async workspace summary result
- response model:
  - completed: `WorkspaceSummaryResponse`
  - still running: `WorkspaceSummaryAcceptedResponse`

### `POST /performance/benchmark`

- purpose: calculate benchmark performance
- request model: `app.models.benchmark_analytics_requests.BenchmarkAnalyticsRequest`
- response model:
  - sync: `app.models.benchmark_responses.BenchmarkPerformanceResponse`
  - async accepted: `app.models.benchmark_responses.BenchmarkAcceptedResponse`
- lineage: durable lineage metadata is written and artifacts are materialized asynchronously
- supported input modes:
  - `stateless`
  - `stateful`
- execution mode:
  - synchronous for stateless and smaller stateful requests
  - `202 Accepted` for larger stateful benchmark requests offloaded to the compute executor
- contract note:
  - `calculation_id` is caller-optional; when omitted, lotus-performance generates one and returns it in the response
  - new callers should prefer the Lotus-style envelope with `input_mode`, `stateless_input`, and `stateful_input`
  - `return_source=calculated` is the default execution path
  - `return_source=vendor_series` is an explicit non-default override
  - stateless calculated mode accepts exactly one of:
    - `stateless_input.component_observations`
    - `stateless_input.component_price_points`
  - stateful calculated mode sources benchmark definition, component price series, and FX inputs from lotus-core and normalizes them into canonical benchmark component observations before engine execution
  - stateful calculated mode supports multi-segment rebalance windows through the lotus-core composition-window contract
- output checks:
  - `benchmark.summary.period_return` geometrically links benchmark daily returns inside the resolved period
  - `daily_returns[].benchmark_return` reconciles to same-date component contributions in calculated mode
  - `component_contributions[].contribution` equals `weight_bop * component_return` in percentage-point output units
  - `meta`, `diagnostics`, and `audit` carry lineage, effective-start, count, and weight-residual evidence
- certification: `docs/technical/benchmark-endpoint-certification.md`
- downstream guidance:
  - downstream analytics engines that only need aligned benchmark return series should use `POST /integration/returns/series`, not this endpoint

### `GET /performance/benchmark/results/{calculation_id}`

- purpose: retrieve the durable async benchmark result
- response model:
  - completed: `BenchmarkPerformanceResponse`
  - still running: `BenchmarkAcceptedResponse`

### `POST /performance/contribution`

- purpose: calculate position contribution
- request model: `app.models.contribution_analytics_requests.ContributionAnalyticsRequest`
- response model:
  - sync: `app.models.contribution_responses.ContributionResponse`
  - async accepted: `app.models.contribution_responses.ContributionAcceptedResponse`
- input modes:
  - `stateless`
  - `stateful`
  - existing stateless callers can continue sending top-level `portfolio_data` and `positions_data`
  - new callers should prefer the Lotus-style envelope with `input_mode`, `stateless_input`, and `stateful_input`
  - stateful mode sources portfolio and position timeseries from lotus-core query-control-plane via `CORE_CONTROL_PLANE_BASE_URL` and normalizes them into canonical contribution inputs before engine execution
  - lotus-performance stamps source consumer identity server-side for the stateful envelope
  - position-level `average_weight` and grouped `weight_avg` are both emitted in percentage units
  - `position_contributions` remains the primary ranking surface for top/bottom contributor views
  - optional `hierarchy` rows reconcile to the same residual-adjusted `total_contribution` as the position rows
  - `emit.timeseries` and `emit.by_position_timeseries` return daily ladders that reconcile to `total_contribution`
  - `emit.top_n_per_level`, `emit.threshold_weight`, `emit.include_other`, and `emit.include_unclassified` control hierarchy row shaping
- execution mode:
  - synchronous for smaller stateless sets and smaller stateful windows
  - `202 Accepted` with `calculation_id`, `poll_path`, and `result_path` when offloaded to the compute executor
- certification: `docs/technical/contribution-endpoint-certification.md`

### `GET /performance/contribution/results/{calculation_id}`

- purpose: retrieve the durable async contribution result
- response model:
  - completed: `ContributionResponse`
  - still running: `ContributionAcceptedResponse`

### `POST /performance/attribution`

- purpose: calculate multi-level attribution
- request model: `app.models.attribution_analytics_requests.AttributionAnalyticsRequest`
- response model:
  - sync: `app.models.attribution_responses.AttributionResponse`
  - async accepted: `app.models.attribution_responses.AttributionAcceptedResponse`
- input modes:
  - `stateless`
  - `stateful`
  - new callers should prefer the Lotus-style envelope with `input_mode`, `stateless_input`, and `stateful_input`
  - stateful mode sources portfolio and position timeseries from lotus-core query-control-plane via `CORE_CONTROL_PLANE_BASE_URL` and derives benchmark group inputs from benchmark assignment plus the shared benchmark engine sourcing path
  - lotus-performance stamps source consumer identity server-side for the stateful envelope
  - when a benchmark is resolved, the response also emits top-level `benchmark_context`
  - each attribution group row now includes average portfolio weight, average benchmark weight, portfolio return, and benchmark return alongside allocation, selection, interaction, and total effect
  - each attribution level exposes authoritative totals in `totals` and as explicit `allocation_total_pct`, `selection_total_pct`, `interaction_total_pct`, and `total_effect_pct` fields
  - downstream consumers should use level totals for footers and summary-only states instead of summing visible rows
  - current stateful fences:
    - `mode=by_instrument` only
    - `group_by` limited to canonical lotus-core attribution dimensions plus `currency`: `asset_class`, `sector`, `country`, `currency`
    - `currency_mode=BOTH` requires `report_ccy`
    - `currency_mode=BOTH` requires `fx.rates` when sourced positions include currencies different from `report_ccy`
- execution mode:
  - synchronous for smaller stateless sets and smaller stateful windows
  - `202 Accepted` when offloaded to the compute executor

### `GET /performance/attribution/results/{calculation_id}`

- purpose: retrieve the durable async attribution result
- response model:
  - completed: `AttributionResponse`
  - still running: `AttributionAcceptedResponse`

### `GET /performance/executions/{calculation_id}`

- purpose: poll durable execution state
- response includes:
  - execution status
  - execution stages
  - upstream snapshots
  - compute job state
  - async result metadata

### `GET /performance/lineage/{calculation_id}`

- purpose: retrieve durable lineage status and artifact URLs
- response model: `app.models.lineage_responses.LineageResponse`
- use this endpoint when support, operations, or front-office evidence workflows need to inspect
  whether calculation lineage has been materialized and which artifacts can be downloaded
- response includes:
  - `calculation_id`, `calculation_type`, `timestamp_utc`, and durable lineage `status`
  - `artifacts` keyed by artifact filename, each containing a controlled service-owned `url`
  - `error_message` when materialization failed
- integrity note:
  - complete lineage requires a readable `manifest.json` that is structurally valid and consistent with the durable lineage record
  - complete lineage also requires every declared artifact to exist on disk before URLs are returned
  - inconsistent or corrupted manifests return `503` instead of silently serving drifted audit metadata
- certification evidence: `docs/technical/lineage-endpoint-certification.md`

### `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`

- purpose: download a specific lineage artifact through a controlled calculation/artifact route
- Swagger status: documented in `/docs` because the route is part of the public reproducibility and supportability contract
- execution mode: synchronous file retrieval
- contract note:
  - only artifacts listed in the lineage record are downloadable
  - unknown artifact names return `404`
  - missing or inconsistent lineage manifests return `503`
  - artifacts declared in durable lineage but missing from storage return `503`

## Integration APIs

### `GET /integration/capabilities`

- purpose: advertise lotus-performance capabilities to downstream consumers
- response model: integration capabilities contract in `app.api.endpoints.integration_capabilities`
- canonical query controls:
  - `consumer_system`: downstream consumer system, for example `lotus-gateway`, `lotus-risk`, or `lotus-manage`
  - `tenant_id`: tenant or policy scope, default `default`
  - `feature_limit`: bounded feature row limit, default `100`, max `500`
  - `workflow_limit`: bounded workflow row limit, default `50`, max `200`
- response includes:
  - service-level `supported_input_modes`
  - endpoint-level `analytics_surfaces` entries with:
    - `path`
    - `supported_input_modes`
    - `supports_async`
    - `poll_path_template`
    - `result_path_template`
    - `stateful_restrictions`
    - `contract_notes`
    - `options`
- use `analytics_surfaces` when a downstream Lotus app needs the actual contract for a specific endpoint rather than only the coarse service-wide mode list
- `workspace_summary` is now advertised as a first-class analytics surface in this contract, including:
  - multi-horizon period-family support
  - longest-window sourcing behavior
  - annualization surface semantics
- async-capable surfaces now also advertise their canonical execution polling and endpoint-specific result path templates so downstream apps can discover the accepted-to-completed flow without reconstructing it from separate docs
- `workspace_summary` now also advertises machine-readable request options for benchmark mode support
- canonical capability example payload:
  - `docs/examples/integration_capabilities_response.json`
- certification evidence lives in:
  - `docs/technical/integration-capabilities-endpoint-certification.md`

**Canonical capabilities response excerpt**

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "consumer_system": "lotus-gateway",
  "supported_input_modes": ["stateful", "stateless"],
  "analytics_surfaces": [
    {
      "key": "workspace_summary",
      "path": "/performance/workspace-summary",
      "supports_async": true,
      "poll_path_template": "/performance/executions/{calculation_id}",
      "result_path_template": "/performance/workspace-summary/results/{calculation_id}",
      "stateful_restrictions": [],
      "options": [
        {
          "key": "benchmark_mode",
          "supported_values": ["user_input_stateless", "linked_stateful"]
        }
      ]
    }
  ],
  "features": [
    {
      "key": "pa.analytics.workspace_summary",
      "enabled": true
    }
  ],
  "workflows": [
    {
      "workflow_key": "performance_workspace",
      "enabled": true
    }
  ]
}
```

### `GET /integration/runtime-status`

- purpose: expose an operational snapshot of runtime state for support and platform operators
- response model: `app.models.runtime_status.RuntimeStatusResponse`
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - aggregate runtime status
  - aggregate `runtime_degradation_reasons`
  - aggregate `runtime_degradation_details`
  - draining state
  - durable metadata store availability
  - remediation hints for durable metadata store and lineage queue unavailability reasons when the service knows the next recovery step
  - lineage storage availability folded into `lineage_queue.status` / `lineage_queue.reason`
  - lineage storage capacity details:
    - `storage_total_bytes`
    - `storage_used_bytes`
    - `storage_free_bytes`
    - `storage_free_ratio`
  - active compute and lineage degradation-policy thresholds
  - compute queue backlog details
  - oldest pending, leased, and running compute-job ages
  - retry-backlog, lease-expiry, reclaimable, and terminal-failure compute-job counts
  - compute inspection anchors for the oldest pending, leased, and running work plus the latest terminal failure
  - compute inspection anchors also include the latest recovered compute job returned to pending after retry or stale-lease recovery
  - a bounded `recent_recoveries` list for compute showing the latest requeued items, recovery kind, timestamp, and attempt count
  - compute `degradation_reasons`
  - compute `degradation_details`
  - lineage queue backlog details
  - retry-backlog, reclaimable, and terminal-failure lineage payload counts
  - lineage inspection anchors for the oldest pending and leased work plus the latest terminal failure
  - lineage inspection anchors also include the latest recovered lineage item returned to pending after a retryable materialization failure
  - a bounded `recent_recoveries` list for lineage showing the latest requeued items, recovery kind, timestamp, and attempt count
  - lineage `degradation_details`
  - lineage `degradation_reasons`
  - governed recovery-drill action visibility with active-run status, count, and oldest active-run anchor fields
  - latest stale recovery-drill reclaim visibility with the reclaimed operator, target, acquisition time, reclaim time, reclaim age, and cumulative reclaim count
  - retained runtime-retention cleanup assurance with latest operator, cleanup mode, retention window, freshness, and live dry-run preview counts under the current policy
  - governed runtime-retention action visibility with active-run status, count, and oldest active-run anchor fields
  - latest stale runtime-retention reclaim visibility with the reclaimed operator, target, acquisition time, reclaim time, reclaim age, and cumulative reclaim count
- runtime may report `degraded` when configured queue-age or failure-pressure thresholds are exceeded
- runtime also reports `degraded` when lineage storage is missing, invalid, or unreadable even if the durable DB remains healthy
- runtime can also report lineage-storage saturation pressure before writes fail:
  - `lineage_storage_free_bytes_below_threshold`
  - `lineage_storage_free_ratio_below_threshold`
- lineage queue policy now exposes:
  - `storage_min_free_bytes`
  - `storage_min_free_ratio`
- use the inspection anchors to jump directly to:
  - `/performance/executions/{calculation_id}`
  - `/performance/lineage/{calculation_id}`
- certification evidence: `docs/technical/runtime-status-endpoint-certification.md`

### `GET /integration/runtime-work-items`

- purpose: return exact compute and lineage work items for operator drill-down
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- query parameters:
  - `queue`: `both`, `compute`, or `lineage`
  - `status`: `active`, `failed`, `all`, or `reclaimable`
  - `limit`: max items returned per queue
  - `offset`: zero-based page offset applied per queue
  - `min_age_seconds`: optional stale-item filter for operator triage
  - `compute_analytics_type`: optional compute-only analytics family filter
  - `lineage_calculation_type`: optional lineage-only calculation family filter
  - `calculation_id_contains`: optional calculation-handle substring filter across selected queues
- response includes:
  - durable metadata store availability
  - queue-specific availability for compute and lineage inspection
  - queue-specific `total_count`, `returned_count`, and `next_offset`
  - `reclaimable` isolates work whose durable worker lease already expired and is eligible for recovery or re-lease
  - echoed targeted filters for operator auditability
  - filtered compute work items with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, lifecycle state, age, attempts, and failure context
  - filtered lineage work items with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, lifecycle state, age, attempts, and failure context
- `result_path` can now point directly to async result routes for `TWR`, `BENCHMARK`, `ReturnsSeries`, `Contribution`, and `Attribution` when that workflow exposes a stable endpoint-specific result surface
- use this when runtime-status tells you there is pressure, and you need the actual work items behind it without querying the database directly
- `next_offset` is queue-local and only appears when additional filtered work items remain for that queue
- response model: `app.models.runtime_work_items.RuntimeWorkItemsResponse`
- certification evidence: `docs/technical/runtime-work-items-endpoint-certification.md`

### `GET /integration/runtime-recoveries`

- purpose: return recent compute and lineage recovery events for operator drill-down
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- query parameters:
  - `queue`: `both`, `compute`, or `lineage`
  - `limit`: max recovery events returned per queue
  - `offset`: zero-based page offset applied per queue
  - `recovered_after`: optional inclusive lower UTC timestamp bound on recovery-event timestamps
  - `recovered_before`: optional inclusive upper UTC timestamp bound on recovery-event timestamps
  - `cursor_recovered_before`: optional seek cursor timestamp for deterministic traversal of older matching events
  - `cursor_calculation_id_before`: optional seek cursor calculation handle paired with the cursor timestamp
  - `compute_analytics_type`: optional compute-only analytics family filter
  - `lineage_calculation_type`: optional lineage-only calculation family filter
  - `calculation_id_contains`: optional calculation-handle substring filter across selected queues
- response includes:
  - durable metadata store availability
  - queue-specific availability for compute and lineage recovery inspection
  - queue-specific `total_count`, `returned_count`, `next_offset`, `next_cursor_recovered_before`, and `next_cursor_calculation_id_before`
  - filtered compute recovery events with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, analytics type, recovery kind, recovery timestamp, attempt count, and last durable error type
  - filtered lineage recovery events with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, calculation type, recovery kind, recovery timestamp, and attempt count
- `result_path` can now point directly to async result routes for `TWR`, `BENCHMARK`, `ReturnsSeries`, `Contribution`, and `Attribution` when that workflow exposes a stable endpoint-specific result surface
- use this when runtime-status shows recent recovery activity and you need the concrete event stream behind the bounded status snapshot without querying the database directly
- `next_offset` is queue-local and only appears when additional filtered events remain for that queue
- the cursor fields give deterministic seek pagination for hot recovery streams where offset paging may drift as new recoveries arrive
- response model: `app.models.runtime_recoveries.RuntimeRecoveriesResponse`
- certification evidence: `docs/technical/runtime-recoveries-endpoint-certification.md`

### `GET /integration/recovery-drills`

- purpose: inspect retained durable recovery-drill evidence and manifest state
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - retained recovery-drill evidence artifacts
  - latest retained drill summary
  - filtering by operator, backup identifier, status, and bounded time window
  - retained enterprise request context when available:
    - `tenant_id`
    - `correlation_id`
- response model: `app.models.recovery_drill_history.RecoveryDrillHistoryResponse`
- certification evidence: `docs/technical/recovery-drills-endpoint-certification.md`

### `POST /integration/recovery-drills/run`

- purpose: execute a governed durable recovery drill through the service-owned control plane
- privileged-write auth:
  - when `ENTERPRISE_ENFORCE_AUTHZ=true`, this route requires enterprise identity headers
  - default governed capability: `operations.runtime.manage`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- request includes:
  - `backup_identifier`
- response includes:
  - immediate recovery-drill summary for the run that just executed
  - operator identity carried from `X-Actor-Id` or `X-Service-Identity`
  - retained enterprise request context from `X-Tenant-Id` and `X-Correlation-Id` when supplied
  - same-correlation retries replay the original retained evidence only when operator and tenant ownership also match, returning `X-Idempotent-Replay: true`; otherwise the request is treated as a fresh governed action
  - `409` plus `Retry-After` when a recent matching manual drill for the same operator, tenant, and backup identifier already completed inside the configured cooldown window
  - `409` when the same governed drill is already running in-flight for the same operator, tenant, and backup identifier
  - stale in-flight drill leases are reclaimed automatically after the configured stale threshold instead of blocking forever after a crash
- use this when an operator needs an audited recovery drill without shell access
- request model: `app.models.recovery_drill_history.RecoveryDrillRunRequest`
- response model: `app.models.recovery_drill_history.RecoveryDrillRunResponse`
- certification evidence: `docs/technical/recovery-drills-endpoint-certification.md`

### `GET /integration/runtime-retention-cleanups`

- purpose: inspect retained runtime-retention cleanup evidence and manifest state
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - retained cleanup evidence artifacts
  - latest retained cleanup summary
  - filtering by operator, trigger mode, job identity, cleanup mode, status, and bounded time window
  - retained enterprise request context when available:
    - `tenant_id`
    - `correlation_id`
- response model: `app.models.runtime_retention_history.RuntimeRetentionHistoryResponse`
- certification evidence: `docs/technical/runtime-retention-endpoint-certification.md`

### `POST /integration/runtime-retention-cleanups/run`

- purpose: execute a governed runtime-retention dry run or apply action through the service-owned control plane
- privileged-write auth:
  - when `ENTERPRISE_ENFORCE_AUTHZ=true`, this route requires enterprise identity headers
  - default governed capability: `operations.runtime.manage`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- request includes:
  - `apply`
  - optional `retention_days`
  - optional `job_id`
- response includes:
  - retained cleanup evidence summary for the run that just executed
  - operator identity carried from `X-Actor-Id` or `X-Service-Identity`
  - retained enterprise request context from `X-Tenant-Id` and `X-Correlation-Id` when supplied
  - `trigger_mode="manual"` for this control-plane action path
  - same-correlation retries replay the original retained evidence only when operator and tenant ownership also match, returning `X-Idempotent-Replay: true`; otherwise the request is treated as a fresh governed action
  - `apply=true` requires a recent matching `dry_run` preview for the same governed request shape before execution
  - `409` plus `Retry-After` when a recent manual cleanup already completed inside the configured cooldown window
  - `409` when the same governed cleanup action is already running in-flight for the same operator, tenant, action mode, retention window, and job identity
  - stale in-flight cleanup leases are reclaimed automatically after the configured stale threshold instead of blocking forever after a crash
- use this when an operator needs an audited cleanup preview or a deliberate apply action without shell access
- request model: `app.models.runtime_retention_history.RuntimeRetentionCleanupRunRequest`
- response model: `app.models.runtime_retention_history.RuntimeRetentionCleanupRunResponse`
- certification evidence: `docs/technical/runtime-retention-endpoint-certification.md`

### `POST /integration/returns/series`

- purpose: return canonical portfolio, benchmark, and risk-free return series for downstream analytics
- use this endpoint when risk, attribution, or another analytics service needs reusable return
  observations; do not reconstruct this feed from TWR, MWR, or benchmark endpoint responses
- request model: `app.models.returns_series.ReturnsSeriesRequest`
- response model:
  - sync: `app.models.returns_series.ReturnsSeriesResponse`
  - async accepted: `app.models.returns_series.ReturnsSeriesAcceptedResponse`
- execution mode:
  - synchronous for stateless and smaller stateful windows
  - `202 Accepted` for long-window stateful requests offloaded to the compute executor
- contract note:
  - stateless benchmark series are still caller-supplied via `stateless_input.benchmark_returns`
  - in stateful mode, benchmark sourcing defaults to the shared lotus-performance benchmark calculation path
  - lotus-performance stamps source consumer identity server-side for the stateful envelope
  - `benchmark.return_source="vendor_series"` is an explicit stateful-only override for lotus-core benchmark return-series retrieval
  - `benchmark.benchmark_id` is only meaningful in stateful mode for explicit benchmark override; otherwise lotus-core benchmark assignment can resolve the benchmark id
  - when both portfolio and benchmark series are present, the response also emits arithmetic `active_returns`
  - the response also emits cumulative ladders:
    - `cumulative_portfolio_returns`
    - `cumulative_benchmark_returns`
    - `cumulative_risk_free_returns`
    - `cumulative_active_returns`
  - cumulative portfolio, benchmark, and risk-free ladders are geometrically linked
  - `cumulative_active_returns` is arithmetic excess of cumulative portfolio and cumulative benchmark returns
  - when stateful benchmark resolution is used, the response also emits `benchmark_context` with the resolved `benchmark_id` and `return_source`
  - `series.*_returns` values are decimal ratios, not percentages; `0.0012` means `0.12%`
  - stateful risk-free points carrying `value_convention="annualized_rate"` are converted to
    period returns using the supplied day-count convention before being returned or linked
  - `calendar_policy=BUSINESS` filters daily output to weekdays before coverage diagnostics;
    `MARKET` currently applies the same weekday approximation and emits a warning
  - downstream certification and figure tie-outs are recorded in
    `docs/technical/returns-series-endpoint-certification.md`

### `GET /integration/returns/series/results/{calculation_id}`

- purpose: retrieve the durable async returns-series result
- response model:
  - completed: `ReturnsSeriesResponse`
  - still running: `ReturnsSeriesAcceptedResponse`

### `POST /integration/benchmarks/exposure-context`

- purpose: return benchmark exposure history aligned to benchmark performance context for downstream active-risk attribution
- request model: `app.models.benchmark_exposure_context.BenchmarkExposureContextRequest`
- response model: `app.models.benchmark_exposure_context.BenchmarkExposureContextResponse`
- execution mode:
  - synchronous v1 integration endpoint
- ownership:
  - lotus-core remains the benchmark composition and classification system of record
  - lotus-performance exposes the derived, lineage-backed view used with benchmark returns
- supported grouping dimensions:
  - `POSITION`
  - `SECTOR`
  - `ASSET_CLASS`
- gated grouping dimensions:
  - `ISSUER` remains unsupported until benchmark issuer exposure semantics are defined
- contract notes:
  - if `benchmark_id` is omitted, lotus-performance resolves benchmark assignment through lotus-core
  - benchmark market-series is requested with `series_fields=["component_weight"]`
  - `frequency=DAILY` is the only supported v1 frequency; monthly or weekly benchmark exposure history is intentionally rejected rather than silently resampled
  - response rows use decimal weights, not percentages
  - row weights are returned as decimal fractions where `0.60` means a 60% benchmark exposure
  - `POSITION` rows carry `component_id`; aggregate `SECTOR` and `ASSET_CLASS` rows omit `component_id`
  - pagination uses `page.page_size` and opaque `page.next_page_token` values returned by the endpoint
  - lineage metadata includes `source_system="lotus-core"` and `served_by="lotus-performance"`
  - downstream certification and consumer posture are recorded in
    `docs/technical/benchmark-exposure-context-endpoint-certification.md`

## Health and observability

### `GET /`

- purpose: return the service-entry message and point callers to `/docs`
- use this only as an informational entry route; do not treat it as a strategic analytics or operator API
- response model: `app.models.platform_surfaces.RootResponse`
- certification evidence: `docs/technical/platform-surfaces-endpoint-certification.md`

### `GET /health`

- returns basic process health
- use this as a lightweight reachability probe, not as a durable readiness contract
- response model: `app.models.platform_surfaces.HealthStatusResponse`
- certification evidence: `docs/technical/platform-surfaces-endpoint-certification.md`

### `GET /health/live`

- returns liveness state
- use this to confirm the process is running without checking durable dependencies
- response model: `app.models.platform_surfaces.HealthStatusResponse`
- certification evidence: `docs/technical/platform-surfaces-endpoint-certification.md`

### `GET /health/ready`

- returns readiness only when:
  - the service is not draining
  - the durable metadata store is reachable
  - lineage storage is present and usable
- lineage storage usability includes a real write/delete health probe by default, not just path existence checks
- failure contract:
  - `503 {"status":"draining"}`
  - `503 {"status":"unavailable","reason":"durable_metadata_store_unreachable"}`
  - `503 {"status":"unavailable","reason":"lineage_storage_path_missing"}`
  - `503 {"status":"unavailable","reason":"lineage_storage_write_probe_failed"}`
- readiness failures may also include `remediation_hint` when the service has a concrete recovery recommendation
- response model: `app.models.platform_surfaces.HealthStatusResponse`
- certification evidence: `docs/technical/platform-surfaces-endpoint-certification.md`

### `GET /metrics`

- Prometheus metrics surface
- contract note:
  - served as `text/plain` Prometheus exposition format, not JSON
- includes durable queue metrics for compute and lineage backlog/failure pressure
- operator runbook:
  - `docs/runbooks/runtime-alerts.md` is the governed first-response guide for queue, storage, and recovery-drill breach gauges
- alert templates:
  - `docs/operations/runtime-alert-rule-templates.md` provides Prometheus-style expressions for the breach and availability gauges exported here
- alert policy:
  - `docs/standards/runtime-alert-policy.md` defines the default severity and response class for these breach and availability gauges
- threshold profiles:
  - `docs/standards/runtime-threshold-profiles.md` defines recommended dev, staging, and production values for the runtime degradation settings behind these gauges
  - `docs/examples/runtime-thresholds.production.env` and its dev/staging companions provide concrete env overlays for those settings
  - `docs/examples/docker-compose.runtime-thresholds.production.yml` and its dev/staging companions provide compose-ready override files for the same thresholds
- certification evidence: `docs/technical/platform-surfaces-endpoint-certification.md`
- includes alert-ready queue policy breach metrics:
  - `lotus_performance_compute_queue_degradation_breach{reason=...}`
  - `lotus_performance_lineage_queue_degradation_breach{reason=...}`
- includes recovery assurance metrics:
  - `lotus_performance_recovery_drill_availability`
  - `lotus_performance_recovery_drill_action_availability`
  - `lotus_performance_recovery_drill_active_actions`
  - `lotus_performance_recovery_drill_oldest_active_action_age_seconds`
  - `lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds`
  - `lotus_performance_recovery_drill_reclaimed_actions`
  - `lotus_performance_recovery_drill_latest_age_seconds`
  - `lotus_performance_recovery_drill_policy_threshold{threshold="max_age_seconds|active_run_age_seconds|reclaim_count"}`
  - `lotus_performance_recovery_drill_degradation_breach{reason="recovery_drill_latest_not_passed|recovery_drill_age_exceeded|recovery_drill_active_run_age_exceeded|recovery_drill_reclaim_pressure_exceeded"}`
- includes runtime-retention lifecycle metrics:
  - `lotus_performance_runtime_retention_availability`
  - `lotus_performance_runtime_retention_action_availability`
  - `lotus_performance_runtime_retention_active_actions`
  - `lotus_performance_runtime_retention_oldest_active_action_age_seconds`
  - `lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds`
  - `lotus_performance_runtime_retention_reclaimed_actions`
  - `lotus_performance_runtime_retention_preview_availability`
  - `lotus_performance_runtime_retention_latest_age_seconds`
  - `lotus_performance_runtime_retention_policy_threshold{threshold="max_age_seconds|active_run_age_seconds|reclaim_count"}`
  - `lotus_performance_runtime_retention_degradation_breach{reason="runtime_retention_latest_not_applied|runtime_retention_age_exceeded|runtime_retention_active_run_age_exceeded|runtime_retention_reclaim_pressure_exceeded"}`
  - `lotus_performance_runtime_retention_prunable_items{category="execution|compute_job|async_result|lineage_record|lineage_artifact"}`
- `GET /integration/runtime-status` now also carries bounded `recent_reclaimed_runs` lists for both governed action lanes, so operators can inspect the last few stale-lease recoveries without leaving the primary control-plane snapshot
- includes lineage storage capacity metrics:
  - `lotus_performance_lineage_storage_capacity_availability`
  - `lotus_performance_lineage_storage_capacity_bytes{segment="total|used|free"}`
  - `lotus_performance_lineage_storage_free_ratio`
  - `lotus_performance_lineage_storage_pressure_threshold{threshold="min_free_bytes|min_free_ratio"}`

## Runtime Operations

### `python scripts/runtime_retention_cleanup.py`

- purpose: inspect or prune retained terminal runtime state and lineage artifacts beyond the configured retention window
- governed runbook:
  - `docs/runbooks/runtime-retention-cleanup.md`
- default behavior:
  - dry run only
  - prints a JSON summary of prunable runtime records and lineage artifact directories
- apply behavior:
  - `python scripts/runtime_retention_cleanup.py --apply`
- override behavior:
  - `python scripts/runtime_retention_cleanup.py --retention-days <days>`
- scheduled automation behavior:
  - `python scripts/runtime_retention_cleanup.py --scheduled --apply`
  - evidence records `trigger_mode` plus the configured automation `job_id`
  - `make runtime-retention-smoke` runs the governed scheduled dry-run path with retained evidence
- safety contract:
  - only terminal executions, terminal compute jobs, async results, terminal lineage metadata, and matching lineage artifacts older than the cutoff are eligible
  - active runtime work is not pruned
  - each execution persists timestamped evidence plus refreshed `latest.json` and `manifest.json` under the configured retention artifact directory

### `GET /integration/runtime-retention-cleanups`

- purpose: inspect retained runtime-retention cleanup evidence and history
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - retained cleanup artifact directory
  - latest retained cleanup evidence file
  - configured cleanup-history retention policy
  - paged retained cleanup entries with operator, trigger mode, optional job identity, cleanup mode, status, retention window, and prunable record counts
- query parameters:
  - `limit`
  - `offset`
  - `operator_id`
  - `trigger_mode`
  - `job_id`
  - `cleanup_mode`
  - `status`
  - `generated_after`
  - `generated_before`
- governed runbook:
  - `docs/runbooks/runtime-retention-cleanup.md`
  - the optional runtime-retention worker uses the same scheduled automation identity and persisted evidence path
  - `lotus_performance_lineage_storage_pressure_breach{reason="lineage_storage_free_bytes_below_threshold|lineage_storage_free_ratio_below_threshold"}`

## Async execution pattern

Executor-backed endpoints use one common pattern:

1. client submits a calculation request
2. API returns either a final result or `202 Accepted`
3. client polls `/performance/executions/{calculation_id}`
4. client retrieves the endpoint-specific async result at the provided `result_path`

`calculation_id` is a durable execution handle, not a best-effort correlation field:

- callers may omit `calculation_id`; lotus-performance generates one and returns it on both sync and async submissions
- async endpoints treat an exact resubmission with the same `calculation_id` as an idempotent replay and return the same accepted handle
- reusing the same `calculation_id` with a different payload returns `409 Conflict`
- synchronous endpoints require a fresh `calculation_id` for each new submission

## Contract guidance

- prefer Swagger/OpenAPI for exact field-level descriptions and examples
- use the execution polling endpoint as the source of truth for async lifecycle state
- use lineage retrieval for artifact discovery, not as a proxy for execution completion
