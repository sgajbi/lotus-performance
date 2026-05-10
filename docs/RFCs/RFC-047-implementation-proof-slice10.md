# RFC 047 Slice 10 - Implementation Proof and Live Front-Office Evidence

Status: Complete  
Date: 2026-05-10  
Repository branch: `lotus-performance/docs/rfc-contribution-carino-alignment`  
Performance commit under test: `1660b5115434ac915e5aa0865480c7e2daa6eb27`

## Purpose

Slice 10 proves the RFC 047 contribution analytics implementation against the live canonical
front-office stack, not only against isolated unit or integration tests. The proof covers the
`lotus-performance` contribution API, Gateway performance routes, Workbench product surfaces,
execution lineage, source economics evidence, Carino smoothing evidence, readiness, metrics, and
structured logs.

The live stack was left running after validation by operator request because another agent was
using the same stack.

## Branch and Governance Check

Before starting this slice, the branch hygiene check was run:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result: the only relevant unmerged governance branch in `lotus-performance` was
`origin/docs/rfc-contribution-carino-alignment`, classified as `active` for RFC 047.

## Canonical Front-Office Proof

Command run from `lotus-workbench`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/live/Start-LotusFrontOfficeCanonical.ps1 `
  -BuildImages `
  -RunValidation `
  -ScreenshotDirectory output/rfc047-slice10-live-proof
```

Result: passed.

Evidence:

1. Workbench live evidence directory:
   `C:\Users\Sandeep\projects\lotus-workbench\output\rfc047-slice10-live-proof`
2. Machine-readable validation summary:
   `C:\Users\Sandeep\projects\lotus-workbench\output\rfc047-slice10-live-proof\live-validation-summary.json`
3. Screenshot index:
   `C:\Users\Sandeep\projects\lotus-workbench\output\rfc047-slice10-live-proof\SHOT-INDEX.md`
4. Performance-local evidence snapshot:
   `output/rfc047-slice10-live-proof/slice10-live-proof-summary.json`

Canonical identifiers:

1. Portfolio: `PB_SG_GLOBAL_BAL_001`
2. Benchmark: `BMK_PB_GLOBAL_BALANCED_60_40`
3. Governed as-of date in Workbench evidence: `2026-04-10`
4. Performance contribution calculation report end date: `2026-05-08`

Workbench validation confirmed the populated front-office screens and machine-readable panel checks,
including:

1. `performance.summary`: ready
2. `performance.analysis.contribution`: ready with 4 contribution level rows
3. `performance.evidence`: ready capability state, with a screenshot classified as
   `truthfully_degraded` while evidence detail state was settling
4. return path table row count: 5
5. attribution detail table row count: 4
6. contribution detail table row count: 4

## Direct Contribution API Proof

Endpoint:

```text
POST http://performance.dev.lotus/performance/contribution
```

Request mode:

1. `input_mode`: `stateful`
2. `portfolio_id`: `PB_SG_GLOBAL_BAL_001`
3. `report_start_date`: `2026-01-01`
4. `report_end_date`: `2026-05-08`
5. `period`: `YTD`
6. `hierarchy`: `asset_class`
7. stateful dimensions: `asset_class`, `sector`, `country`
8. `metric_basis`: `NET`
9. `include_cash_flows`: `true`

Observed response:

1. HTTP status: `200`
2. calculation id: `6991d0ad-5833-4268-a54d-44d826cc852d`
3. `total_portfolio_return`: `-0.691791`
4. `total_contribution`: `-0.6917909999999998`
5. position rows: 11
6. level rows: 4
7. supportability state: ready

Carino smoothing evidence:

1. status: `APPLIED`
2. reason codes:
   - `CARINO_FACTOR_APPLIED`
   - `RAW_CONTRIBUTION_DIFFERS_FROM_LINKED_RETURN`
   - `RESIDUAL_ALLOCATED_TO_RECONCILE_PERIOD`

Source economics evidence:

1. status: `SOURCE_LIMITED`
2. source owner: `lotus-core`
3. upstream snapshot count: 4
4. reason codes:
   - `COMPONENT_PNL_NOT_SOURCE_AUTHORED`
   - `LOTUS_CORE_ANALYTICS_INPUTS_USED`
   - `UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE`
5. unsupported economics:
   - `price_pnl`
   - `income_pnl`
   - `fee_pnl`
   - `tax_pnl`
   - `fx_pnl`
   - `corporate_action_pnl`
   - `derivative_pnl`
   - `cash_pnl`
   - `residual_pnl`

Critical interpretation: this is the correct RFC 047 posture. Lotus now exposes that source-owned
component P&L is not available from the upstream contract rather than inventing unsupported
component attribution.

## Execution and Lineage Proof

Endpoint:

```text
GET http://performance.dev.lotus/performance/executions/6991d0ad-5833-4268-a54d-44d826cc852d
```

Settled execution result:

1. status: `complete`
2. execution mode: `sync`
3. stages:
   - `retrieval`: complete
   - `normalization`: complete
   - `execution`: complete
   - `lineage_materialization`: complete
4. lineage artifacts:
   - `daily_contributions.csv`
   - `portfolio_twr.csv`
   - `request.json`
   - `response.json`
