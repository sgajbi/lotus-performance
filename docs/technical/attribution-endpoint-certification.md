# Attribution Endpoint Certification

This note records the production-readiness checks for `POST /performance/attribution` and
`GET /performance/attribution/results/{calculation_id}`.

## Purpose

Use attribution when a portfolio needs benchmark-relative explanation of active return. The endpoint
decomposes active return into:

- allocation effect
- selection effect
- interaction effect
- total effect

It is the performance-owned surface for Brinson-style active return attribution. It is not a risk
factor attribution, risk contribution, or standalone return endpoint.

## Supported Modes

The endpoint supports:

- stateless instrument-level attribution with `mode="by_instrument"`
- stateless pre-aggregated group attribution with `mode="by_group"`
- stateful position and benchmark sourcing through lotus-core analytics-input contracts
- synchronous responses for smaller requests
- asynchronous execution with `202 Accepted`, `poll_path`, and `result_path` for heavier requests

Stateful attribution is currently fenced to:

- `mode="by_instrument"`
- `group_by` values `asset_class`, `sector`, `country`, and `currency`
- `currency_mode="BOTH"` only when `report_ccy` is supplied
- mixed-currency sourced positions only when required FX rates are supplied, using trimmed and
  uppercased source `position_currency` and `report_ccy` codes for comparison

## Output Checks

Certification must validate more than headline active return. For every tested period and level:

- every group has average portfolio weight and benchmark weight in percentage units
- every group has linked portfolio and benchmark return in percentage-point units
- every group satisfies `total_effect = allocation + selection + interaction`
- level `totals` equal the sum of all group allocation, selection, interaction, and total effect values
- explicit `allocation_total_pct`, `selection_total_pct`, `interaction_total_pct`, and
  `total_effect_pct` match the nested `totals` block
- reconciliation `sum_of_effects` equals the top-level attribution level total effect
- reconciliation residual is explained by linking, rounding, or source-data gaps
- linked attribution does not report a clean linked state when a portfolio or benchmark period
  return is less than or equal to `-100%`; the period must emit `linking_invalid_return_chain`
  and `supportability_evidence.linking_status="invalid_return_chain"`
- currency attribution effects are present only when the currency attribution contract is active
- missing portfolio or benchmark grouping labels are preserved under an `unknown` bucket rather than
  dropped from the grouped panel
- portfolio and benchmark average weights should be interpreted as attribution beginning weights,
  not necessarily as end-user holdings exposure; source cash-flow timing can create negative cash or
  above-100% invested buckets when beginning-of-period cash movements fund positions

Downstream systems should use the explicit `*_total_pct` fields for footers and summary-only views.
They must not infer authoritative totals by summing visible rows because a UI may filter, truncate, or
hide rows.

## Upstream Integration

Stateful attribution sources portfolio and position analytics inputs from lotus-core query control
plane contracts:

- `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries`
- `POST /integration/portfolios/{portfolio_id}/analytics/position-timeseries`

Benchmark assignment and benchmark component inputs are resolved through the shared benchmark
sourcing path. lotus-core provides source data; lotus-performance owns attribution calculations,
linking, reconciliation, lineage, and response semantics.

Position source grain is preserved through `source_position_key`. Account, custody, book, sleeve,
strategy, mandate, and tax-lot discriminators prevent same-date rows with the same business
`position_id` from overwriting each other; attribution uses the source grain as the instrument
identity while carrying the original business `position_id` as `business_position_id` metadata.

Stateful normalization now records bounded source-alignment evidence during execution-stage
normalization. The evidence covers portfolio observation count, position row count, resolved
benchmark id, benchmark component observation count, index record count, classification completeness,
currency/FX source posture, and explicit source-contract limitations. Current source contracts do
not expose benchmark version, classification version, calendar policy, derivative or short flags, or
fee/tax/income breakout fields; those are treated as source-limited and must not be promoted as
supported attribution claims.

When `currency_mode="BOTH"` is source-ready, the response emits both per-currency
`currency_attribution[]` rows and portfolio-level `currency_attribution_totals`. The totals are the
source-owned Karnosky-Singer sum of local allocation, local selection, currency allocation, currency
selection, total effect, and currency bucket count across the emitted rows. If the request groups
by `currency` plus another dimension, `lotus-performance` first recomputes a date/currency panel
using summed weights and weight-averaged local/FX returns; it does not sum granular sector or other
visible-row returns into the FX methodology. Gateway, Workbench, reporting, and manage consumers
should consume these totals rather than reconstructing
portfolio-level FX attribution by summing displayed rows.

