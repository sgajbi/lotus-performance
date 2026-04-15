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
- mixed-currency sourced positions only when required FX rates are supplied

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
- `lotus-gateway` issue `#106` tracks the remaining row-coverage concern: the gateway currently
  limits attribution groups to 10 rows without an explicit truncation or coverage signal.
- `lotus-gateway` issue `#105` tracks removal of the historical dependency on UI-side attribution
  total reconstruction once the lotus-performance totals contract is merged.

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
ruff check app/models/attribution_requests.py app/models/attribution_responses.py app/api/endpoints/performance.py engine/attribution.py tests/integration/test_attribution_api.py tests/unit/models/test_attribution_models.py
ruff format --check app/models/attribution_requests.py app/models/attribution_responses.py app/api/endpoints/performance.py engine/attribution.py tests/integration/test_attribution_api.py tests/unit/models/test_attribution_models.py
mypy app/models/attribution_requests.py app/models/attribution_responses.py app/api/endpoints/performance.py engine/attribution.py
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
```

Gateway consumer validation should include the focused performance workspace service tests when the
attribution contract shape changes.