5. upstream snapshots:
   - two `portfolio_timeseries` snapshots from `lotus-core`
   - two `position_timeseries` snapshots from `lotus-core`
   - all four snapshot retrieval statuses were `200`

An immediate execution read briefly saw `lineage_materialization` as `in_progress`. A later settled
read showed it complete with all four artifacts present. That behavior is acceptable for a
near-immediate poll, but the final proof uses the settled complete state.

## Gateway and Workbench Contract Proof

Gateway details endpoint:

```text
GET http://gateway.dev.lotus/api/v1/workbench/PB_SG_GLOBAL_BAL_001/performance/details?period=YTD&chart_frequency=monthly&detail_basis=NET&contribution_dimension=asset_class&attribution_dimension=asset_class&benchmark_code=BMK_PB_GLOBAL_BALANCED_60_40
```

Required caller context headers:

1. `X-Actor-Id`
2. `X-Tenant-Id`
3. `X-Region`

Observed Gateway details result:

1. final evidence state: `supported`
2. partial failures: none
3. contribution rows: 11
4. contribution level rows: 4
5. contribution smoothing status: `APPLIED`
6. contribution source economics status: `SOURCE_LIMITED`
7. calculation roles:
   - `workspace_summary`: execution complete, lineage complete
   - `contribution`: execution complete, lineage complete
   - `attribution`: execution complete, lineage complete

Gateway summary endpoint:

```text
GET http://gateway.dev.lotus/api/v1/workbench/PB_SG_GLOBAL_BAL_001/performance/summary?period=YTD&chart_frequency=monthly&detail_basis=NET&contribution_dimension=asset_class&attribution_dimension=asset_class&benchmark_code=BMK_PB_GLOBAL_BALANCED_60_40
```

Observed Gateway summary result:

1. evidence state: `supported`
2. warnings: none
3. partial failures: none
4. benchmark code: `BMK_PB_GLOBAL_BALANCED_60_40`

Critical interpretation: Slice 7 downstream changes are live. Gateway preserves the
`lotus-performance` contribution return and contribution evidence, and Workbench can render the
source economics and smoothing posture without reverting to the previous misleading alignment to
TWR summary return.

## Health, Metrics, and Logs

Readiness endpoint:

```text
GET http://performance.dev.lotus/health/ready
```

Observed result:

```json
{"status":"ready"}
```

Metrics endpoint:

```text
GET http://performance.dev.lotus/metrics
```

Observed supportability and HTTP metric families included:

1. `lotus_performance_calculation_supportability_total`
2. `http_requests_total{handler="/performance/contribution",method="POST",status="2xx"}`
3. `http_requests_total{handler="/performance/contribution",method="POST",status="4xx"}`
4. attribution supportability metrics

Structured log review from `performance-analytics` confirmed JSON access logs with correlation,
request, and trace identifiers across the direct contribution request, upstream `lotus-core`
timeseries requests, and execution lookup.

## Negative and Boundary Proof

Direct invalid contribution payload proof:

1. a stateful contribution request containing unsupported dimension `currency` returned HTTP `422`;
2. the validation response identified `stateful_input.dimensions[3]`;
3. allowed request dimensions are `asset_class`, `sector`, and `country`.

Critical interpretation: this is correct request validation. The response can still include
source-derived classification metadata such as `currency`; requestable contribution dimensions
remain deliberately narrower until the domain engine supports them.

## Critical Review Findings

Findings closed in this slice:

1. Method confusion was verified: `/performance/contribution` is a `POST` endpoint; a direct `GET`
   correctly returns method-not-allowed behavior.
2. Gateway caller-context enforcement was verified: calls without `X-Actor-Id`, `X-Tenant-Id`, and
   `X-Region` are rejected instead of being silently accepted.
3. Settled Gateway details and summary evidence returned `supported` with no partial failures.
4. Direct execution lineage settled to `complete` and exposed the expected artifacts and upstream
   snapshot fingerprints.

Known observations carried into Slice 11 hardening review:

1. The Workbench screenshot index classified `performance.evidence-live.png` as
   `truthfully_degraded` during validation while direct Gateway details later settled to
   `supported`. Slice 11 should review whether the Workbench validation timing or evidence panel
   classification should wait for settled lineage before classifying the screenshot.
2. The canonical contribution diagnostics reported `position_flow_residual_days: 2` and
   `position_flow_residual_max_bp: 9`. The implementation surfaces this as diagnostics rather than
   hiding it. Slice 11 should decide whether this canonical seed-data condition is acceptable demo
   truth or should be tightened in upstream seed data.
3. Generic panel validation reported source supportability as `unknown` on some summary/analysis
   panel metadata while contribution-specific source economics evidence was present and explicit.
   Slice 11 should review whether panel-level supportability metadata should be upgraded to consume
   the contribution-specific evidence contract.

## Slice Judgment

Slice 10 passes. The live canonical stack, direct `lotus-performance` API, Gateway routes,
Workbench panels, execution lineage, readiness, metrics, logs, and request validation all prove the
RFC 047 implementation is materially live and product-facing.

The proof is not treated as final closure. The observations above are deliberately carried into
Slice 11 so the second-last hardening pass can decide whether to improve validation timing,
canonical seed-data posture, or generic panel metadata before RFC closure.