## Downstream Consumers

Known consumers:

- `lotus-gateway` performance workspace details use attribution detail for Workbench performance
  analysis panels.
- `lotus-gateway` performance attribution trend uses the same attribution endpoint over multiple
  windows.
- `lotus-workbench` consumes the gateway performance workspace and attribution trend contracts.
- `lotus-risk` does not consume this endpoint for risk attribution; it owns separate risk
  attribution terminology and contracts.

Downstream certification status:

- `lotus-gateway` passes authoritative attribution totals through to the Workbench performance
  detail contract.
- `lotus-gateway#207` is merged. Gateway preserves period `status`, `reason_codes`, detailed
  `reasons`, `residual_materiality`, and `supportability_evidence` through the Performance
  Workspace contract.
- `lotus-workbench#179` is merged. Workbench displays attribution posture, residual materiality,
  and supportability evidence from Gateway rather than reconstructing attribution state locally.
- `lotus-gateway#106` is closed. Gateway now treats row-coverage handling as a governed consumer
  concern instead of an unresolved attribution endpoint defect.
- `lotus-gateway#105` is closed. Gateway no longer depends on UI-side attribution total
  reconstruction for the authoritative totals emitted by `lotus-performance`.

## Supportability and Observability

Completed attribution responses now include `calculation_supportability` with bounded `state`,
`reason`, and `freshness_bucket` values plus input-row, resolved-period, and benchmark-row counts.
The service also increments:

`lotus_performance_calculation_supportability_total{operation="attribution",supportability_state,reason,freshness_bucket}`

Use this block as the source-owned freshness and degraded-state signal for front-office attribution
panels. The response publishes `calculation_supportability.metric_labels` with the same bounded
label keys used by the metric. The metric labels must not include portfolio, tenant, account,
benchmark, calculation, trace, correlation, request body, response body, or security identifiers.

Each resolved attribution period also includes controlled `status`, `reason_codes`, detailed
`reasons`, `supportability_evidence`, and `reconciliation.residual_materiality`. Consumers should
preserve these fields when displaying partial, warning, or degraded attribution output. They should
not collapse a partial period into a green state simply because allocation, selection, and
interaction totals are present. Current controlled reason codes include off-benchmark exposure,
benchmark-only exposure, unclassified segment, missing benchmark data or returns, negative weights,
zero exposure rows, currency-attribution gaps including absent currency grouping or missing local/FX
evidence, skipped linking, invalid linked return chains,
material residuals, and residual-watch posture.

## Canonical Live Findings

For `PB_SG_GLOBAL_BAL_001` as of `2026-04-10`, the stateful attribution endpoint now reconciles
`sum_of_effects` to `total_active_return` for `asset_class`, `sector`, `country`, and `currency`.

Current interpretation caveats:

- `sector` and `country` depend on benchmark index-catalog labels. When lotus-core returns no
  sector or country labels for benchmark components, lotus-performance preserves the benchmark in
  an `unknown` bucket so totals reconcile, but the dimension is not economically rich enough for a
  final front-office sector/country attribution story.
- `portfolio_weight_avg` and `benchmark_weight_avg` are attribution beginning weights. They can be
  negative or above 100% for cash or funding buckets when source cash-flow timing is included in the
  attribution denominator.

## Validation Evidence

Focused validation for attribution changes should include:

```powershell
python -m pytest tests/integration/test_attribution_api.py tests/unit/models/test_attribution_models.py -q
python -m pytest tests/unit/engine/test_attribution.py tests/unit/engine/test_attribution_supportability.py -q
ruff check app/models/attribution_requests.py app/models/attribution_responses.py app/api/endpoints/performance.py engine/attribution.py tests/integration/test_attribution_api.py tests/unit/models/test_attribution_models.py
ruff format --check app/models/attribution_requests.py app/models/attribution_responses.py app/api/endpoints/performance.py engine/attribution.py tests/integration/test_attribution_api.py tests/unit/models/test_attribution_models.py
mypy app/models/attribution_requests.py app/models/attribution_responses.py app/api/endpoints/performance.py engine/attribution.py
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
make check
```

Gateway consumer validation should include the focused performance workspace service tests when the
attribution contract shape changes. Workbench validation should include focused presentation and
performance attribution section tests when product-surface posture changes.
