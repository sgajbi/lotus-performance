# Returns-Series Operator Triage

- Service: `lotus-performance`
- Scope: first response for stale, partial, or degraded `POST /integration/returns/series` executions
- Primary surfaces:
  - `POST /integration/returns/series`
  - `GET /integration/returns/series/results/{calculation_id}`
  - `GET /performance/executions/{calculation_id}`
  - `GET /integration/runtime-status`
  - `GET /integration/runtime-work-items?queue=compute`
  - `GET /integration/runtime-recoveries?queue=compute`

Use this runbook when a downstream risk workflow, API client, alert, or support ticket reports stale
returns-series freshness, partial coverage, side-series fill evidence, skipped risk-free source rows,
retained gaps, async result failure, or elevated
`lotus_performance_calculation_supportability_total{operation="returns_series"}` samples.

## First Response

1. Capture support-safe identifiers: `calculation_id`, endpoint path, response status, `correlation_id`, `request_id`, `trace_id`, and the bounded diagnostics fields. Do not copy portfolio names, client names, request payloads, or raw source rows into tickets.
2. Check `GET /health/ready` and `GET /integration/runtime-status`.
3. For `202 Accepted` or missing async results, poll `GET /performance/executions/{calculation_id}` and `GET /integration/returns/series/results/{calculation_id}`.
4. If compute execution is stuck or failed, inspect `GET /integration/runtime-work-items?queue=compute` and `GET /integration/runtime-recoveries?queue=compute`.
5. If the completed response is stale or degraded, classify the diagnostic posture below before escalating.

## Diagnostic Posture

| Signal | Support meaning | First owner |
| --- | --- | --- |
| `diagnostics.freshness="stale"` | The latest selected source evidence is older than the required observation date. | `lotus-performance` triages; source freshness may escalate to `lotus-core`. |
| `diagnostics.coverage.missing_points > 0` | Returned portfolio points do not cover all required dates under the selected calendar policy. | `lotus-performance` validates policy and source window; `lotus-core` owns missing stateful source facts. |
| `diagnostics.gaps[]` | A selected portfolio, benchmark, or risk-free series retained a gap after policy application. | `lotus-performance` owns gap diagnostics; upstream source owners own missing facts. |
| `diagnostics.fill_evidence[]` | A selected benchmark or risk-free side-series point was synthesized by `FORWARD_FILL` or `ZERO_FILL`, not observed directly in the source series. | `lotus-performance` owns policy application; source owners own the original side-series gap when filled points are unexpected. |
| `diagnostics.risk_free_source_quality.skipped_points > 0` | Stateful risk-free source rows were malformed, unusable, or used unsupported day-count conventions. | `lotus-performance` owns normalization; `lotus-core` owns source payload correction. |
| `diagnostics.warnings[]` | Non-fatal policy degradation, including max-gap tolerance warnings. | `lotus-performance`. |

MARKET calendar requests use the Lotus reference market trading calendar, not a weekday-only
approximation. If a reported gap falls on a supported market holiday such as Good Friday, verify the
request used `calendar_policy=MARKET` before raising a source-data defect.

## Metrics And Alerts

Completed responses emit:

- `lotus_performance_calculation_supportability_total{operation="returns_series",supportability_state,reason,freshness_bucket}`
- `lotus_analytics_freshness_bucket_total{service="lotus-performance",operation="returns_series",freshness_bucket,supportability_state}`

Bounded mapping:

- current and complete: `supportability_state="ready"`, `reason="calculation_complete"`
- stale freshness: `supportability_state="stale"`, `reason="stale_source_observations"`
- partial coverage, retained gaps, warnings, or skipped risk-free rows: `supportability_state="degraded"`, `reason="calculation_quality_issue"`

Metric labels must not include portfolio, client, tenant, account, benchmark, calculation, trace,
correlation, request, or response payload identifiers.

## Escalation Boundaries

- `lotus-performance`: returns-series API behavior, diagnostics calculation, async result route,
  benchmark calculation path, metric emission, and this runbook.
- `lotus-core`: stateful portfolio analytics timeseries, benchmark assignment or vendor benchmark
  return rows, risk-free source payload shape, and source observation freshness.
- `lotus-risk`: downstream polling budgets, risk calculation interpretation, and risk-panel user
  messaging after a valid returns-series response is received.

Escalate to `lotus-risk` only after `lotus-performance` has either produced a completed
returns-series response or identified a performance-owned execution failure. Escalate to
`lotus-core` only with bounded evidence: source family, required date, latest source date, skipped
row count, and upstream endpoint family. Do not attach raw portfolio/client payloads.

## Closure Evidence

Record these fields in the incident or GitHub issue:

- `calculation_id`
- response status and result route
- `diagnostics.freshness`
- `diagnostics.coverage.requested_points`, `returned_points`, and `missing_points`
- count of `diagnostics.gaps`
- count of `diagnostics.fill_evidence` and bounded filled-date samples when present
- `diagnostics.risk_free_source_quality` counts when present
- observed metric labels for `operation="returns_series"`
- owner boundary selected for follow-up
